import json
import time

import httpx
import jwt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

FCM_OAUTH_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_ACCESS_TOKEN_LIFETIME_SECONDS = 3600
# Access tokens are valid for an hour; cache one per process so a fan-out of
# many device sends performs a single OAuth exchange.
_token_cache: dict = {"access_token": None, "expires_at": 0.0}


def _get_service_account() -> dict:
    raw = getattr(settings, "NOTIFICATIONS_FCM_SERVICE_ACCOUNT_JSON", "")
    if not isinstance(raw, str) or not raw.strip():
        msg = (
            "NOTIFICATIONS_FCM_SERVICE_ACCOUNT_JSON must be configured with the "
            "Firebase service-account JSON to send FCM notifications."
        )
        raise ImproperlyConfigured(msg)
    try:
        account = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = "NOTIFICATIONS_FCM_SERVICE_ACCOUNT_JSON is not valid JSON."
        raise ImproperlyConfigured(msg) from exc
    missing = [
        field
        for field in ("client_email", "private_key", "project_id", "token_uri")
        if not account.get(field)
    ]
    if missing:
        raise ImproperlyConfigured(
            "NOTIFICATIONS_FCM_SERVICE_ACCOUNT_JSON is missing required fields: "
            + ", ".join(missing)
        )
    return account


async def _get_access_token(account: dict) -> str:
    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] - 60 > now:
        return _token_cache["access_token"]
    assertion = jwt.encode(
        payload={
            "iss": account["client_email"],
            "scope": FCM_OAUTH_SCOPE,
            "aud": account["token_uri"],
            "iat": int(now),
            "exp": int(now) + _ACCESS_TOKEN_LIFETIME_SECONDS,
        },
        key=account["private_key"],
        algorithm="RS256",
    )
    async with httpx.AsyncClient() as client:
        response = await client.post(
            account["token_uri"],
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
    response.raise_for_status()
    body = response.json()
    _token_cache["access_token"] = body["access_token"]
    _token_cache["expires_at"] = now + int(
        body.get("expires_in", _ACCESS_TOKEN_LIFETIME_SECONDS)
    )
    return _token_cache["access_token"]


async def send_fcm_request(
    *,
    token: str,
    data: dict[str, str] | None = None,
    notification: dict[str, str] | None = None,
    android_priority: str = "high",
    ttl_seconds: int | None = None,
) -> httpx.Response:
    """POST one message to the FCM HTTP v1 API.

    Returns the raw response; callers interpret a 404 (UNREGISTERED) as an
    invalid token to prune, mirroring how send_apns_request callers handle
    BadDeviceToken/Unregistered.
    """
    account = _get_service_account()
    access_token = await _get_access_token(account)
    android: dict = {"priority": android_priority}
    if ttl_seconds is not None:
        android["ttl"] = f"{max(0, ttl_seconds)}s"
    message: dict = {"token": token, "android": android}
    if data:
        message["data"] = data
    if notification:
        message["notification"] = notification
    async with httpx.AsyncClient(http2=True) as client:
        return await client.post(
            "https://fcm.googleapis.com/v1/projects/"
            f"{account['project_id']}/messages:send",
            json={"message": message},
            headers={"authorization": f"Bearer {access_token}"},
        )
