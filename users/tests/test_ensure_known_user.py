import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import call_command


pytestmark = pytest.mark.django_db


def test_ensure_known_user_creates_verified_primary_user():
    User = get_user_model()

    call_command(
        "ensure_known_user",
        email="smoke@example.com",
        password="SmokeTest123!",
        first_name="Smoke",
        last_name="Tester",
    )

    user = User.objects.get(email="smoke@example.com")
    email_address = EmailAddress.objects.get(user=user, email="smoke@example.com")

    assert user.first_name == "Smoke"
    assert user.last_name == "Tester"
    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.check_password("SmokeTest123!")
    assert email_address.verified is True
    assert email_address.primary is True


def test_ensure_known_user_updates_existing_user_and_primary_email():
    User = get_user_model()
    user = User.objects.create_user(email="smoke@example.com", password="old-password")
    EmailAddress.objects.create(
        user=user,
        email="old@example.com",
        verified=True,
        primary=True,
    )
    EmailAddress.objects.create(
        user=user,
        email="smoke@example.com",
        verified=False,
        primary=False,
    )

    call_command(
        "ensure_known_user",
        email="smoke@example.com",
        password="NewSmoke123!",
        superuser=True,
    )

    user.refresh_from_db()
    current_email = EmailAddress.objects.get(user=user, email="smoke@example.com")
    old_email = EmailAddress.objects.get(user=user, email="old@example.com")

    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.check_password("NewSmoke123!")
    assert current_email.verified is True
    assert current_email.primary is True
    assert old_email.primary is False
