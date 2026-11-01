"""The shared pytest plugin keeps every suite off the real Stripe API."""

import pytest
import stripe
from django.contrib.auth import get_user_model

from payment.models import Account


def test_unpatched_stripe_calls_fail_the_test():
    with pytest.raises(AssertionError, match="real Stripe API call: GET"):
        stripe.Subscription.retrieve("sub_should_never_be_fetched")


@pytest.mark.django_db
def test_creating_a_user_gets_a_local_customer_id(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_not_a_real_key"  # noqa: S105

    user = get_user_model().objects.create_user(email="plugin@example.com")

    account = Account.objects.get(user_owner=user)
    assert account.customer_id.startswith("cus_test_")


@pytest.mark.django_db
def test_creating_a_user_without_stripe_configured_skips_customer(settings):
    settings.STRIPE_SECRET_KEY = ""

    user = get_user_model().objects.create_user(email="no-stripe@example.com")

    assert Account.objects.get(user_owner=user).customer_id in ("", None)
