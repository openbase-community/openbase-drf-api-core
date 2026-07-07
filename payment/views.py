from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

import stripe
import structlog
from appstoreserverlibrary.api_client import (
    APIException,
    AppStoreServerAPIClient,
    GetTransactionHistoryVersion,
)
from appstoreserverlibrary.models import Data
from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.models.HistoryResponse import HistoryResponse
from appstoreserverlibrary.models.JWSTransactionDecodedPayload import (
    JWSTransactionDecodedPayload,
)
from appstoreserverlibrary.models.NotificationTypeV2 import NotificationTypeV2
from appstoreserverlibrary.models.ResponseBodyV2DecodedPayload import (
    ResponseBodyV2DecodedPayload,
)
from appstoreserverlibrary.models.TransactionHistoryRequest import (
    Order,
    ProductType,
    TransactionHistoryRequest,
)
from appstoreserverlibrary.signed_data_verifier import (
    SignedDataVerifier,
    VerificationException,
)
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from payment import serializers
from payment.models import Account, Subscription
from payment.subscription_hooks import run_subscription_cancellation_hooks
from payment.tiers import (
    subscription_tier,
    subscription_tier_price_id,
    validate_subscription_tier_cents,
)

stripe.api_key = settings.STRIPE_SECRET_KEY

logger = structlog.get_logger(__name__)


def stripe_error_is_missing_customer(error: stripe.error.StripeError) -> bool:
    if not isinstance(error, stripe.error.InvalidRequestError):
        return False
    if getattr(error, "param", None) == "customer":
        return True

    error_message = str(error).lower()
    return "no such customer" in error_message and "cus_" in error_message


class AddValueView(generics.CreateAPIView):
    serializer_class = serializers.AddValueSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = serializers.AddValueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment_method_id = serializer.validated_data["payment_method_id"]  # type: ignore
        amount = serializer.validated_data["amount"]  # type: ignore
        account = request.user.get_account()
        try:
            _ = stripe.PaymentIntent.create(
                amount=int(amount * 100),
                currency="usd",
                payment_method=payment_method_id,
                confirm=True,
                customer=account.customer_id,
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            )
            account.balance += amount
            account.save()
            return JsonResponse({"success": True})
        except stripe.error.CardError as e:
            logger.exception(
                "Payment failed",
                user_id=request.user.id,
                amount=amount,
                error=e.user_message,
            )
            return JsonResponse({"error": e.user_message}, status=400)
        except stripe.error.StripeError as e:
            # Non-card Stripe failures (rate limit, API, network) are not the
            # user's fault; surface a generic message and a 502 rather than a
            # raw 500 from an uncaught exception.
            logger.exception(
                "Stripe payment error",
                user_id=request.user.id,
                amount=amount,
                error=str(e),
            )
            return JsonResponse(
                {"error": "Payment could not be processed. Please try again."},
                status=502,
            )


class AddValueHistoryView(generics.ListAPIView):
    serializer_class = serializers.AddValueHistorySerializer

    def get_queryset(self):
        # Get Stripe PaymentIntents
        payment_intents = stripe.PaymentIntent.list(
            customer=self.request.user.get_account().customer_id
        )
        return [
            {
                "date": datetime.fromtimestamp(pi.created, tz=UTC),
                "amount": pi.amount / 100,
                "status": pi.status,
            }
            for pi in payment_intents.data
        ]


def load_root_certificates():
    cert_dir = Path(__file__).resolve().parent / "certs"
    cert_paths = [
        cert_dir / "AppleRootCA-G3.cer",
        cert_dir / "AppleRootCA-G2.cer",
        cert_dir / "AppleIncRootCertificate.cer",
        cert_dir / "AppleComputerRootCertificate.cer",
    ]
    certs = []

    for path in cert_paths:
        with path.open("rb") as file:
            certs.append(file.read())
    return certs


def get_create_apple_subscription(subscription_info: JWSTransactionDecodedPayload):
    product_id = subscription_info.productId
    expires_timestamp = subscription_info.expiresDate
    environment = subscription_info.environment
    delta = (
        timedelta(days=1)
        if environment != Environment.SANDBOX
        else timedelta(seconds=1)
    )
    expires_date = datetime.fromtimestamp(expires_timestamp / 1000, tz=UTC) + delta
    app_account_token = subscription_info.appAccountToken
    logger.info("Received subscription", environment=str(environment))
    logger.info(
        "Received subscription payload", subscription_info=str(subscription_info)
    )

    with transaction.atomic():
        account = (
            Account.objects.select_for_update()
            .filter(apple_uuid=app_account_token)
            .first()
        )
        if account is None:
            # Apple redelivers on non-2xx, but retrying an unknown
            # appAccountToken can never succeed, so ack and log loudly.
            logger.error(
                "Account not found for apple subscription",
                apple_uuid=app_account_token,
            )
            return None

        subscription, _created = Subscription.objects.update_or_create(
            account=account,
            defaults={
                "subscription_type": product_id,
                "expiration_date": expires_date,
                "platform_data": str(subscription_info),
                "is_sandbox": environment == Environment.SANDBOX,
            },
        )

    return subscription


