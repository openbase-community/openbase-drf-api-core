"""Safely provision and manage reserved production field-test accounts.

Core product field tests use throwaway identities that cannot receive email.
They are provisioned directly as verified users so no message is sent to a
person. Personal inboxes, plus-addresses, and ordinary deliverable domains are
rejected even when an operator accidentally adds them to the allowlist.

Every operation requires exact membership in ``FIELD_TEST_ALLOWED_EMAILS``.
Provisioning reads the password only from ``FIELD_TEST_ACCOUNT_PASSWORD``;
there is deliberately no password command-line option because one-off command
arguments and task logs are not secret storage.
"""

import json
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from payment.models import Account, Subscription
from users.field_test_accounts import (
    assert_allowed_field_test_email,
    field_test_password,
    normalize_email,
)

FIELD_TEST_SUBSCRIPTION_TYPE = "field-test"
FIELD_TEST_SUBSCRIPTION_DAYS = 3650


class Command(BaseCommand):
    help = (
        "Provision, destroy, or grant local paid entitlement to a reserved "
        "field-test account. All actions require exact FIELD_TEST_ALLOWED_EMAILS "
        "membership and a reserved non-delivery address. --provision reads "
        "FIELD_TEST_ACCOUNT_PASSWORD and creates a verified nonstaff user without "
        "sending email. Passwords are never accepted on the command line."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--provision",
            metavar="EMAIL",
            help="Create or refresh a verified, nonstaff throwaway account.",
        )
        group.add_argument(
            "--destroy",
            metavar="EMAIL",
            help="Delete the throwaway user through the canonical cascade.",
        )
        group.add_argument(
            "--mock-payment",
            metavar="EMAIL",
            help="Grant local paid entitlement without a payment-provider call.",
        )

    def handle(self, *args, **options):
        if options["provision"] is not None:
            action, email = "provision", options["provision"]
        elif options["destroy"] is not None:
            action, email = "destroy", options["destroy"]
        else:
            action, email = "mock-payment", options["mock_payment"]

        email = normalize_email(email)
        assert_allowed_field_test_email(email)

        if action == "provision":
            # Read and validate the secret before opening the transaction, but
            # never include it in output or error text.
            password = field_test_password()
            result = self._provision(email, password)
        elif action == "destroy":
            result = self._destroy(email)
        else:
            result = self._mock_payment(email)

        self.stdout.write(json.dumps(result))

    @transaction.atomic
    def _provision(self, email: str, password: str) -> dict:
        User = get_user_model()
        users = list(User.objects.select_for_update().filter(email__iexact=email)[:2])
        if len(users) > 1:
            msg = "Refusing to provision: multiple case-insensitive user matches exist."
            raise CommandError(msg)
        user = users[0] if users else None

        email_rows = EmailAddress.objects.select_for_update().filter(
            email__iexact=email
        )
        if email_rows.exclude(user=user).exists():
            msg = "Refusing to provision: the email identity belongs to another user."
            raise CommandError(msg)
        if user is not None and (user.is_staff or user.is_superuser):
            msg = "Refusing to provision over a staff or superuser account. No changes were made."
            raise CommandError(msg)

        password_user = user or User(email=email)
        try:
            validate_password(password, user=password_user)
        except ValidationError as exc:
            msg = "The field-test password failed password validation."
            raise CommandError(msg) from exc

        created = user is None
        if user is None:
            # Avoid User.save(), whose normal product path may provision a
            # Stripe customer. Bulk creation plus the two local post-save
            # artifacts keeps this operator path deterministic and offline.
            user = User(
                email=email,
                first_name="Openbase",
                last_name="Field Test",
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
            user.set_password(password)
            User.objects.bulk_create([user])
        else:
            user.set_password(password)
            User.objects.filter(pk=user.pk).update(
                email=email,
                password=user.password,
                first_name="Openbase",
                last_name="Field Test",
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
            user.refresh_from_db()

        # These are the only local artifacts normally created by User.save().
        # Creating them explicitly avoids email and payment-provider side effects.
        Token.objects.get_or_create(user=user)
        Account.objects.get_or_create(user_owner=user)
        user.groups.clear()
        user.user_permissions.clear()

        EmailAddress.objects.filter(user=user, primary=True).exclude(
            email__iexact=email
        ).update(primary=False)
        email_address = email_rows.filter(user=user).first()
        if email_address is None:
            email_address = EmailAddress.objects.create(
                user=user,
                email=email,
                verified=True,
                primary=True,
            )
        else:
            email_address.email = email
            email_address.verified = True
            email_address.primary = True
            email_address.save(update_fields=["email", "verified", "primary"])

        return {
            "action": "provision",
            "email": email,
            "user_id": user.id,
            "created": created,
            "verified": email_address.verified,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
        }

    def _destroy(self, email: str) -> dict:
        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return {
                "action": "destroy",
                "email": email,
                "destroyed": False,
                "user_id": None,
                "reason": "not_found",
            }

        assert_allowed_field_test_email(user.email)
        if user.is_staff or user.is_superuser:
            msg = "Refusing to destroy a staff or superuser account. No changes were made."
            raise CommandError(msg)
        user_id = user.id
        user.delete()
        return {
            "action": "destroy",
            "email": email,
            "destroyed": True,
            "user_id": user_id,
        }

    def _mock_payment(self, email: str) -> dict:
        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            msg = f"No user with email {email}: provision the field-test account first."
            raise CommandError(msg)

        assert_allowed_field_test_email(user.email)
        if user.is_staff or user.is_superuser:
            msg = "Refusing to grant entitlement to a staff or superuser account."
            raise CommandError(msg)
        with transaction.atomic():
            # Do not use User.get_account(); when Stripe is configured that
            # helper may make a network call. This path must stay purely local.
            account, _created = Account.objects.get_or_create(user_owner=user)
            _subscription, created = Subscription.objects.update_or_create(
                account=account,
                defaults={
                    "subscription_type": FIELD_TEST_SUBSCRIPTION_TYPE,
                    "expiration_date": (
                        timezone.now() + timedelta(days=FIELD_TEST_SUBSCRIPTION_DAYS)
                    ),
                    "platform_data": {"provider": "field-test", "manual_grant": True},
                },
            )

        return {
            "action": "mock-payment",
            "email": user.email,
            "user_id": user.id,
            "entitled": True,
            "subscription_created": created,
        }
