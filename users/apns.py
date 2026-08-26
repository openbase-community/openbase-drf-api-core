import time

import httpx
import jwt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _get_required_apns_setting(name: str) -> str:
    value = getattr(settings, name, None)
    if not isinstance(value, str) or not value.strip():
        raise ImproperlyConfigured(
            f"{name} must be configured as a non-empty string to send APNS notifications."
        )
    return value


async def send_apns_request(
    *,
    token: str,
    payload: dict,
    push_type: str,
    topic: str,
    expiration: int,
    priority: int = 10,
    sandbox: bool | None = None,
) -> httpx.Response:
    use_sandbox = settings.NOTIFICATIONS_SANDBOX if sandbox is None else sandbox
    host = (
        "api.sandbox.push.apple.com"
        if use_sandbox
        else "api.push.apple.com"
    )
    team_id = _get_required_apns_setting("NOTIFICATIONS_APPLE_TEAM_ID")
    auth_key_id = _get_required_apns_setting("NOTIFICATIONS_APPLE_AUTH_KEY_ID")
    p8_contents = _get_required_apns_setting("NOTIFICATIONS_APPLE_P8_CONTENTS")
    provider_token = jwt.encode(
        payload={"iss": team_id, "iat": time.time()},
        key=p8_contents,
        algorithm="ES256",
        headers={"alg": "ES256", "kid": auth_key_id},
    )
    headers = {
        "apns-expiration": str(expiration),
        "apns-priority": str(priority),
        "apns-push-type": push_type,
        "apns-topic": topic,
        "authorization": f"bearer {provider_token}",
    }
    async with httpx.AsyncClient(http2=True) as client:
        return await client.post(
            f"https://{host}:443/3/device/{token}",
            json=payload,
            headers=headers,
        )
