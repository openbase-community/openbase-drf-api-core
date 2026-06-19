from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import stripe
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from payment.models import Account, Subscription
from payment.views import (
    StripeCheckoutView,
    StripeCustomerPortalView,
    StripeWebhookView,
)

pytestmark = pytest.mark.django_db


TEST_PRICE_IDS = {
    "pro": "price_pro_test",
    "pro_plus": "price_pro_plus_test",
    "ultra": "price_ultra_test",
}


@override_settings(
    ALLOWED_HOSTS=["app.example.com"],
    OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS=TEST_PRICE_IDS,
)
def test_checkout_uses_configured_stripe_price_for_default_tier():
    response, session_create = _create_checkout()
    subscription_data = session_create.call_args.kwargs["subscription_data"]

    assert response.status_code == 200
    assert response.data == {"url": "https://checkout.stripe.test/session"}
    assert session_create.call_args.kwargs["line_items"] == [
        {"price": "price_pro_test", "quantity": 1}
    ]
    assert subscription_data["trial_period_days"] == 1


@override_settings(
    ALLOWED_HOSTS=["app.example.com"],
    OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS=TEST_PRICE_IDS,
)
def test_checkout_uses_requested_subscription_tier():
    response, session_create = _create_checkout(
        monthly_tier_cents=6000,
    )

    subscription_data = session_create.call_args.kwargs["subscription_data"]

    assert response.status_code == 200
    assert session_create.call_args.kwargs["line_items"] == [
        {"price": "price_pro_plus_test", "quantity": 1}
    ]
    assert subscription_data["metadata"] == {
        "openbase_plan_key": "pro_plus",
        "openbase_plan": "Pro+",
        "openbase_monthly_tier_cents": "6000",
    }
    assert "trial_period_days" not in subscription_data


@override_settings(
    ALLOWED_HOSTS=["app.example.com"],
    OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS=TEST_PRICE_IDS,
)
def test_checkout_rejects_unknown_subscription_tier():
    response, session_create = _create_checkout(
        monthly_tier_cents=50000,
    )

    assert response.status_code == 400
    assert session_create.call_count == 0


@override_settings(
    ALLOWED_HOSTS=["app.example.com"],
    OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS={
        "pro": "price_pro_test",
        "pro_plus": "",
        "ultra": "price_ultra_test",
    },
)
def test_checkout_rejects_unconfigured_subscription_tier():
    response, session_create = _create_checkout(monthly_tier_cents=6000)

    assert response.status_code == 400
    assert "OPENBASE_STRIPE_PRO_PLUS_PRICE_ID" in str(response.data)
    assert session_create.call_count == 0


