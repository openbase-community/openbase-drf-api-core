from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from payment.models import Subscription
from users.serializers import UserSerializer

pytestmark = pytest.mark.django_db


@override_settings(STRIPE_SECRET_KEY=None)
def test_user_serializer_does_not_require_stripe_key():
    user = get_user_model().objects.create_user(email="staff@example.com")

    with patch("users.models.stripe.Customer.create_async") as create_async:
        data = UserSerializer(user).data

    assert data["balance"] == Decimal("0")
    assert data["active_subscription"] is None
    create_async.assert_not_called()


def test_user_serializer_reports_active_subscription():
    user = _create_user("subscriber@example.com")
    account = user.get_account()
    Subscription.objects.create(
        account=account,
        subscription_type="pro",
        expiration_date=timezone.now() + timezone.timedelta(days=7),
    )

    data = UserSerializer(user).data

    assert data["active_subscription"] == "pro"


def _create_user(email):
    with patch(
        "users.models.stripe.Customer.create",
        return_value=SimpleNamespace(id="cus_test"),
    ):
        return get_user_model().objects.create_user(email=email)
