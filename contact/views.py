from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from rest_framework import generics
from rest_framework.permissions import AllowAny

from config.email import get_request_from_email
from contact import serializers


class SubmitContactView(generics.CreateAPIView):
    serializer_class = serializers.ContactSubmissionSerializer
    queryset = serializers.ContactSubmission.objects.all()
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        site = get_current_site(self.request)
        submission = serializer.save(site=site)
        self._send_admin_notification(submission)

    def _send_admin_notification(self, submission):
        if not settings.CONTACT_NOTIFICATION_EMAIL:
            msg = "CONTACT_NOTIFICATION_EMAIL must be set to send contact notifications."
            raise ValueError(msg)

        site = submission.site
        email_message = EmailMessage(
            subject=f"New contact submission for {site.name if site else 'site'}",
            body=render_to_string(
                "contact/admin_notification.txt",
                {"submission": submission, "site": site},
            ),
            to=[settings.CONTACT_NOTIFICATION_EMAIL],
            from_email=get_request_from_email(self.request),
            reply_to=[submission.email],
        )
        email_message.send()
