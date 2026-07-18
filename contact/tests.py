import os
from unittest import mock

import pytest
from django.contrib.sites.models import Site
from django.core import mail
from django.core.cache import cache
from django.test import override_settings

from contact.models import ContactSubmission
from sites.models import SiteAttributes

pytestmark = pytest.mark.django_db


@pytest.fixture
def contact_site():
    site = Site.objects.create(
        domain="contact.example.com",
        name="Contact Example",
    )
    SiteAttributes.objects.create(
        site=site,
        from_email="team@contact.example.com",
    )
    yield site
    Site.objects.clear_cache()


@override_settings(
    ALLOWED_HOSTS=["contact.example.com"],
    CONTACT_NOTIFICATION_EMAILS=[
        "gabe@openbase.cloud",
        "lucas@openbase.cloud",
        "zoky@openbase.cloud",
    ],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SITE_ID=None,
)
def test_submit_contact_sends_admin_notification_email(client, contact_site):
    response = client.post(
        "/api/contact/",
        {
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "message": "I need help with billing.",
        },
        HTTP_HOST=contact_site.domain,
    )

    assert response.status_code == 201
    assert ContactSubmission.objects.count() == 1
    assert len(mail.outbox) == 1

    email = mail.outbox[0]

    assert email.to == [
        "gabe@openbase.cloud",
        "lucas@openbase.cloud",
        "zoky@openbase.cloud",
    ]
    assert email.reply_to == ["ada@example.com"]
    assert email.from_email == "Contact Example <team@contact.example.com>"
    assert email.subject == "New contact submission for Contact Example"
    assert "Ada Lovelace" in email.body
    assert "ada@example.com" in email.body
    assert "I need help with billing." in email.body


@override_settings(
    ALLOWED_HOSTS=["contact.example.com"],
    CONTACT_NOTIFICATION_EMAILS=["gabe@openbase.cloud"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SITE_ID=None,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "contact-throttle-test",
        }
    },
)
def test_submit_contact_is_rate_limited_per_ip(client, contact_site):
    cache.clear()
    payload = {"name": "Ada", "email": "ada@example.com", "message": "hello"}
    with mock.patch.dict(os.environ, {"CONTACT_SUBMISSION_THROTTLE_RATE": "3/hour"}):
        statuses = [
            client.post(
                "/api/contact/", payload, HTTP_HOST=contact_site.domain
            ).status_code
            for _ in range(4)
        ]

    assert statuses[:3] == [201, 201, 201]
    assert statuses[3] == 429
    assert ContactSubmission.objects.count() == 3
