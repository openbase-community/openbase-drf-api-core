from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from payment.models import Account
from payment.views import StripeCheckoutView

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

    assert response.status_code == 200
    assert response.data == {"url": "https://checkout.stripe.test/session"}
    assert session_create.call_args.kwargs["line_items"] == [
        {"price": "price_pro_test", "quantity": 1}
    ]


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
