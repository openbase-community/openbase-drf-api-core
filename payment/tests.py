from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.test import override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from payment.models import Account
from payment.views import StripeCheckoutView
from sites.models import SiteAttributes

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_site_cache():
    yield
    Site.objects.clear_cache()


@override_settings(ALLOWED_HOSTS=["app.example.com"], SITE_ID=None)
def test_checkout_uses_inline_product_data_for_placeholder_product_id():
    response, session_create = _create_checkout(stripe_product_id="prod_implementme")

    price_data = session_create.call_args.kwargs["line_items"][0]["price_data"]

    assert response.status_code == 200
    assert response.data == {"url": "https://checkout.stripe.test/session"}
    assert price_data["product_data"] == {"name": "Openbase Cloud"}
    assert "product" not in price_data
    assert price_data["unit_amount"] == 2000


@override_settings(ALLOWED_HOSTS=["app.example.com"], SITE_ID=None)
def test_checkout_uses_requested_subscription_tier():
    response, session_create = _create_checkout(
        stripe_product_id="prod_implementme",
        monthly_tier_cents=10000,
    )

    price_data = session_create.call_args.kwargs["line_items"][0]["price_data"]

    assert response.status_code == 200
    assert price_data["unit_amount"] == 10000


@override_settings(ALLOWED_HOSTS=["app.example.com"], SITE_ID=None)
def test_checkout_rejects_unknown_subscription_tier():
    response, session_create = _create_checkout(
        stripe_product_id="prod_implementme",
        monthly_tier_cents=50000,
    )

    assert response.status_code == 400
    assert session_create.call_count == 0


@override_settings(ALLOWED_HOSTS=["app.example.com"], SITE_ID=None)
def test_checkout_uses_configured_stripe_product_id():
    response, session_create = _create_checkout(stripe_product_id="prod_real")

    price_data = session_create.call_args.kwargs["line_items"][0]["price_data"]

    assert response.status_code == 200
    assert price_data["product"] == "prod_real"
    assert "product_data" not in price_data


def _create_checkout(*, stripe_product_id, monthly_tier_cents=None):
    site = Site.objects.create(domain="app.example.com", name="Openbase Cloud")
    SiteAttributes.objects.create(
        site=site,
        stripe_product_id=stripe_product_id,
        stripe_price_cents=2000,
    )

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
