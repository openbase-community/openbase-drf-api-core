import json
from io import StringIO

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.utils import timezone

from payment.billing import user_has_active_subscription
from payment.models import Account, Subscription
from users.field_test_accounts import is_reserved_field_test_email
from users.management.commands.field_test_account import Command

pytestmark = pytest.mark.django_db

ALLOWED = "delivered+openbase-field-20260831-a7f3@resend.dev"
SECOND_ALLOWED = "delivered+openbase-field-run-2@resend.dev"


def run(**kwargs) -> dict:
    out = StringIO()
    call_command("field_test_account", stdout=out, **kwargs)
    return json.loads(out.getvalue().strip())


def make_user(
    email: str,
    password: str = "Existing-Quasar-Password-731!",  # noqa: S107
):
    return get_user_model().objects.create_user(email=email, password=password)


def test_reserved_namespace_accepts_fresh_run_identities():
    assert is_reserved_field_test_email(ALLOWED) is True
    assert is_reserved_field_test_email(f"  {ALLOWED.upper()}  ") is True
    assert is_reserved_field_test_email(SECOND_ALLOWED) is True
    assert is_reserved_field_test_email("delivered+openbase-field-run-3@resend.dev")
    assert is_reserved_field_test_email("delivered+someone-else@resend.dev") is False


@pytest.mark.parametrize(
    "email",
    [
        "gabe+field-test@gmail.com",
        "delivered+openbase-field-run@gmail.com",
        "delivered+openbase-field-run@yahoo.com",
        "delivered+openbase-field-run@outlook.com",
        "delivered+openbase-field-run@icloud.com",
        "delivered+openbase-field-run@proton.me",
        "delivered+openbase-field-run@company.com",
        "delivered+field-test-run@resend.dev",
        "bounced+openbase-field-run@resend.dev",
        "delivered@resend.dev",
        "other@example.com",
        "openbase-field-run@example.com",
        "delivered+openbase-field-run@resend.dev.evil.com",
        "",
    ],
)
def test_personal_plus_and_nonreserved_addresses_fail(email):
    assert is_reserved_field_test_email(email) is False
    with pytest.raises(CommandError):
        run(destroy=email)


def test_command_has_no_user_creation_option():
    parser = Command().create_parser("manage.py", "field_test_account")
    options = {
        option
        for action in parser._actions  # noqa: SLF001
        for option in action.option_strings
    }
    assert "--provision" not in options
    assert {"--destroy", "--mock-payment"}.issubset(options)
    assert not get_user_model().objects.filter(email=ALLOWED).exists()


def test_destroy_removes_user_and_owned_data():
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


def test_destroy_missing_user_is_idempotent_noop():
    result = run(destroy=ALLOWED)
    assert result["destroyed"] is False
    assert result["reason"] == "not_found"


def test_destroy_refuses_nonreserved_user():
    victim = "victim@example.com"
    make_user(victim)
    with pytest.raises(CommandError):
        run(destroy=victim)
    assert get_user_model().objects.filter(email=victim).exists()


def test_mock_payment_grants_local_entitlement_without_stripe(mocker):
    user = make_user(ALLOWED)
    EmailAddress.objects.create(user=user, email=ALLOWED, verified=True, primary=True)
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


def test_mock_payment_is_idempotent():
    user = make_user(ALLOWED)
    EmailAddress.objects.create(user=user, email=ALLOWED, verified=True, primary=True)
    first = run(mock_payment=ALLOWED)
    second = run(mock_payment=ALLOWED)
    assert first["subscription_created"] is True
    assert second["subscription_created"] is False
    assert Subscription.objects.filter(account__user_owner__email=ALLOWED).count() == 1


def test_mock_payment_requires_existing_user():
    with pytest.raises(CommandError):
        run(mock_payment=ALLOWED)


def test_mock_payment_requires_real_email_verification():
    user = make_user(ALLOWED)
    EmailAddress.objects.create(user=user, email=ALLOWED, verified=False, primary=True)

    with pytest.raises(CommandError, match="Verify the field-test email"):
        run(mock_payment=ALLOWED)
    assert not Subscription.objects.filter(account__user_owner=user).exists()


def test_direct_destroy_guard_rechecks_stored_identity():
    email = "victim@example.com"
    make_user(email)
    with pytest.raises(CommandError):
        Command()._destroy(email)  # noqa: SLF001
    assert get_user_model().objects.filter(email=email).exists()
