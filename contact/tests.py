import pytest
from django.contrib.sites.models import Site
from django.core import mail
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
    CONTACT_NOTIFICATION_EMAIL="admin@example.com",
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

    assert email.to == ["admin@example.com"]
    assert email.reply_to == ["ada@example.com"]
    assert email.from_email == "Contact Example <team@contact.example.com>"
    assert email.subject == "New contact submission for Contact Example"
    assert "Ada Lovelace" in email.body
    assert "ada@example.com" in email.body
    assert "I need help with billing." in email.body
