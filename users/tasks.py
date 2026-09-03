import structlog
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from twilio.rest import Client

from config.email import get_site_from_email
from config.taskiq_config import broker
from users.apns import send_apns_request
from users.models import UserAPNSToken

required_prefix = "From your assistant: "


logger = structlog.get_logger(__name__)


User = get_user_model()


def _is_email_provider_auth_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status_code in {401, 403, "401", "403"}:
        return True

    exception_name = type(exc).__name__.casefold()
    return exception_name in {
        "invalidapikeyerror",
        "missingapikeyerror",
        "unauthorizederror",
    }


@broker.task
def send_email(subject, message, to_email, site_id=None):
    email_message = EmailMessage(
        subject=subject,
        body=message,
        to=[to_email] if isinstance(to_email, str) else to_email,
        from_email=get_site_from_email(site_id) if site_id is not None else None,
    )
    email_message.content_subtype = "html"
    try:
        email_message.send()
    except Exception as exc:
        if not _is_email_provider_auth_error(exc):
            raise
        logger.error(
            "Email provider authentication failed; email task will not retry",
            exception_class=type(exc).__name__,
            status_code=getattr(exc, "status_code", None) or getattr(exc, "code", None),
            site_id=site_id,
            recipients_count=len(email_message.to),
        )


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
    bundle_id = settings.APPLE_BUNDLE_ID
    payload = {
        "aps": {
            "alert": message,
            "sound": "default",
        },
    }
    # Add custom data to payload if provided
    if data:
        payload.update(data)
    response = await send_apns_request(
        token=token,
        payload=payload,
        push_type="alert",
        topic=bundle_id,
        expiration=0,
    )
    if response.status_code >= 400:
        logger.error(
            "Could not send APN",
            status_code=response.status_code,
            response_content=response.content.decode(errors="replace"),
            user_id=user_id,
        )