@cache
def get_signed_data_verifiers():
    root_certificates = load_root_certificates()

    signed_data_verifiers = []
    for environment in [Environment.PRODUCTION, Environment.SANDBOX]:
        app_apple_id = (
            settings.APPLE_APP_APPLE_ID
        )  # appAppleId must be provided for the Production environment
        signed_data_verifier = SignedDataVerifier(
            root_certificates=root_certificates,
            enable_online_checks=True,
            environment=environment,
            bundle_id=settings.APPLE_BUNDLE_ID,
            app_apple_id=app_apple_id,
        )
        signed_data_verifiers.append(signed_data_verifier)
    return tuple(signed_data_verifiers)


def verify_and_decode_notification(notification):
    prod_verifier, sandbox_verifier = get_signed_data_verifiers()
    try:
        return prod_verifier.verify_and_decode_notification(notification)
    except VerificationException as prod_exception:
        try:
            return sandbox_verifier.verify_and_decode_notification(notification)
        except VerificationException:
            raise prod_exception from None


def verify_and_decode_signed_transaction(signed_transaction):
    prod_verifier, sandbox_verifier = get_signed_data_verifiers()
    try:
        return prod_verifier.verify_and_decode_signed_transaction(signed_transaction)
    except VerificationException as prod_exception:
        try:
            return sandbox_verifier.verify_and_decode_signed_transaction(
                signed_transaction
            )
        except VerificationException:
            raise prod_exception from None


