# ruff: noqa: S106 - APNs device-token fixtures are identifiers, not credentials.

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import override_settings

from users.models import UserAPNSToken
from users.tasks import send_apn


@pytest.mark.django_db(transaction=True)
@override_settings(
    NOTIFICATIONS_APPLE_TEAM_ID="team-id",
    NOTIFICATIONS_APPLE_AUTH_KEY_ID="key-id",
    NOTIFICATIONS_APPLE_P8_CONTENTS="test-signing-key",
    NOTIFICATIONS_SANDBOX=False,
    APPLE_BUNDLE_ID="com.example.app",
)
def test_send_apn_declares_alert_push_type():
    with patch(
        "users.models.stripe.Customer.create",
        return_value=SimpleNamespace(id="cus_test"),
    ):
        user = get_user_model().objects.create_user(email="first@example.com")
    UserAPNSToken.objects.create(user=user, token="device-token")
    requests = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            requests.append((url, kwargs))
            return SimpleNamespace(status_code=200, content=b"")

    with (
        patch("users.apns.jwt.encode", return_value="provider-token"),
        patch("users.apns.httpx.AsyncClient", return_value=Client()),
    ):
        async_to_sync(send_apn.original_func)(
            user.pk,
            {"title": "Dottie", "body": "Review is ready"},
            {"openbase_destination": "threads", "thread_id": "thread-42"},
        )

    assert requests[0][1]["headers"]["apns-push-type"] == "alert"
    assert requests[0][1]["headers"]["apns-topic"] == "com.example.app"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("status_code", "reason"),
    [
        (400, "BadDeviceToken"),
        (410, "Unregistered"),
    ],
)
def test_send_apn_deletes_definitively_invalid_tokens(status_code, reason):
    with patch(
        "users.models.stripe.Customer.create",
        return_value=SimpleNamespace(id="cus_test"),
    ):
        user = get_user_model().objects.create_user(email="invalid-apn@example.com")
    token = UserAPNSToken.objects.create(user=user, token="invalid-device-token")
    mocked_send = AsyncMock(
        return_value=SimpleNamespace(
            status_code=status_code,
            content=(f'{{"reason":"{reason}"}}').encode(),
        )
    )

    with (
        patch("users.tasks.send_apns_request", mocked_send),
        patch("users.tasks.logger") as logger,
    ):
        async_to_sync(send_apn.original_func)(
            user.pk,
            {"title": "Dottie", "body": "Review is ready"},
        )

    assert not UserAPNSToken.objects.filter(pk=token.pk).exists()
    logger.info.assert_called_once_with(
        "Removed rejected APN token",
        status_code=status_code,
        reason=reason,
        user_id=user.pk,
    )
    logger.error.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_send_apn_keeps_token_for_non_token_rejection():
    with patch(
        "users.models.stripe.Customer.create",
        return_value=SimpleNamespace(id="cus_test"),
    ):
        user = get_user_model().objects.create_user(email="provider-error@example.com")
    token = UserAPNSToken.objects.create(user=user, token="device-token")
    mocked_send = AsyncMock(
        return_value=SimpleNamespace(
            status_code=403,
            content=b'{"reason":"InvalidProviderToken"}',
        )
    )

    with (
        patch("users.tasks.send_apns_request", mocked_send),
        patch("users.tasks.logger") as logger,
    ):
        async_to_sync(send_apn.original_func)(
            user.pk,
            {"title": "Dottie", "body": "Review is ready"},
        )

    assert UserAPNSToken.objects.filter(pk=token.pk).exists()
    logger.error.assert_called_once_with(
        "Could not send APN",
        status_code=403,
        reason="InvalidProviderToken",
        response_content='{"reason":"InvalidProviderToken"}',
        user_id=user.pk,
    )
