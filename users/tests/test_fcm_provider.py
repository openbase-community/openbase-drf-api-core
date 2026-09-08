import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from asgiref.sync import async_to_sync
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from users import fcm
from users.fcm import send_fcm_request

SERVICE_ACCOUNT = {
    "type": "service_account",
    "project_id": "openbase-test",
    "client_email": "sender@openbase-test.iam.gserviceaccount.com",
    "private_key": "test-signing-key",
    "token_uri": "https://oauth2.example.test/token",
}


@pytest.fixture(autouse=True)
def clear_token_cache():
    fcm._token_cache.update({"access_token": None, "expires_at": 0.0})
    yield
    fcm._token_cache.update({"access_token": None, "expires_at": 0.0})


class Client:
    def __init__(self, requests):
        self.requests = requests

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if "oauth2" in url:
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"access_token": "access-token", "expires_in": 3600},
                raise_for_status=lambda: None,
            )
        return SimpleNamespace(status_code=200, content=b"")


@override_settings(NOTIFICATIONS_FCM_SERVICE_ACCOUNT_JSON=json.dumps(SERVICE_ACCOUNT))
def test_send_fcm_request_exchanges_oauth_and_posts_v1_message():
    requests = []
    with (
        patch("users.fcm.jwt.encode", return_value="signed-assertion"),
        patch(
            "users.fcm.httpx.AsyncClient",
            side_effect=lambda **_kwargs: Client(requests),
        ),
    ):
        async_to_sync(send_fcm_request)(
            token="fcm-token-1",
            data={"invitation_id": "A" * 43},
            android_priority="high",
            ttl_seconds=55,
        )

    oauth_url, oauth_kwargs = requests[0]
    assert oauth_url == SERVICE_ACCOUNT["token_uri"]
    assert oauth_kwargs["data"]["assertion"] == "signed-assertion"

    send_url, send_kwargs = requests[1]
    assert send_url == (
        "https://fcm.googleapis.com/v1/projects/openbase-test/messages:send"
    )
    assert send_kwargs["headers"] == {"authorization": "Bearer access-token"}
    assert send_kwargs["json"] == {
        "message": {
            "token": "fcm-token-1",
            "android": {"priority": "high", "ttl": "55s"},
            "data": {"invitation_id": "A" * 43},
        }
    }


@override_settings(NOTIFICATIONS_FCM_SERVICE_ACCOUNT_JSON=json.dumps(SERVICE_ACCOUNT))
def test_send_fcm_request_reuses_cached_access_token():
    requests = []
    with (
        patch("users.fcm.jwt.encode", return_value="signed-assertion"),
        patch(
            "users.fcm.httpx.AsyncClient",
            side_effect=lambda **_kwargs: Client(requests),
        ),
    ):
        async_to_sync(send_fcm_request)(token="fcm-token-1")
        async_to_sync(send_fcm_request)(token="fcm-token-2")

    oauth_requests = [url for url, _kwargs in requests if "oauth2" in url]
    send_requests = [url for url, _kwargs in requests if "fcm.googleapis" in url]
    assert len(oauth_requests) == 1
    assert len(send_requests) == 2


@pytest.mark.parametrize(
    "raw_value",
    [
        "",
        "   ",
        "not-json",
        json.dumps({"client_email": "sender@example.test"}),
    ],
)
def test_send_fcm_request_requires_valid_service_account(raw_value):
    with (
        override_settings(NOTIFICATIONS_FCM_SERVICE_ACCOUNT_JSON=raw_value),
        patch("users.fcm.jwt.encode") as encode,
        pytest.raises(ImproperlyConfigured, match="NOTIFICATIONS_FCM"),
    ):
        async_to_sync(send_fcm_request)(token="fcm-token-1")

    encode.assert_not_called()
