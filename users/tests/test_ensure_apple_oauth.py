from io import StringIO

import pytest
from allauth.socialaccount.models import SocialApp
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db

CREDENTIALS_JSON = """
{
  "client_id": "cloud.openbase.signin,cloud.openbase.Openbase",
  "key_id": "KEYID12345",
  "team_id": "TEAMID1234",
  "private_key": "-----BEGIN PRIVATE KEY-----\\nfake\\n-----END PRIVATE KEY-----"
}
"""


def test_ensure_apple_oauth_skips_without_credentials_in_non_interactive_mode(
    monkeypatch,
):
    call_command("ensure_default_sites")
    monkeypatch.setattr(
        "builtins.input", lambda: pytest.fail("input() should not be called")
    )
    stdout = StringIO()

    call_command("ensure_apple_oauth", non_interactive=True, stdout=stdout)

    assert "skipping in non-interactive mode" in stdout.getvalue().lower()
    assert not SocialApp.objects.filter(provider="apple").exists()


def test_ensure_apple_oauth_uses_credentials_json_for_default_site():
    call_command("ensure_default_sites")

    call_command(
        "ensure_apple_oauth", credentials_json=CREDENTIALS_JSON, name="Dev App"
    )

    social_app = SocialApp.objects.get(provider="apple")

    assert social_app.name == "Dev App"
    assert social_app.client_id == "cloud.openbase.signin,cloud.openbase.Openbase"
    assert social_app.secret == "KEYID12345"
    assert social_app.key == "TEAMID1234"
    assert social_app.settings == {
        "certificate_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----"
    }
    assert list(social_app.sites.values_list("id", flat=True)) == [1]


def test_ensure_apple_oauth_updates_key_and_settings_for_existing_app():
    call_command("ensure_default_sites")
    existing = SocialApp.objects.create(
        provider="apple",
        name="Dev App",
        client_id="cloud.openbase.signin,cloud.openbase.Openbase",
        secret="KEYID12345",
        key="OLDTEAM",
        provider_id="",
        settings={},
    )

    call_command(
        "ensure_apple_oauth",
        credentials_json=CREDENTIALS_JSON,
        name="Dev App",
    )

    existing.refresh_from_db()
    assert SocialApp.objects.filter(provider="apple").count() == 1
    assert existing.key == "TEAMID1234"
    assert existing.settings["certificate_key"].startswith("-----BEGIN PRIVATE KEY")


def test_ensure_apple_oauth_requires_all_fields():
    call_command("ensure_default_sites")

    with pytest.raises(CommandError, match="key_id, team_id, private_key"):
        call_command(
            "ensure_apple_oauth",
            credentials_json='{"client_id": "cloud.openbase.signin"}',
        )
