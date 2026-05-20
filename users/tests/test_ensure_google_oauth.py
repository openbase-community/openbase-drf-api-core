from io import StringIO

import pytest
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site
from django.core.management import call_command
from django.core.management.base import CommandError


pytestmark = pytest.mark.django_db


def test_ensure_google_oauth_skips_without_credentials_in_non_interactive_mode(
    monkeypatch,
):
    call_command("ensure_default_sites")
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("input() should not be called"))
    stdout = StringIO()

    call_command("ensure_google_oauth", non_interactive=True, stdout=stdout)

    assert "skipping in non-interactive mode" in stdout.getvalue().lower()
    assert not SocialApp.objects.filter(provider="google").exists()


def test_ensure_google_oauth_uses_credentials_json_for_default_site():
    call_command("ensure_default_sites")
    credentials_json = """
    {
      "web": {
        "client_id": "client-id",
        "client_secret": "client-secret"
      }
    }
    """

    call_command("ensure_google_oauth", credentials_json=credentials_json, name="Dev App")

    social_app = SocialApp.objects.get(provider="google")

    assert social_app.name == "Dev App"
    assert social_app.client_id == "client-id"
    assert social_app.secret == "client-secret"
    assert list(social_app.sites.values_list("id", flat=True)) == [1]


def test_ensure_google_oauth_uses_requested_site_domain():
    site = Site.objects.create(
        domain="api.mindfulmakers.xyz",
        name="Wellness Navigator",
    )
    credentials_json = """
    {
      "web": {
        "client_id": "client-id",
        "client_secret": "client-secret"
      }
    }
    """

    call_command(
        "ensure_google_oauth",
        credentials_json=credentials_json,
        name="Wellness Navigator Google",
        site_domains=["api.mindfulmakers.xyz"],
    )

    social_app = SocialApp.objects.get(provider="google")

    assert social_app.name == "Wellness Navigator Google"
    assert list(social_app.sites.values_list("id", flat=True)) == [site.id]


def test_ensure_google_oauth_reuses_matching_credentials_for_new_site():
    call_command("ensure_default_sites")
    other_site = Site.objects.create(
        domain="api.mindfulmakers.xyz",
        name="Wellness Navigator",
    )
    existing_social_app = SocialApp.objects.create(
        provider="google",
        name="Shared Google",
        client_id="client-id",
        secret="client-secret",
        key="",
        provider_id="",
        settings={},
    )
    existing_social_app.sites.add(1)
    credentials_json = """
    {
      "web": {
        "client_id": "client-id",
        "client_secret": "client-secret"
      }
    }
    """

    call_command(
        "ensure_google_oauth",
        credentials_json=credentials_json,
        name="Shared Google",
        site_domains=["api.mindfulmakers.xyz"],
    )

    assert SocialApp.objects.filter(provider="google").count() == 1
    social_app = SocialApp.objects.get(provider="google")
    assert set(social_app.sites.values_list("id", flat=True)) == {1, other_site.id}


def test_ensure_google_oauth_requires_requested_site_domain_to_exist():
    credentials_json = """
    {
      "web": {
        "client_id": "client-id",
        "client_secret": "client-secret"
      }
    }
    """

    with pytest.raises(CommandError, match="Could not find site"):
        call_command(
            "ensure_google_oauth",
            credentials_json=credentials_json,
            site_domains=["missing.example.com"],
        )
