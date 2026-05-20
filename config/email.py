import os
from email.mime.base import MIMEBase

import resend
from django.contrib.sites.models import Site
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import EmailAttachment, EmailMessage

from sites.models import SiteAttributes
from sites.utils import get_current_site_attributes


def format_from_email(display_name: str, from_email: str) -> str:
    return f"{display_name} <{from_email}>"


def get_request_from_email(request) -> str:
    site = get_current_site(request)
    site_attributes = get_current_site_attributes(request)
    if site is None:
        msg = "Current site is required to determine the from email address."
        raise ValueError(msg)
    if site_attributes is None:
        msg = (
            "Current site attributes are required to determine the from email address."
        )
        raise ValueError(msg)
    return format_from_email(site.name, site_attributes.from_email)


def get_site_from_email(site_id: int) -> str:
    site = Site.objects.select_related("attributes").get(id=site_id)
    try:
        site_attributes = site.attributes
    except SiteAttributes.DoesNotExist as exc:
        msg = f"Site {site_id} is missing site attributes required for email sending."
        raise ValueError(msg) from exc
    return format_from_email(site.name, site_attributes.from_email)


class ResendEmailBackend(BaseEmailBackend):
    def open(self):
        resend.api_key = os.environ["RESEND_API_KEY"]
        return True

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        self.open()
        sent_count = 0
        for email_message in email_messages:
            if not email_message.recipients():
                continue
            try:
                resend.Emails.send(self._build_send_params(email_message))
            except Exception:
                if not self.fail_silently:
                    raise
            else:
                sent_count += 1
        return sent_count

    def _build_send_params(
        self, email_message: EmailMessage
    ) -> resend.Emails.SendParams:
        text_body, html_body = self._extract_bodies(email_message)
        if text_body is None and html_body is None:
            msg = "Either text or html content is required to send an email."
            raise ValueError(msg)

        params: resend.Emails.SendParams = {
            "from": email_message.from_email,
            "to": email_message.to,
            "subject": email_message.subject,
        }
        if text_body is not None:
            params["text"] = text_body
        if html_body is not None:
            params["html"] = html_body
        if email_message.cc:
            params["cc"] = email_message.cc
        if email_message.bcc:
            params["bcc"] = email_message.bcc
        if email_message.reply_to:
            params["reply_to"] = email_message.reply_to
        if email_message.extra_headers:
            params["headers"] = {
                key: str(value) for key, value in email_message.extra_headers.items()
            }
        attachments = self._build_attachments(email_message)
        if attachments:
            params["attachments"] = attachments
        return params

    @staticmethod
    def _extract_bodies(email_message: EmailMessage) -> tuple[str | None, str | None]:
        text_body = None
        html_body = None

        if email_message.content_subtype == "html":
            html_body = email_message.body or None
        else:
            text_body = email_message.body or None

        for alternative in getattr(email_message, "alternatives", ()):
            if alternative.mimetype == "text/plain":
                text_body = alternative.content
            elif alternative.mimetype == "text/html":
                html_body = alternative.content

        return text_body, html_body

    @staticmethod
    def _build_attachments(email_message: EmailMessage) -> list[resend.Attachment]:
        attachments: list[resend.Attachment] = []
        for attachment in email_message.attachments:
            if isinstance(attachment, MIMEBase):
                msg = "MIMEBase attachments are not supported by ResendEmailBackend."
                raise TypeError(msg)
            if not isinstance(attachment, EmailAttachment):
                msg = "Unsupported attachment type for ResendEmailBackend."
                raise TypeError(msg)

            content = attachment.content
            if isinstance(content, bytes):
                content = list(content)

            resend_attachment: resend.Attachment = {
                "filename": attachment.filename,
                "content": content,
            }
            if attachment.mimetype:
                resend_attachment["content_type"] = attachment.mimetype
            attachments.append(resend_attachment)
        return attachments
