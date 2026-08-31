import json
from io import StringIO

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.utils import timezone
from rest_framework.authtoken.models import Token

from payment.billing import user_has_active_subscription
from payment.models import Account, Subscription
from users.field_test_accounts import (
    is_allowed_field_test_email,
    is_reserved_field_test_email,
)
from users.management.commands.field_test_account import Command

pytestmark = pytest.mark.django_db

ALLOWED = "openbase-field-20260831@example.com"
SECOND_ALLOWED = "openbase-field-test-run-2@accounts.openbase.test"
ALLOWLIST = f"{ALLOWED}, {SECOND_ALLOWED}"
PASSWORD = "Quasar-Copper-Harbor-731!"  # noqa: S105


@pytest.fixture
def field_test_env(monkeypatch):
    monkeypatch.setenv("FIELD_TEST_ALLOWED_EMAILS", ALLOWLIST)
    monkeypatch.setenv("FIELD_TEST_ACCOUNT_PASSWORD", PASSWORD)


def run(**kwargs) -> dict:
    out = StringIO()
    call_command("field_test_account", stdout=out, **kwargs)
    return json.loads(out.getvalue().strip())


def make_user(
    email: str,
    password: str = "Existing-Quasar-Password-731!",  # noqa: S107
):
    return get_user_model().objects.create_user(email=email, password=password)


def test_allowlist_requires_exact_reserved_identity(field_test_env):
    assert is_allowed_field_test_email(ALLOWED) is True
    assert is_allowed_field_test_email(f"  {ALLOWED.upper()}  ") is True
    assert is_allowed_field_test_email(SECOND_ALLOWED) is True
    assert is_allowed_field_test_email("openbase-field-test-run-3@example.com") is False
    assert is_allowed_field_test_email("customer@example.com") is False


@pytest.mark.parametrize(
    "email",
    [
        "gabe+field-test@gmail.com",
        "openbase-field-test+run@gmail.com",
        "openbase-field-test@gmail.com",
        "openbase-field-test@yahoo.com",
        "openbase-field-test@outlook.com",
        "openbase-field-test@icloud.com",
        "openbase-field-test@proton.me",
        "openbase-field-test@company.com",
        "other@example.com",
        "openbase-field-test+run@example.com",
        "openbase-field-test@example.com.evil.com",
        "",
    ],
)
def test_personal_plus_and_nonreserved_addresses_fail_even_if_allowlisted(
    monkeypatch, email
):
    monkeypatch.setenv("FIELD_TEST_ALLOWED_EMAILS", email)
    assert is_reserved_field_test_email(email) is False
    assert is_allowed_field_test_email(email) is False
    with pytest.raises(CommandError):
        run(destroy=email)


def test_empty_allowlist_refuses_everything(monkeypatch):
    monkeypatch.delenv("FIELD_TEST_ALLOWED_EMAILS", raising=False)
    with pytest.raises(CommandError):
        run(provision=ALLOWED)
    assert not get_user_model().objects.filter(email=ALLOWED).exists()


def test_provision_creates_verified_nonstaff_user_without_external_side_effects(
    field_test_env, mocker
):
    stripe_create = mocker.patch("stripe.Customer.create")
    resend_send = mocker.patch("resend.Emails.send")
    send_mail = mocker.patch("allauth.account.adapter.DefaultAccountAdapter.send_mail")

    result = run(provision=ALLOWED)

    user = get_user_model().objects.get(email=ALLOWED)
    assert result == {
        "action": "provision",
        "email": ALLOWED,
        "user_id": user.id,
        "created": True,
        "verified": True,
        "is_staff": False,
        "is_superuser": False,
    }
    assert user.check_password(PASSWORD)
    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False
    email_address = EmailAddress.objects.get(user=user, email=ALLOWED)
    assert email_address.verified is True
    assert email_address.primary is True
    assert Token.objects.filter(user=user).exists()
    assert Account.objects.filter(user_owner=user).exists()
    stripe_create.assert_not_called()
    resend_send.assert_not_called()
    send_mail.assert_not_called()


