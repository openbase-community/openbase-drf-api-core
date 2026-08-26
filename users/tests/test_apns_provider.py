from types import SimpleNamespace
from unittest.mock import patch

import pytest
from asgiref.sync import async_to_sync
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from users.apns import send_apns_request


@override_settings(
    NOTIFICATIONS_APPLE_TEAM_ID="team-id",
    NOTIFICATIONS_APPLE_AUTH_KEY_ID="key-id",
    NOTIFICATIONS_APPLE_P8_CONTENTS="test-signing-key",
    NOTIFICATIONS_SANDBOX=False,
)
def test_send_apns_request_uses_explicit_sandbox_and_voip_headers():
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
        async_to_sync(send_apns_request)(
            token="a" * 64,
            payload={"aps": {"content-available": 1}},
            push_type="voip",
            topic="com.example.app.voip",
            expiration=1_800_000_000,
            sandbox=True,
        )

    url, kwargs = requests[0]
    assert url == f"https://api.sandbox.push.apple.com:443/3/device/{'a' * 64}"
    assert kwargs["headers"] == {
        "apns-expiration": "1800000000",
        "apns-priority": "10",
        "apns-push-type": "voip",
        "apns-topic": "com.example.app.voip",
        "authorization": "bearer provider-token",
    }
    assert kwargs["json"] == {"aps": {"content-available": 1}}


@pytest.mark.parametrize(
    ("setting_name", "setting_value"),
    [
        ("NOTIFICATIONS_APPLE_TEAM_ID", None),
        ("NOTIFICATIONS_APPLE_TEAM_ID", 123),
        ("NOTIFICATIONS_APPLE_AUTH_KEY_ID", ""),
        ("NOTIFICATIONS_APPLE_P8_CONTENTS", "   "),
    ],
)
def test_send_apns_request_requires_string_credentials(setting_name, setting_value):
    settings_override = {
        "NOTIFICATIONS_APPLE_TEAM_ID": "team-id",
        "NOTIFICATIONS_APPLE_AUTH_KEY_ID": "key-id",
        "NOTIFICATIONS_APPLE_P8_CONTENTS": "test-signing-key",
        "NOTIFICATIONS_SANDBOX": False,
        setting_name: setting_value,
    }

    with (
        override_settings(**settings_override),
        patch("users.apns.jwt.encode") as encode,
        pytest.raises(ImproperlyConfigured, match=setting_name),
    ):
        async_to_sync(send_apns_request)(
            token="a" * 64,
            payload={"aps": {"content-available": 1}},
            push_type="voip",
            topic="com.example.app.voip",
            expiration=1_800_000_000,
            sandbox=True,
        )

    encode.assert_not_called()
