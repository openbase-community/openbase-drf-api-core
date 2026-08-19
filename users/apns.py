import time

import httpx
import jwt
from django.conf import settings


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
    provider_token = jwt.encode(
        payload={"iss": settings.NOTIFICATIONS_APPLE_TEAM_ID, "iat": time.time()},
        key=settings.NOTIFICATIONS_APPLE_P8_CONTENTS,
        algorithm="ES256",
        headers={"alg": "ES256", "kid": settings.NOTIFICATIONS_APPLE_AUTH_KEY_ID},
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
