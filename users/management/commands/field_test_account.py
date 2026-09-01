"""Safely manage production accounts created by the field-test signup flow.

Field tests sign up through the real product with an official Resend testing
recipient, retrieve the rendered verification message, and complete normal
allauth verification. This command deliberately cannot create or verify users.
It only performs guarded teardown and optional local paid entitlement.

Every operation requires exact membership in ``FIELD_TEST_ALLOWED_EMAILS``.
"""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from payment.models import Account, Subscription
from users.field_test_accounts import (
    assert_allowed_field_test_email,
    normalize_email,
)

FIELD_TEST_SUBSCRIPTION_TYPE = "field-test"
FIELD_TEST_SUBSCRIPTION_DAYS = 3650


class Command(BaseCommand):
    help = (
        "Destroy or grant local paid entitlement to a field-test account created "
        "through the real signup and email-verification flow. All actions require "
        "exact FIELD_TEST_ALLOWED_EMAILS membership and the official Resend "
        "field-test recipient format. This command cannot create or verify users."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
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
        if options["destroy"] is not None:
            action, email = "destroy", options["destroy"]
        else:
            action, email = "mock-payment", options["mock_payment"]

        email = normalize_email(email)
        assert_allowed_field_test_email(email)

        if action == "destroy":
            result = self._destroy(email)
        else:
            result = self._mock_payment(email)

        self.stdout.write(json.dumps(result))

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
            msg = f"No user with email {email}: complete field-test signup first."
            raise CommandError(msg)

        assert_allowed_field_test_email(user.email)
        if user.is_staff or user.is_superuser:
            msg = "Refusing to grant entitlement to a staff or superuser account."
            raise CommandError(msg)
        if not user.emailaddress_set.filter(email__iexact=email, verified=True).exists():
            msg = "Verify the field-test email through the real signup flow first."
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
