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
from django.contrib.sites.shortcuts import get_current_site
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
        account = request.user.get_account()

        # Get the base URL from the current request
        protocol = "https" if request.is_secure() else "http"
        domain = request.get_host()
        base_url = f"{protocol}://{domain}"

        # Allow override of success/cancel URLs but default to the current site
        success_url = request.data.get("success_url", f"{base_url}/settings/")
        cancel_url = request.data.get("cancel_url", f"{base_url}/settings/")

        try:
            session = stripe.checkout.Session.create(
                customer=account.customer_id,
                payment_method_types=["card"],
                line_items=[
                    {
                        "price_data": {
                            "product": get_current_site(
                                request
                            ).attributes.stripe_product_id,
                            "recurring": {"interval": "month"},
                            "currency": "usd",
                            "unit_amount": get_current_site(
                                request
                            ).attributes.stripe_price_cents,
                        },
                        "quantity": 1,
                    }
                ],
                mode="subscription",
                success_url=success_url,
                cancel_url=cancel_url,
            )
            return Response({"url": session.url})
        except stripe.error.StripeError as e:
            logger.exception("Stripe checkout session creation failed", error=str(e))
            return Response(
                {"error": "Failed to create checkout session"},
                status=status.HTTP_400_BAD_REQUEST,
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

            if event.type in {
                "customer.subscription.created",
                "customer.subscription.updated",
            }:
                # Get the subscription end date
                current_period_end = datetime.fromtimestamp(
                    subscription_object["current_period_end"], tz=UTC
                )

                # Get the product name/ID for subscription_type
                product_id = subscription_object["items"]["data"][0]["price"]["product"]

                subscription, created = Subscription.objects.update_or_create(
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

            elif event.type == "customer.subscription.deleted":
                try:
                    subscription = Subscription.objects.get(account=account)
                    subscription.expiration_date = timezone.now()
                    subscription.save()
                    logger.info(
                        "Marked subscription as expired",
                        account_id=account.pk,
                    )
                except Subscription.DoesNotExist:
                    pass

        return Response(status=status.HTTP_200_OK)
