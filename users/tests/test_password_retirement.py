import importlib
import json
from io import StringIO

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.core.mail.backends.locmem import EmailBackend as LocmemBackend
from django.core.management import call_command

from sites.models import SiteAttributes
from users.password_retirement import (
    build_notice,
    password_retirement_recipients,
    send_password_retirement_notices,
)

pytestmark = pytest.mark.django_db

migration = importlib.import_module("users.migrations.0003_password_retirement_notice")


@pytest.fixture(autouse=True)
def _no_stripe(settings):
    settings.STRIPE_SECRET_KEY = ""


def _user(email, password="Quasar-Field-Test-734!", **fields):  # noqa: S107
    return get_user_model().objects.create_user(email, password, **fields)


def _emails(recipients):
    return [recipient.email for recipient in recipients]


def test_recipients_are_active_accounts_with_a_usable_password():
    with_password = _user("with-password@resend.dev", first_name="Ada")
    _user("social-only@resend.dev", password=None)
    _user("inactive@resend.dev", is_active=False)

    recipients = password_retirement_recipients(get_user_model())

    assert _emails(recipients) == [with_password.email]
    assert recipients[0].first_name == "Ada"
    assert recipients[0].site_id is None


def test_notice_names_the_account_and_the_sign_in_options(settings, monkeypatch):
    monkeypatch.setenv("DEFAULT_FROM_EMAIL", "team@openbase.cloud")
    settings.PASSWORD_RETIREMENT_NOTICE_BRAND = "Openbase"  # noqa: S105
    settings.PASSWORD_RETIREMENT_NOTICE_LOGIN_URL = "https://app.example/account/login"  # noqa: S105
    settings.PASSWORD_RETIREMENT_NOTICE_SUPPORT_EMAIL = "help@example"  # noqa: S105
    _user("ada@resend.dev", first_name="Ada")

    message = build_notice(password_retirement_recipients(get_user_model())[0])

    assert message.subject == "Openbase is retiring password sign-in"
    assert message.to == ["ada@resend.dev"]
    assert message.from_email == "Openbase <team@openbase.cloud>"
    assert message.reply_to == ["help@example"]
    assert "Hi Ada," in message.body
    assert "retiring password sign-in" in message.body
    assert "VPC and VPN" in message.body
    assert "ada@resend.dev" in message.body
    assert "https://app.example/account/login" in message.body
    assert "sign-in code" in message.body
    assert "Sign in with Google" in message.body
    assert "help@example" in message.body
    html, mimetype = message.alternatives[0]
    assert mimetype == "text/html"
    assert 'href="https://app.example/account/login"' in html
    assert "Hi Ada," in html


def test_notice_uses_the_site_from_address_for_site_accounts():
    site = Site.objects.create(domain="app.other.test", name="Other")
    SiteAttributes.objects.create(site=site, from_email="hello@other.test")
    _user("other@resend.dev", site=site)

    message = build_notice(password_retirement_recipients(get_user_model())[0])

    assert message.from_email == "Other <hello@other.test>"


def test_greeting_without_a_first_name():
    _user("anon@resend.dev")

    message = build_notice(password_retirement_recipients(get_user_model())[0])

    assert "Hi,\n" in message.body


def test_send_mails_each_recipient_once(mailoutbox):
    _user("one@resend.dev")
    _user("two@resend.dev")
    _user("no-password@resend.dev", password=None)

    result = send_password_retirement_notices(get_user_model())

    assert result.as_dict() == {
        "recipients": 2,
        "sent": 2,
        "filtered": 0,
        "failed": 0,
        "dry_run": False,
        "failures": [],
    }
    assert sorted(message.to[0] for message in mailoutbox) == [
        "one@resend.dev",
        "two@resend.dev",
    ]


def test_dry_run_counts_without_sending(mailoutbox):
    _user("dry@resend.dev")

    result = send_password_retirement_notices(get_user_model(), dry_run=True)

    assert result.recipients == 1
    assert result.sent == 0
    assert result.dry_run is True
    assert mailoutbox == []


class RefusingBackend(LocmemBackend):
    """Raises for one recipient and delivers to nobody for another, like a
    provider rejection and the Resend backend's non-delivery filter."""

    def send_messages(self, email_messages):
        recipient = email_messages[0].to[0]
        if recipient.startswith("bounce"):
            msg = "provider rejected the address"
            raise RuntimeError(msg)
        if recipient.endswith("@example.com"):
            return 0
        return super().send_messages(email_messages)


def test_a_failed_address_is_logged_and_the_rest_still_go_out(settings, mailoutbox):
    settings.EMAIL_BACKEND = "users.tests.test_password_retirement.RefusingBackend"
    _user("bounce@resend.dev")
    _user("filtered@example.com")
    _user("fine@resend.dev")

    result = send_password_retirement_notices(get_user_model())

    assert (result.recipients, result.sent, result.filtered, result.failed) == (
        3,
        1,
        1,
        1,
    )
    assert result.failures == [
        f"user {get_user_model().objects.get(email='bounce@resend.dev').id}: RuntimeError"
    ]
    assert [message.to[0] for message in mailoutbox] == ["fine@resend.dev"]


def test_migration_sends_on_a_deployed_passwordless_server(settings, mailoutbox):
    settings.DEBUG = False
    settings.PASSWORD_RETIREMENT_NOTICE_SKIP = False
    settings.PASSWORD_AUTH_ENABLED = False
    _user("deployed@resend.dev")

    migration.send_notices(apps, None)

    assert [message.to[0] for message in mailoutbox] == ["deployed@resend.dev"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"DEBUG": True},
        {"PASSWORD_RETIREMENT_NOTICE_SKIP": True},
        {"PASSWORD_AUTH_ENABLED": True},
    ],
)
def test_migration_stays_quiet_when_told_to(settings, mailoutbox, overrides):
    settings.DEBUG = False
    settings.PASSWORD_RETIREMENT_NOTICE_SKIP = False
    settings.PASSWORD_AUTH_ENABLED = False
    for name, value in overrides.items():
        setattr(settings, name, value)
    _user("quiet@resend.dev")

    migration.send_notices(apps, None)

    assert mailoutbox == []


def test_command_defaults_to_a_dry_run(mailoutbox):
    _user("cmd@resend.dev")
    out = StringIO()

    call_command("password_retirement_notice", stdout=out)

    assert json.loads(out.getvalue()) == {
        "recipients": 1,
        "sent": 0,
        "filtered": 0,
        "failed": 0,
        "dry_run": True,
        "failures": [],
    }
    assert mailoutbox == []


def test_command_sends_with_the_flag(mailoutbox):
    _user("cmd-send@resend.dev")
    out = StringIO()

    call_command("password_retirement_notice", "--send", stdout=out)

    assert json.loads(out.getvalue())["sent"] == 1
    assert [message.to[0] for message in mailoutbox] == ["cmd-send@resend.dev"]
