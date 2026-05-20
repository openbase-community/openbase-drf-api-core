from io import StringIO

import pytest
from allauth.socialaccount.models import SocialApp
from django.core.management import call_command


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
