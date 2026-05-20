import time

import httpx
import jwt
import structlog
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from twilio.rest import Client

from config.email import get_site_from_email
from config.taskiq_config import broker
from users.models import UserAPNSToken

required_prefix = "From your assistant: "


logger = structlog.get_logger(__name__)


User = get_user_model()


@broker.task
def send_email(subject, message, to_email, site_id=None):
    email_message = EmailMessage(
        subject=subject,
        body=message,
        to=[to_email] if isinstance(to_email, str) else to_email,
        from_email=get_site_from_email(site_id) if site_id is not None else None,
    )
    email_message.content_subtype = "html"
    email_message.send()


@broker.task
def send_sms(message, to_number):
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    client.messages.create(
        to=to_number, from_=settings.OWNED_TWILIO_NUMBER, body=required_prefix + message
    )


@broker.task
async def send_apn(user_id, message, data: dict | None = None):
    user = await User.objects.aget(id=user_id)
    token_instance = await UserAPNSToken.objects.filter(user=user).afirst()
    if not token_instance:
        return
    token = token_instance.token
    team_id = settings.NOTIFICATIONS_APPLE_TEAM_ID
    bundle_id = settings.APPLE_BUNDLE_ID
    auth_key_id = settings.NOTIFICATIONS_APPLE_AUTH_KEY_ID
    # APNs URL for push notifications (use the appropriate server: development or production)
    apns_url_template = (
        "https://api.push.apple.com:443/3/device/{}"
        if not settings.NOTIFICATIONS_SANDBOX
        else "https://api.sandbox.push.apple.com:443/3/device/{}"
    )
    apns_url = apns_url_template.format(token)
    # Generate the JWT token for authentication
    token_headers = {"alg": "ES256", "kid": auth_key_id}
    token_payload = {"iss": team_id, "iat": time.time()}
    auth_key = settings.NOTIFICATIONS_APPLE_P8_CONTENTS
    jwt_token = jwt.encode(
        payload=token_payload, key=auth_key, algorithm="ES256", headers=token_headers
    )
    # Prepare request headers
    request_headers = {
        "apns-expiration": "0",
        "apns-priority": "10",
        "apns-topic": bundle_id,
        "authorization": "bearer " + jwt_token,
    }
    payload = {
        "aps": {
            "alert": message,
            "sound": "default",
        },
    }
    # Add custom data to payload if provided
    if data:
        payload.update(data)
    # Send the notification
    async with httpx.AsyncClient(http2=True) as client:
        response = await client.post(apns_url, json=payload, headers=request_headers)
    if response.status_code >= 400:
        logger.error(
            "Could not send APN",
            status_code=response.status_code,
            response_content=response.content.decode(errors="replace"),
            user_id=user_id,
        )
