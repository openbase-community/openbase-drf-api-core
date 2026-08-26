import json
from io import StringIO

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from payment.billing import user_has_active_subscription
from payment.models import Subscription
from users.management.commands.field_test_user import (
    Command,
    assert_field_test_email,
    is_field_test_email,
)

pytestmark = pytest.mark.django_db


def run(**kwargs) -> dict:
    """Invoke the command and return the parsed JSON it wrote to stdout."""
    out = StringIO()
    call_command("field_test_user", stdout=out, **kwargs)
    return json.loads(out.getvalue().strip())


# --- Pattern guard -------------------------------------------------------------

VALID_EMAILS = [
    "field-test-abc@example.com",
    "field-test-run-2026-08-26@example.com",
    "field-test-0@example.com",
    "FIELD-TEST-ABC@EXAMPLE.COM",  # case-insensitive
]

# Realistic near-misses that must NEVER be treated as field-test identities.
INVALID_EMAILS = [
    "gabe@openbase.cloud",
    "field-test-x@example.com.evil.com",  # suffix trick
    "field-test-x@example.org",  # wrong reserved domain
    "field-test-x@example.net",
    "field-test-@example.com",  # empty slug
    "field-test-x@evil-example.com",
    "prefix-field-test-x@example.com",
    "test@example.com",  # filtered, but not a field-test identity
    "field-test-x@example.com.evil.com\n",  # suffix trick survives whitespace strip
    "",
]


@pytest.mark.parametrize("email", VALID_EMAILS)
def test_pattern_accepts_valid(email):
    assert is_field_test_email(email) is True
    assert_field_test_email(email)  # does not raise


@pytest.mark.parametrize("email", INVALID_EMAILS)
def test_pattern_rejects_invalid_and_near_misses(email):
    assert is_field_test_email(email) is False
    with pytest.raises(CommandError):
        assert_field_test_email(email)


# --- Create --------------------------------------------------------------------


def test_create_makes_verified_entitled_user():
    result = run(create="alpha")

    assert result["action"] == "create"
    assert result["email"] == "field-test-alpha@example.com"
    assert result["verified"] is True
    assert result["entitled"] is True
    assert isinstance(result["password"], str)
    assert len(result["password"]) >= 20

    User = get_user_model()
    user = User.objects.get(email="field-test-alpha@example.com")
    assert result["user_id"] == user.id
    # Password from stdout actually authenticates.
    assert user.check_password(result["password"])
    # Email marked verified + primary via allauth.
    email_address = EmailAddress.objects.get(user=user, email=user.email)
    assert email_address.verified is True
    assert email_address.primary is True
    # Faked-but-real paid entitlement, no Stripe involved.
    assert user_has_active_subscription(user) is True
    subscription = Subscription.objects.get(account__user_owner=user)
    assert subscription.is_active() is True
    assert subscription.is_stripe_billed is False


def test_create_rejects_existing_user():
    run(create="beta")
    with pytest.raises(CommandError):
        run(create="beta")


def test_create_rejects_invalid_slug():
    for bad in ["Alpha", "has space", "under_score", "sym!bol", ""]:
        with pytest.raises(CommandError):
            run(create=bad)


# --- Destroy -------------------------------------------------------------------


def test_destroy_removes_user_and_owned_data():
    created = run(create="gamma")
    User = get_user_model()
    user = User.objects.get(email="field-test-gamma@example.com")
    account_id = user.get_account().id
    assert Subscription.objects.filter(account_id=account_id).exists()

    result = run(destroy="gamma")

    assert result["destroyed"] is True
    assert result["user_id"] == created["user_id"]
    assert not User.objects.filter(email="field-test-gamma@example.com").exists()
    # Cascade cleaned owned data (Account -> Subscription, allauth email).
    assert not Subscription.objects.filter(account_id=account_id).exists()
    assert not EmailAddress.objects.filter(
        email="field-test-gamma@example.com"
    ).exists()


def test_destroy_missing_user_is_idempotent_noop():
    result = run(destroy="never-created")
    assert result["destroyed"] is False
    assert result["reason"] == "not_found"


# --- Recycle -------------------------------------------------------------------


def test_recycle_creates_when_absent():
    result = run(recycle="delta")
    assert result["action"] == "recycle"
    assert result["destroyed_existing"] is False
    assert result["entitled"] is True

    User = get_user_model()
    assert User.objects.filter(email="field-test-delta@example.com").exists()


def test_double_recycle_is_idempotent_and_rotates_user():
    first = run(recycle="epsilon")
    second = run(recycle="epsilon")

    assert first["destroyed_existing"] is False
    assert second["destroyed_existing"] is True
    # A brand-new user row each time (old one destroyed then recreated).
    assert second["user_id"] != first["user_id"]
    assert second["password"] != first["password"]

    User = get_user_model()
    users = User.objects.filter(email="field-test-epsilon@example.com")
    assert users.count() == 1
    user = users.get()
    assert user.check_password(second["password"])
    assert user_has_active_subscription(user) is True


# --- Hard guardrail: non-matching users can never be destroyed -----------------


@pytest.mark.parametrize(
    "email",
    [
        "gabe@openbase.cloud",
        "field-test-x@example.com.evil.com",
        "test@example.com",
        "field-test-x@example.org",
    ],
)
def test_destroy_path_refuses_non_field_test_user(email):
    """A user whose stored email is not a field-test identity is never deleted,
    even when the delete path is reached directly with that email."""
    User = get_user_model()
    user = User.objects.create_user(email=email, password="pw-should-survive")

    command = Command()
    with pytest.raises(CommandError):
        command._destroy(email)  # noqa: SLF001 (white-box test of the delete guard)

    assert User.objects.filter(email=email).exists()
    user.refresh_from_db()
    assert user.check_password("pw-should-survive")
