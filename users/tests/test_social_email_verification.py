import pytest
from allauth.account.models import EmailAddress
from allauth.account.signals import user_signed_up
from allauth.socialaccount.models import SocialAccount, SocialLogin
from allauth.socialaccount.signals import (
    social_account_added,
    social_account_updated,
)
from django.contrib.auth import get_user_model
from django.core.management import call_command

from config.email_verification import user_has_verified_email

pytestmark = pytest.mark.django_db


def _social_login(user, *, provider="google", uid="uid-123"):
    return SocialLogin(
        user=user,
        account=SocialAccount(provider=provider, uid=uid, user=user),
    )


def test_social_account_added_verifies_unverified_email():
    """Auto-connect gap: a social login attached to a pre-existing account with
    an unverified email must end up verified, not trapped behind the gate."""
    User = get_user_model()
    user = User.objects.create_user(email="yueyue@gmail.com", password="pw")
    EmailAddress.objects.create(
        user=user, email="yueyue@gmail.com", verified=False, primary=True
    )
    assert user_has_verified_email(user) is False

    social_account_added.send(
        sender=SocialLogin, request=None, sociallogin=_social_login(user)
    )

    assert user_has_verified_email(user) is True
    assert EmailAddress.objects.get(user=user, email="yueyue@gmail.com").verified


def test_user_signed_up_with_sociallogin_verifies_email():
    """Fresh social signup (no EmailAddress yet) gets a verified primary one."""
    User = get_user_model()
    user = User.objects.create_user(email="newgoogle@gmail.com", password="pw")

    user_signed_up.send(
        sender=User,
        request=None,
        user=user,
        sociallogin=_social_login(user, uid="uid-signup"),
    )

    email_address = EmailAddress.objects.get(user=user, email="newgoogle@gmail.com")
    assert email_address.verified is True
    assert email_address.primary is True


def test_social_account_updated_heals_existing_account():
    """Repeat logins refresh provider data and heal accounts created before the
    safeguard existed."""
    User = get_user_model()
    user = User.objects.create_user(email="returning@gmail.com", password="pw")
    EmailAddress.objects.create(
        user=user, email="returning@gmail.com", verified=False, primary=True
    )

    social_account_updated.send(
        sender=SocialLogin, request=None, sociallogin=_social_login(user)
    )

    assert user_has_verified_email(user) is True


def test_plain_email_signup_is_not_auto_verified():
    """Guardrail: a non-social user_signed_up (no sociallogin) must NOT be
    silently verified, preserving mandatory email verification for password
    signups."""
    User = get_user_model()
    user = User.objects.create_user(email="passworduser@example.com", password="pw")
    EmailAddress.objects.create(
        user=user, email="passworduser@example.com", verified=False, primary=True
    )

    user_signed_up.send(sender=User, request=None, user=user)

    assert user_has_verified_email(user) is False


def test_verify_social_account_emails_command_heals_trapped_user():
    User = get_user_model()
    user = User.objects.create_user(email="trapped@gmail.com", password="pw")
    SocialAccount.objects.create(user=user, provider="google", uid="cmd-uid")
    EmailAddress.objects.create(
        user=user, email="trapped@gmail.com", verified=False, primary=True
    )

    call_command("verify_social_account_emails", email="trapped@gmail.com")

    assert user_has_verified_email(user) is True
