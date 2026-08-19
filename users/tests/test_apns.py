# ruff: noqa: S106 - APNs device-token fixtures are identifiers, not credentials.

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from users.models import UserAPNSToken
from users.views import APNSView

pytestmark = pytest.mark.django_db


def test_registers_device_token():
    user = _create_user("first@example.com")

    response = _request("post", user, {"token": "device-token"})

    assert response.status_code == 200
    assert UserAPNSToken.objects.get(token="device-token").user == user


def test_updates_current_users_device_token():
    user = _create_user("first@example.com")
    UserAPNSToken.objects.create(user=user, token="old-token")

    response = _request("post", user, {"token": "new-token"})

    assert response.status_code == 200
    assert not UserAPNSToken.objects.filter(token="old-token").exists()
    assert UserAPNSToken.objects.get(token="new-token").user == user


def test_transfers_device_token_between_accounts():
    old_user = _create_user("old@example.com")
    new_user = _create_user("new@example.com")
    UserAPNSToken.objects.create(user=old_user, token="shared-device-token")
    UserAPNSToken.objects.create(user=new_user, token="other-device-token")

    response = _request("post", new_user, {"token": "shared-device-token"})

    assert response.status_code == 200
    assert UserAPNSToken.objects.count() == 1
    assert UserAPNSToken.objects.get(token="shared-device-token").user == new_user


def test_unregisters_current_users_device_token_only():
    user = _create_user("first@example.com")
    other_user = _create_user("other@example.com")
    UserAPNSToken.objects.create(user=user, token="first-token")
    UserAPNSToken.objects.create(user=other_user, token="other-token")

    response = _request("delete", user)

    assert response.status_code == 200
    assert not UserAPNSToken.objects.filter(user=user).exists()
    assert UserAPNSToken.objects.get(token="other-token").user == other_user


def test_unregister_is_idempotent():
    user = _create_user("first@example.com")

    response = _request("delete", user)

    assert response.status_code == 200


def _request(method, user, data=None):
    factory = APIRequestFactory()
    request = getattr(factory, method)("/api/apns/", data=data, format="json")
    force_authenticate(request, user=user)
    return APNSView.as_view()(request)


def _create_user(email):
    with patch(
        "users.models.stripe.Customer.create",
        return_value=SimpleNamespace(id="cus_test"),
    ):
        return get_user_model().objects.create_user(email=email)
