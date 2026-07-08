import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import override_settings

pytestmark = pytest.mark.django_db


@override_settings(DEBUG=True)
def test_ensure_dev_superuser_creates_default_superuser_in_non_interactive_mode():
    User = get_user_model()

    call_command("ensure_dev_superuser", non_interactive=True)

    superuser = User.objects.get(is_superuser=True)
    email_address = EmailAddress.objects.get(user=superuser)

    assert superuser.email == "test@example.com"
    assert superuser.is_staff is True
    assert superuser.first_name == "Test"
    assert superuser.last_name == "User"
    assert superuser.check_password("test")
    assert email_address.email == "test@example.com"
    assert email_address.verified is True
    assert email_address.primary is True


def test_ensure_dev_superuser_promotes_existing_user_in_non_interactive_mode():
    User = get_user_model()
    user = User.objects.create_user(email="dev@example.com", password="old-password")

    call_command(
        "ensure_dev_superuser",
        non_interactive=True,
        email="dev@example.com",
        password="new-password",
    )

    user.refresh_from_db()
    email_address = EmailAddress.objects.get(user=user)

    assert user.is_superuser is True
    assert user.is_staff is True
    assert user.first_name == "Test"
    assert user.last_name == "User"
    assert user.check_password("new-password")
    assert email_address.verified is True
    assert email_address.primary is True


@override_settings(DEBUG=False)
def test_ensure_dev_superuser_refuses_default_password_when_debug_off():
    User = get_user_model()

    with pytest.raises(CommandError, match="default"):
        call_command("ensure_dev_superuser", non_interactive=True)

    assert not User.objects.filter(is_superuser=True).exists()


@override_settings(DEBUG=False)
def test_ensure_dev_superuser_allows_explicit_password_when_debug_off():
    User = get_user_model()

    call_command(
        "ensure_dev_superuser",
        non_interactive=True,
        email="ops@example.com",
        password="explicit-strong-password",  # noqa: S106
    )

    superuser = User.objects.get(is_superuser=True)
    assert superuser.email == "ops@example.com"
    assert superuser.check_password("explicit-strong-password")