class AppleWebhookView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        request=serializers.WebhookPayloadSerializer,
        responses=serializers.PaymentMessageResponseSerializer,
    )
    def post(self, request, *args, **kwargs):
        signed_notification = request.data.get("signedPayload")
        if not signed_notification:
            return Response(
                {"error": "Signed payload not provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            payload: ResponseBodyV2DecodedPayload = verify_and_decode_notification(
                signed_notification
            )
            type_ = payload.notificationType
            logger.info("Received Apple notification", notification_type=str(type_))
            if type_ == NotificationTypeV2.TEST:
                logger.info("Test notification")
            elif type_ in (NotificationTypeV2.SUBSCRIBED, NotificationTypeV2.DID_RENEW):
                logger.info("Subscribed notification")
                data: Data = payload.data
                signed_transaction_info = data.signedTransactionInfo
                subscription_info = verify_and_decode_signed_transaction(
                    signed_transaction_info
                )
        except VerificationException as e:
            # Never ack a payload we could not verify: a 2xx here would tell
            # Apple the notification was processed and it would never retry.
            logger.exception("Apple webhook verification failed", error=str(e))
            return Response(
                {"error": "Signed payload verification failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if type_ in (NotificationTypeV2.SUBSCRIBED, NotificationTypeV2.DID_RENEW):
            # Persistence errors propagate as a 500 so Apple redelivers.
            get_create_apple_subscription(subscription_info)

        return Response({"message": "Received"})


def get_apple_storekit_api_clients():
    clients = []
    for environment in [Environment.PRODUCTION, Environment.SANDBOX]:
        private_key = settings.APPLE_STOREKIT_P8_CONTENTS.encode()
        key_id = settings.APPLE_STOREKIT_KEY_ID
        issuer_id = settings.APPLE_STOREKIT_ISSUER_ID
        bundle_id = settings.APPLE_BUNDLE_ID
        client = AppStoreServerAPIClient(
            signing_key=private_key,
            key_id=key_id,
            issuer_id=issuer_id,
            bundle_id=bundle_id,
            environment=environment,
        )
        clients.append(client)
    return tuple(clients)


def get_transaction_history(
    transaction_id: str,
    revision: str | None,
    transaction_history_request: TransactionHistoryRequest,
    version: GetTransactionHistoryVersion = GetTransactionHistoryVersion.V1,
):
    prod_client, sandbox_client = get_apple_storekit_api_clients()
    try:
        return prod_client.get_transaction_history(
            transaction_id, revision, transaction_history_request, version
        )
    except APIException:
        return sandbox_client.get_transaction_history(
            transaction_id, revision, transaction_history_request, version
        )


# For user-uploaded transaction IDs
class AppleSubscription(APIView):
    @extend_schema(
        request=serializers.AppleSubscriptionRequestSerializer,
        responses=serializers.PaymentMessageResponseSerializer,
    )
    def post(self, request, *args, **kwargs):
        transaction_id = str(request.data.get("transaction_id"))
        if transaction_id is None:
            return Response(
                {"error": "Transaction ID not provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transactions = []
        response: HistoryResponse | None = None
        request: TransactionHistoryRequest = TransactionHistoryRequest(
            sort=Order.ASCENDING,
            revoked=False,
            productTypes=[ProductType.AUTO_RENEWABLE],
        )
        while response is None or response.hasMore:
            revision = response.revision if response is not None else None
            response = get_transaction_history(
                transaction_id, revision, request, GetTransactionHistoryVersion.V2
            )
            transactions.extend(response.signedTransactions)

        if not transactions:
            logger.error("No transactions found", transaction_id=transaction_id)
            msg = "No transactions found"
            raise ValidationError(msg)
        last_transaction = transactions[-1]
        last_transaction_info = verify_and_decode_signed_transaction(last_transaction)
        _ = get_create_apple_subscription(last_transaction_info)

        return Response({"message": "Received"})


class StripeCustomerPortalView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=serializers.StripeCustomerPortalRequestSerializer,
        responses={
            200: serializers.URLResponseSerializer,
            400: serializers.PaymentErrorResponseSerializer,
        },
    )
    def post(self, request, *args, **kwargs):
        account = request.user.get_account()
        if not account.customer_id:
            return Response(
                {"error": "No Stripe customer found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get the base URL from the current request
        protocol = "https" if request.is_secure() else "http"
        domain = request.get_host()
        default_return_url = f"{protocol}://{domain}/settings/"

        # Allow override of return URL but default to the current site
        return_url = request.data.get("return_url", default_return_url)

        try:
            try:
                session = stripe.billing_portal.Session.create(
                    customer=account.customer_id,
                    return_url=return_url,
                )
            except stripe.error.StripeError as e:
                if not stripe_error_is_missing_customer(e):
                    raise
                account = request.user.create_stripe_customer(account)
                session = stripe.billing_portal.Session.create(
                    customer=account.customer_id,
                    return_url=return_url,
                )
            return Response({"url": session.url})
        except stripe.error.StripeError as e:
            logger.exception("Stripe portal session creation failed", error=str(e))
            return Response(
                {"error": "Failed to create portal session"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class StripeCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=serializers.StripeCheckoutRequestSerializer,
        responses={
            200: serializers.URLResponseSerializer,
            400: serializers.PaymentErrorResponseSerializer,
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = serializers.StripeCheckoutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = request.user.get_account()

        # Get the base URL from the current request
        protocol = "https" if request.is_secure() else "http"
        domain = request.get_host()
        base_url = f"{protocol}://{domain}"

        # Allow override of success/cancel URLs but default to the current site
        success_url = serializer.validated_data.get(
            "success_url",
            f"{base_url}/settings/",
        )
        cancel_url = serializer.validated_data.get(
            "cancel_url",
            f"{base_url}/settings/",
        )
        monthly_tier_cents = serializer.validated_data.get("monthly_tier_cents")
        normalized_tier_cents = validate_subscription_tier_cents(monthly_tier_cents)

        try:
            session = create_checkout_session(
                account=account,
                normalized_tier_cents=normalized_tier_cents,
                success_url=success_url,
                cancel_url=cancel_url,
            )
            return Response({"url": session.url})
        except stripe.error.StripeError as e:
            if not stripe_error_is_missing_customer(e):
                logger.exception(
                    "Stripe checkout session creation failed", error=str(e)
                )
                return Response(
                    {"error": "Failed to create checkout session"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                account = request.user.create_stripe_customer(account)
                session = create_checkout_session(
                    account=account,
                    normalized_tier_cents=normalized_tier_cents,
                    success_url=success_url,
                    cancel_url=cancel_url,
                )
                return Response({"url": session.url})
            except stripe.error.StripeError as retry_error:
                logger.exception(
                    "Stripe checkout session creation failed",
                    error=str(retry_error),
                )
                return Response(
                    {"error": "Failed to create checkout session"},
                    status=status.HTTP_400_BAD_REQUEST,
                )


def create_checkout_session(*, account, normalized_tier_cents, success_url, cancel_url):
    tier = subscription_tier(normalized_tier_cents)
    subscription_data = {
        "metadata": {
            "openbase_plan_key": tier["plan"],
            "openbase_plan": tier["name"],
            "openbase_monthly_tier_cents": str(normalized_tier_cents),
        },
    }
    trial_period_days = tier.get("trial_period_days")
    if trial_period_days:
        subscription_data["trial_period_days"] = trial_period_days

    return stripe.checkout.Session.create(
        customer=account.customer_id,
        payment_method_types=["card"],
        line_items=[
            {
                "price": subscription_tier_price_id(normalized_tier_cents),
                "quantity": 1,
            }
        ],
        mode="subscription",
        subscription_data=subscription_data,
        success_url=success_url,
        cancel_url=cancel_url,
    )


def expire_subscription_and_terminate_resources(
    account: Account,
    *,
    platform_data,
) -> dict[str, int]:
    with transaction.atomic():
        Account.objects.select_for_update().get(pk=account.pk)
        Subscription.objects.update_or_create(
            account=account,
            defaults={
                "subscription_type": stripe_subscription_product_id(platform_data),
                "expiration_date": timezone.now(),
                "platform_data": platform_data,
            },
        )
    if not account.user_owner:
        return {}
    # Hooks run after the expiration commit: provider teardown (cloud API
    # calls) must never sit inside a DB transaction. If a hook fails, the
    # error propagates as a 5xx, the payment provider redelivers the webhook,
    # the expiration upsert is a no-op, and the idempotent hooks retry.
    return run_subscription_cancellation_hooks(account.user_owner)


def stripe_subscription_item(subscription_object):
    items = subscription_object.get("items", {}).get("data", [{}])
    # Subscriptions may carry metered add-on items (e.g. pay-as-you-go
    # overage prices); the licensed flat-fee item is the one that identifies
    # the plan and billing period.
    for item in items:
        recurring = item.get("price", {}).get("recurring") or {}
        if recurring.get("usage_type") != "metered":
            return item
    return items[0] if items else {}


def stripe_subscription_product_id(subscription_object) -> str:
    return str(
        stripe_subscription_item(subscription_object)
        .get("price", {})
        .get("product", "")
    )


def stripe_subscription_period_end_timestamp(subscription_object):
    return (
        subscription_object.get("current_period_end")
        or stripe_subscription_item(subscription_object).get("current_period_end")
        or subscription_object.get("trial_end")
    )


def stripe_subscription_is_canceling(subscription_object) -> bool:
    return bool(
        subscription_object.get("cancel_at")
        or subscription_object.get("cancel_at_period_end")
        or subscription_object.get("canceled_at")
        or subscription_object.get("ended_at")
        or subscription_object.get("status") == "canceled"
    )


class StripeWebhookView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={200: None, 400: None},
    )
    def post(self, request, *args, **kwargs):
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            logger.exception("Invalid Stripe webhook payload", error=str(e))
            return Response(status=status.HTTP_400_BAD_REQUEST)
        except stripe.error.SignatureVerificationError as e:
            logger.exception("Invalid Stripe webhook signature", error=str(e))
            return Response(status=status.HTTP_400_BAD_REQUEST)

        # Handle subscription events
        if event.type.startswith("customer.subscription."):
            subscription_object = event.data.object
            try:
                account = Account.objects.get(
                    customer_id=subscription_object["customer"]
                )
            except Account.DoesNotExist:
                logger.exception(
                    "No account found for Stripe customer",
                    customer_id=subscription_object["customer"],
                )
                return Response(status=status.HTTP_400_BAD_REQUEST)

            subscription_is_canceling = stripe_subscription_is_canceling(
                subscription_object
            )

            if (
                event.type == "customer.subscription.deleted"
                or subscription_is_canceling
            ):
                cleanup_result = expire_subscription_and_terminate_resources(
                    account,
                    platform_data=subscription_object,
                )
                logger.info(
                    "Marked subscription as expired and queued resource termination",
                    account_id=account.pk,
                    event_type=event.type,
                    cleanup_result=cleanup_result,
                )
            elif event.type in {
                "customer.subscription.created",
                "customer.subscription.updated",
            }:
                period_end = stripe_subscription_period_end_timestamp(
                    subscription_object
                )
                if not period_end:
                    logger.error(
                        "Stripe subscription webhook missing period end",
                        account_id=account.pk,
                        stripe_subscription_id=subscription_object.get("id"),
                    )
                    return Response(status=status.HTTP_400_BAD_REQUEST)

                current_period_end = datetime.fromtimestamp(period_end, tz=UTC)
                product_id = stripe_subscription_product_id(subscription_object)

                # Lock the account row so concurrent deliveries for the same
                # customer (Stripe retries, out-of-order events) serialize.
                with transaction.atomic():
                    Account.objects.select_for_update().get(pk=account.pk)
                    _subscription, created = Subscription.objects.update_or_create(
                        account=account,
                        defaults={
                            "subscription_type": product_id,
                            "expiration_date": current_period_end,
                            "platform_data": subscription_object,
                        },
                    )
                logger.info(
                    "Subscription synced from Stripe webhook",
                    action="created" if created else "updated",
                    account_id=account.pk,
                )
        return Response(status=status.HTTP_200_OK)