@override_settings(
    ALLOWED_HOSTS=["app.example.com"],
    OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS=TEST_PRICE_IDS,
)
def test_checkout_replaces_missing_stripe_customer_and_retries():
    User = get_user_model()
    user = User.objects.create_user(email="ada@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_test_mode"
    account.save(update_fields=["customer_id"])

    factory = APIRequestFactory()
    request = factory.post(
        "/api/create-checkout-session/",
        {
            "success_url": "https://app.example.com/success",
            "cancel_url": "https://app.example.com/cancel",
        },
        format="json",
        HTTP_HOST="app.example.com",
        secure=True,
    )
    force_authenticate(request, user=user)

    missing_customer = stripe.error.InvalidRequestError(
        "No such customer",
        "customer",
    )
    with (
        patch(
            "payment.views.stripe.checkout.Session.create",
            side_effect=[
                missing_customer,
                SimpleNamespace(url="https://checkout.stripe.test/session"),
            ],
        ) as session_create,
        patch(
            "users.models.stripe.Customer.create",
            return_value=SimpleNamespace(id="cus_live_mode"),
        ) as customer_create,
    ):
        response = StripeCheckoutView.as_view()(request)

    account.refresh_from_db()

    assert response.status_code == 200
    assert response.data == {"url": "https://checkout.stripe.test/session"}
    assert account.customer_id == "cus_live_mode"
    assert customer_create.call_args.kwargs["email"] == "ada@example.com"
    assert session_create.call_count == 2
    assert session_create.call_args_list[0].kwargs["customer"] == "cus_test_mode"
    assert session_create.call_args_list[1].kwargs["customer"] == "cus_live_mode"


@override_settings(ALLOWED_HOSTS=["app.example.com"])
def test_customer_portal_replaces_test_mode_stripe_customer_and_retries():
    User = get_user_model()
    user = User.objects.create_user(email="ada@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_test_mode"
    account.save(update_fields=["customer_id"])

    request = APIRequestFactory().post(
        "/api/customer-portal/",
        {"return_url": "https://app.example.com/dashboard/devspaces"},
        format="json",
        HTTP_HOST="app.example.com",
        secure=True,
    )
    force_authenticate(request, user=user)

    missing_test_mode_customer = stripe.error.InvalidRequestError(
        "No such customer: 'cus_test_mode'; a similar object exists in test mode, "
        "but a live mode key was used to make this request.",
        None,
    )
    with (
        patch(
            "payment.views.stripe.billing_portal.Session.create",
            side_effect=[
                missing_test_mode_customer,
                SimpleNamespace(url="https://billing.stripe.test/session"),
            ],
        ) as session_create,
        patch(
            "users.models.stripe.Customer.create",
            return_value=SimpleNamespace(id="cus_live_mode"),
        ) as customer_create,
    ):
        response = StripeCustomerPortalView.as_view()(request)

    account.refresh_from_db()

    assert response.status_code == 200
    assert response.data == {"url": "https://billing.stripe.test/session"}
    assert account.customer_id == "cus_live_mode"
    assert customer_create.call_args.kwargs["email"] == "ada@example.com"
    assert session_create.call_count == 2
    assert session_create.call_args_list[0].kwargs["customer"] == "cus_test_mode"
    assert session_create.call_args_list[1].kwargs["customer"] == "cus_live_mode"


def test_subscription_deleted_webhook_expires_subscription_and_terminates_resources():
    User = get_user_model()
    user = User.objects.create_user(email="ada@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_live_mode"
    account.save(update_fields=["customer_id"])
    subscription = Subscription.objects.create(
        account=account,
        subscription_type="prod_pro",
        expiration_date=timezone.now() + timedelta(days=30),
        platform_data={},
    )
    event = SimpleNamespace(
        type="customer.subscription.deleted",
        data=SimpleNamespace(
            object={
                "customer": "cus_live_mode",
                "items": {"data": [{"price": {"product": "prod_pro"}}]},
            }
        ),
    )
    request = APIRequestFactory().post(
        "/api/stripe-webhook/",
        b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="sig_test",
    )

    with (
        patch("payment.views.stripe.Webhook.construct_event", return_value=event),
        patch(
            "payment.views.terminate_user_running_resources",
            return_value={
                "devspaces_terminated": 1,
                "deployment_teardowns_queued": 2,
            },
        ) as terminate_resources,
    ):
        response = StripeWebhookView.as_view()(request)

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.expiration_date <= timezone.now()
    terminate_resources.assert_called_once_with(user)


def _create_checkout(*, monthly_tier_cents=None):
    User = get_user_model()
    user = User.objects.create_user(email="ada@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_test"
    account.save(update_fields=["customer_id"])

    factory = APIRequestFactory()
    payload = {
        "success_url": "https://app.example.com/success",
        "cancel_url": "https://app.example.com/cancel",
    }
    if monthly_tier_cents is not None:
        payload["monthly_tier_cents"] = monthly_tier_cents
    request = factory.post(
        "/api/create-checkout-session/",
        payload,
        format="json",
        HTTP_HOST="app.example.com",
        secure=True,
    )
    force_authenticate(request, user=user)

    with patch(
        "payment.views.stripe.checkout.Session.create",
        return_value=SimpleNamespace(url="https://checkout.stripe.test/session"),
    ) as session_create:
        response = StripeCheckoutView.as_view()(request)

    return response, session_create
