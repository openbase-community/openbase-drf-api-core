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
from django.apps import apps
from django.conf import settings
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

stripe.api_key = settings.STRIPE_SECRET_KEY

logger = structlog.get_logger(__name__)
DEFAULT_SUBSCRIPTION_TIER_CENTS = 2000
PRO_TRIAL_PERIOD_DAYS = 1
SUBSCRIPTION_TIERS = {
    2000: {
        "plan": "pro",
        "name": "Pro",
        "price_setting": "OPENBASE_STRIPE_PRO_PRICE_ID",
    },
    6000: {
        "plan": "pro_plus",
        "name": "Pro+",
        "price_setting": "OPENBASE_STRIPE_PRO_PLUS_PRICE_ID",
    },
    20000: {
        "plan": "ultra",
        "name": "Ultra",
        "price_setting": "OPENBASE_STRIPE_ULTRA_PRICE_ID",
    },
}
SUBSCRIPTION_TIER_CENTS = tuple(SUBSCRIPTION_TIERS)


def subscription_tier_cents(value) -> int:
    amount = int(value or DEFAULT_SUBSCRIPTION_TIER_CENTS)
    if amount not in SUBSCRIPTION_TIER_CENTS:
        msg = "Unsupported subscription tier."
        raise ValidationError(msg)
    return amount


def subscription_tier_name(value) -> str:
    return SUBSCRIPTION_TIERS[subscription_tier_cents(value)]["name"]


def subscription_tier_plan(value) -> str:
    return SUBSCRIPTION_TIERS[subscription_tier_cents(value)]["plan"]


def subscription_tier_price_id(value) -> str:
    tier_cents = subscription_tier_cents(value)
    tier = SUBSCRIPTION_TIERS[tier_cents]
    price_ids = getattr(settings, "OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS", {})
    price_id = price_ids.get(tier["plan"], "").strip()
    if not price_id:
        msg = (
            f"Stripe Price ID is not configured for {tier['name']}. "
            f"Set {tier['price_setting']}."
        )
        raise ValidationError(msg)
    return price_id


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
    # assert isinstance(subscription_info, JWSTransactionDecodedPayload)
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

    try:
        account = Account.objects.get(apple_uuid=app_account_token)
    except Account.DoesNotExist:
        logger.exception(
            "Account not found for apple subscription", apple_uuid=app_account_token
        )
        return None

    subscription, created = Subscription.objects.get_or_create(
        account=account,
        defaults={
            "subscription_type": product_id,
            "expiration_date": expires_date,
            "platform_data": str(subscription_info),
            "is_sandbox": environment == Environment.SANDBOX,
        },
    )
    if not created:
        subscription.expiration_date = expires_date
        subscription.subscription_type = product_id
        subscription.platform_data = str(subscription_info)
        subscription.is_sandbox = environment == Environment.SANDBOX
        subscription.save()

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
                get_create_apple_subscription(subscription_info)
        except VerificationException as e:
            logger.exception("Verification failed", error=str(e))

        # Handle Apple's server-to-server notifications here
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
        monthly_tier_cents = serializer.validated_data.get(
            "monthly_tier_cents",
            DEFAULT_SUBSCRIPTION_TIER_CENTS,
        )
        normalized_tier_cents = subscription_tier_cents(monthly_tier_cents)

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
                logger.exception("Stripe checkout session creation failed", error=str(e))
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
    subscription_data = {
        "metadata": {
            "openbase_plan_key": subscription_tier_plan(normalized_tier_cents),
            "openbase_plan": subscription_tier_name(normalized_tier_cents),
            "openbase_monthly_tier_cents": str(normalized_tier_cents),
        },
    }
    if normalized_tier_cents == DEFAULT_SUBSCRIPTION_TIER_CENTS:
        subscription_data["trial_period_days"] = PRO_TRIAL_PERIOD_DAYS

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


def terminate_user_running_resources(user) -> dict[str, int]:
    result = {
        "devspaces_terminated": 0,
        "deployment_teardowns_queued": 0,
    }
    if apps.is_installed("openbase_api.devspaces"):
        result["devspaces_terminated"] = terminate_user_devspaces(user)
    if apps.is_installed("openbase_api.deployment"):
        result["deployment_teardowns_queued"] = queue_user_deployment_teardowns(user)
    return result


def terminate_user_devspaces(user) -> int:
    try:
        from openbase_api.devspaces.usage_limits import (
            terminate_running_devspaces_for_user,
        )
    except ImportError:
        from openbase_api.devspaces.ec2 import DevSpaceEC2Manager
        from openbase_api.devspaces.models import DevSpace
        from openbase_api.devspaces.usage_limits import accrue_running_devspace_usage

        manager = DevSpaceEC2Manager()
        terminated_count = 0
        for devspace in DevSpace.objects.filter(
            user=user,
            status__in=(DevSpace.Status.RUNNING, DevSpace.Status.STARTING),
        ):
            accrue_running_devspace_usage(devspace)
            if devspace.ec2_instance_id:
                manager.terminate_instance(devspace.ec2_instance_id)
            devspace.mark_terminated()
            terminated_count += 1
        return terminated_count

    return terminate_running_devspaces_for_user(user)


def queue_user_deployment_teardowns(user) -> int:
    try:
        from openbase_api.deployment.services import (
            queue_subscription_cancellation_teardowns,
        )
    except ImportError:
        from openbase_api.deployment.services import queue_monthly_spend_limit_teardowns

        return queue_monthly_spend_limit_teardowns(user)

    return queue_subscription_cancellation_teardowns(user)


def expire_subscription_and_terminate_resources(
    account: Account,
    *,
    platform_data,
) -> dict[str, int]:
    Subscription.objects.update_or_create(
        account=account,
        defaults={
            "subscription_type": str(
                (platform_data.get("items", {}).get("data", [{}])[0])
                .get("price", {})
                .get("product", "")
            ),
            "expiration_date": timezone.now(),
            "platform_data": platform_data,
        },
    )
    if not account.user_owner:
        return {
            "devspaces_terminated": 0,
            "deployment_teardowns_queued": 0,
        }
    return terminate_user_running_resources(account.user_owner)


def stripe_subscription_item(subscription_object):
    return subscription_object.get("items", {}).get("data", [{}])[0]


def stripe_subscription_product_id(subscription_object) -> str:
    return str(stripe_subscription_item(subscription_object).get("price", {}).get("product", ""))


def stripe_subscription_period_end_timestamp(subscription_object):
    return (
        subscription_object.get("current_period_end")
        or stripe_subscription_item(subscription_object).get("current_period_end")
        or subscription_object.get("trial_end")
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

            subscription_is_canceling = bool(
                subscription_object.get("cancel_at_period_end")
            )

            if event.type == "customer.subscription.deleted" or subscription_is_canceling:
                cleanup_result = expire_subscription_and_terminate_resources(
                    account,
                    platform_data=subscription_object,
                )
                logger.info(
                    "Marked subscription as expired and queued resource termination",
                    account_id=account.pk,
                    event_type=event.type,
                    **cleanup_result,
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