def test_provision_is_idempotent_and_refreshes_password(field_test_env, monkeypatch):
    first = run(provision=ALLOWED)
    new_password = "Nimbus-Saffron-Anchor-842!"  # noqa: S105
    monkeypatch.setenv("FIELD_TEST_ACCOUNT_PASSWORD", new_password)
    second = run(provision=ALLOWED)

    assert first["created"] is True
    assert second["created"] is False
    assert second["user_id"] == first["user_id"]
    user = get_user_model().objects.get(email=ALLOWED)
    assert user.check_password(new_password)
    assert get_user_model().objects.filter(email__iexact=ALLOWED).count() == 1
    assert EmailAddress.objects.filter(email__iexact=ALLOWED).count() == 1
    assert Token.objects.filter(user=user).count() == 1
    assert Account.objects.filter(user_owner=user).count() == 1


def test_provision_rejects_email_identity_collision(field_test_env):
    other_user = make_user("openbase-field-test-other@example.net")
    EmailAddress.objects.create(
        user=other_user,
        email=ALLOWED,
        verified=True,
        primary=False,
    )

    with pytest.raises(CommandError, match="belongs to another user"):
        run(provision=ALLOWED)
    assert not get_user_model().objects.filter(email=ALLOWED).exists()


@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_provision_refuses_privileged_collision(field_test_env, flag):
    user = make_user(ALLOWED)
    setattr(user, flag, True)
    user.save(update_fields=[flag])

    with pytest.raises(CommandError, match="staff or superuser"):
        run(provision=ALLOWED)
    user.refresh_from_db()
    assert getattr(user, flag) is True


def test_provision_requires_password_environment_variable(field_test_env, monkeypatch):
    monkeypatch.delenv("FIELD_TEST_ACCOUNT_PASSWORD")
    with pytest.raises(CommandError, match="never accepted as command arguments"):
        run(provision=ALLOWED)
    assert not get_user_model().objects.filter(email=ALLOWED).exists()


def test_provision_never_prints_password(field_test_env):
    out = StringIO()
    call_command("field_test_account", provision=ALLOWED, stdout=out)
    assert PASSWORD not in out.getvalue()


def test_destroy_removes_user_and_owned_data(field_test_env):
    user = make_user(ALLOWED)
    EmailAddress.objects.create(user=user, email=ALLOWED, verified=True, primary=True)
    account = user.get_account()
    Subscription.objects.create(
        account=account,
        subscription_type="field-test",
        expiration_date=timezone.now(),
    )
    account_id = account.id

    result = run(destroy=ALLOWED)

    assert result["destroyed"] is True
    assert result["user_id"] == user.id
    assert not get_user_model().objects.filter(email=ALLOWED).exists()
    assert not Subscription.objects.filter(account_id=account_id).exists()
    assert not EmailAddress.objects.filter(email=ALLOWED).exists()


def test_destroy_missing_user_is_idempotent_noop(field_test_env):
    result = run(destroy=ALLOWED)
    assert result["destroyed"] is False
    assert result["reason"] == "not_found"


def test_destroy_refuses_non_allowlisted_user(field_test_env):
    victim = "openbase-field-test-victim@example.net"
    make_user(victim)
    with pytest.raises(CommandError):
        run(destroy=victim)
    assert get_user_model().objects.filter(email=victim).exists()


def test_mock_payment_grants_local_entitlement_without_stripe(field_test_env, mocker):
    user = make_user(ALLOWED)
    Account.objects.filter(user_owner=user).delete()
    stripe_create = mocker.patch("stripe.Customer.create")

    result = run(mock_payment=ALLOWED)

    assert result["entitled"] is True
    assert result["subscription_created"] is True
    stripe_create.assert_not_called()
    assert user_has_active_subscription(user) is True
    subscription = Subscription.objects.get(account__user_owner=user)
    assert subscription.is_active() is True
    assert subscription.is_stripe_billed is False


def test_mock_payment_is_idempotent(field_test_env):
    make_user(ALLOWED)
    first = run(mock_payment=ALLOWED)
    second = run(mock_payment=ALLOWED)
    assert first["subscription_created"] is True
    assert second["subscription_created"] is False
    assert Subscription.objects.filter(account__user_owner__email=ALLOWED).count() == 1


def test_mock_payment_requires_existing_user(field_test_env):
    with pytest.raises(CommandError):
        run(mock_payment=ALLOWED)


def test_direct_destroy_guard_rechecks_stored_identity(field_test_env):
    email = "openbase-field-test-other@example.net"
    make_user(email)
    with pytest.raises(CommandError):
        Command()._destroy(email)  # noqa: SLF001
    assert get_user_model().objects.filter(email=email).exists()
