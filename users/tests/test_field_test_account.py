import json
from io import StringIO

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.utils import timezone

from payment.billing import user_has_active_subscription
from payment.models import Subscription
from users.management.commands.field_test_account import (
    Command,
    is_allowed_field_test_email,
)

pytestmark = pytest.mark.django_db

ALLOWED = "gabe+ft1@gmail.com"
ALLOWLIST = "gabe+ft1@gmail.com, gabe+ft2@gmail.com"


@pytest.fixture
def allowlist(monkeypatch):
    monkeypatch.setenv("FIELD_TEST_ALLOWED_EMAILS", ALLOWLIST)


def run(**kwargs) -> dict:
    out = StringIO()
    call_command("field_test_account", stdout=out, **kwargs)
    return json.loads(out.getvalue().strip())


def make_user(email: str):
    return get_user_model().objects.create_user(email=email, password="pw-real-signup")


# --- Allowlist enforcement -----------------------------------------------------

# Realistic near-misses relative to the allowlisted addresses.
NEAR_MISSES = [
    "gabe+ft1@gmail.com.evil.com",  # suffix trick
    "gabe@gmail.com",  # no plus tag
    "gabe+ft3@gmail.com",  # unlisted plus tag
    "gabe+ft1@googlemail.com",  # different domain
    "evil@gmail.com",
    "",
]


def test_allowlist_accepts_listed_including_case_and_whitespace(allowlist):
    assert is_allowed_field_test_email(ALLOWED) is True
    assert is_allowed_field_test_email("GABE+FT1@GMAIL.COM") is True
    assert is_allowed_field_test_email("  gabe+ft2@gmail.com  ") is True


@pytest.mark.parametrize("email", NEAR_MISSES)
def test_allowlist_rejects_near_misses(allowlist, email):
    assert is_allowed_field_test_email(email) is False


def test_empty_allowlist_refuses_everything(monkeypatch):
    monkeypatch.delenv("FIELD_TEST_ALLOWED_EMAILS", raising=False)
    assert is_allowed_field_test_email(ALLOWED) is False
    make_user(ALLOWED)
    with pytest.raises(CommandError):
        run(destroy=ALLOWED)
    with pytest.raises(CommandError):
        run(mock_payment=ALLOWED)
    # The user is untouched.
    assert get_user_model().objects.filter(email=ALLOWED).exists()


def test_blank_allowlist_value_refuses_everything(monkeypatch):
    monkeypatch.setenv("FIELD_TEST_ALLOWED_EMAILS", "   ,  ")
    assert is_allowed_field_test_email(ALLOWED) is False
    with pytest.raises(CommandError):
        run(destroy=ALLOWED)


# --- Destroy -------------------------------------------------------------------


def test_destroy_removes_user_and_owned_data(allowlist):
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

    assert result["action"] == "destroy"
    assert result["destroyed"] is True
    assert result["user_id"] == user.id
    assert not get_user_model().objects.filter(email=ALLOWED).exists()
    # Cascade cleaned owned data.
    assert not Subscription.objects.filter(account_id=account_id).exists()
    assert not EmailAddress.objects.filter(email=ALLOWED).exists()


def test_destroy_missing_user_is_idempotent_noop(allowlist):
    result = run(destroy=ALLOWED)
    assert result["destroyed"] is False
    assert result["reason"] == "not_found"


def test_destroy_refuses_non_allowlisted_email(allowlist):
    victim = "customer@openbase.cloud"
    make_user(victim)
    with pytest.raises(CommandError):
        run(destroy=victim)
    assert get_user_model().objects.filter(email=victim).exists()


# --- Mock payment --------------------------------------------------------------


def test_mock_payment_grants_entitlement(allowlist):
    user = make_user(ALLOWED)
    assert user_has_active_subscription(user) is False

    result = run(mock_payment=ALLOWED)

    assert result["action"] == "mock-payment"
    assert result["email"] == ALLOWED
    assert result["user_id"] == user.id
    assert result["entitled"] is True
    assert result["subscription_created"] is True

    assert user_has_active_subscription(user) is True
    subscription = Subscription.objects.get(account__user_owner=user)
    assert subscription.is_active() is True
    assert subscription.is_stripe_billed is False


def test_mock_payment_is_idempotent(allowlist):
    make_user(ALLOWED)
    first = run(mock_payment=ALLOWED)
    second = run(mock_payment=ALLOWED)
    assert first["subscription_created"] is True
    assert second["subscription_created"] is False
    user = get_user_model().objects.get(email=ALLOWED)
    assert Subscription.objects.filter(account__user_owner=user).count() == 1


def test_mock_payment_requires_existing_user(allowlist):
    # No signup happened yet -> error (never creates users).
    with pytest.raises(CommandError):
        run(mock_payment=ALLOWED)
    assert not get_user_model().objects.filter(email=ALLOWED).exists()


def test_mock_payment_refuses_non_allowlisted_email(allowlist):
    victim = "customer@openbase.cloud"
    make_user(victim)
    with pytest.raises(CommandError):
        run(mock_payment=victim)
    assert not Subscription.objects.filter(account__user_owner__email=victim).exists()


# --- Hard guardrail on the delete path ----------------------------------------


@pytest.mark.parametrize(
    "email",
    [
        "customer@openbase.cloud",
        "gabe+ft1@gmail.com.evil.com",
        "gabe@gmail.com",
    ],
)
def test_destroy_path_refuses_non_allowlisted_user(allowlist, email):
    """A user whose stored email is not allowlisted is never deleted, even when
    the delete path is reached directly."""
    make_user(email)
    command = Command()
    with pytest.raises(CommandError):
        command._destroy(email)  # noqa: SLF001 (white-box test of the delete guard)
    assert get_user_model().objects.filter(email=email).exists()
