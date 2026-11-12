"""The one-time notice to accounts that signed in with a password.

Shared by the ``users.0003_password_retirement_notice`` data migration, which
sends it once when the passwordless release is deployed, and by the
``password_retirement_notice`` management command, which previews or re-sends
it. Both pass the model they have (the migration its historical model), so the
selection reads raw fields and never calls methods on ``User``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import structlog
from django.conf import settings
from django.contrib.auth.hashers import is_password_usable
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string

from config.email import format_from_email, get_site_from_email

logger = structlog.get_logger(__name__)

SUBJECT = "{brand} is retiring password sign-in"
TEXT_TEMPLATE = "users/email/password_retirement_notice.txt"
HTML_TEMPLATE = "users/email/password_retirement_notice.html"


@dataclass(frozen=True)
class Recipient:
    user_id: int
    email: str
    first_name: str
    site_id: int | None


@dataclass
class NoticeResult:
    recipients: int = 0
    sent: int = 0
    # The mail backend accepted the message but delivered to nobody: the
    # address is a non-delivery domain (example.com, .test) the Resend backend
    # filters out.
    filtered: int = 0
    failed: int = 0
    dry_run: bool = False
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "recipients": self.recipients,
            "sent": self.sent,
            "filtered": self.filtered,
            "failed": self.failed,
            "dry_run": self.dry_run,
            "failures": list(self.failures),
        }


def password_retirement_recipients(user_model) -> list[Recipient]:
    """Active accounts whose stored password still works.

    Accounts without a usable password (social signups, imported accounts)
    never signed in with one and have nothing to be told.
    """
    rows = (
        user_model.objects.filter(is_active=True)
        .order_by("id")
        .values_list("id", "email", "first_name", "password", "site_id")
    )
    return [
        Recipient(user_id=user_id, email=email, first_name=first_name, site_id=site_id)
        for user_id, email, first_name, password, site_id in rows
        if email and is_password_usable(password)
    ]


def notice_context(recipient: Recipient) -> dict:
    return {
        "brand": settings.PASSWORD_RETIREMENT_NOTICE_BRAND,
        "first_name": (recipient.first_name or "").strip(),
        "email": recipient.email,
        "login_url": settings.PASSWORD_RETIREMENT_NOTICE_LOGIN_URL,
        "support_email": settings.PASSWORD_RETIREMENT_NOTICE_SUPPORT_EMAIL,
    }


def build_notice(recipient: Recipient) -> EmailMultiAlternatives:
    context = notice_context(recipient)
    message = EmailMultiAlternatives(
        subject=SUBJECT.format(brand=context["brand"]),
        body=render_to_string(TEXT_TEMPLATE, context),
        from_email=_from_email(recipient, context["brand"]),
        to=[recipient.email],
        reply_to=[context["support_email"]],
    )
    message.attach_alternative(render_to_string(HTML_TEMPLATE, context), "text/html")
    return message


def _from_email(recipient: Recipient, brand: str) -> str | None:
    if recipient.site_id is not None:
        return get_site_from_email(recipient.site_id)
    default_from_email = os.environ.get("DEFAULT_FROM_EMAIL", "").strip()
    if default_from_email:
        return format_from_email(brand, default_from_email)
    # Django falls back to settings.DEFAULT_FROM_EMAIL.
    return None


def send_password_retirement_notices(
    user_model, *, dry_run: bool = False
) -> NoticeResult:
    """Mail every recipient once; a failed address is logged and skipped so one
    bounce cannot hold up the deploy that runs the migration."""
    recipients = password_retirement_recipients(user_model)
    result = NoticeResult(recipients=len(recipients), dry_run=dry_run)
    if dry_run:
        return result
    connection = get_connection()
    for recipient in recipients:
        message = build_notice(recipient)
        try:
            delivered = connection.send_messages([message])
        except Exception as exc:  # one bad address must not stop the rest
            result.failed += 1
            result.failures.append(f"user {recipient.user_id}: {type(exc).__name__}")
            logger.exception(
                "password_retirement_notice_failed",
                user_id=recipient.user_id,
                exception_class=type(exc).__name__,
            )
            continue
        if delivered:
            result.sent += 1
        else:
            result.filtered += 1
    logger.info("password_retirement_notice_sent", **result.as_dict())
    return result
