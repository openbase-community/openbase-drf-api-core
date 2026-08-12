import pytest
from django.contrib.sites.models import Site
from django.core.management import call_command
from django.test import Client, override_settings

pytestmark = pytest.mark.django_db


@override_settings(ALLOWED_HOSTS=["testserver"], SITE_ID=None)
def test_login_page_renders_without_any_social_app():
    # A deployment site with no configured social provider must still render
    # the login page rather than 500 on the hardcoded provider button.
    Site.objects.update_or_create(domain="testserver", defaults={"name": "testserver"})

    response = Client().get("/accounts/login/")

    assert response.status_code == 200
    assert b"google-login-button" not in response.content


@override_settings(ALLOWED_HOSTS=["testserver"], SITE_ID=None)
def test_login_page_shows_provider_configured_for_the_current_site():
    Site.objects.update_or_create(domain="testserver", defaults={"name": "testserver"})
    call_command(
        "ensure_google_oauth",
        credentials_json='{"web": {"client_id": "id", "client_secret": "s"}}',
        site_domains=["testserver"],
    )

    response = Client().get("/accounts/login/")

    assert response.status_code == 200
    assert b"google-login-button" in response.content
