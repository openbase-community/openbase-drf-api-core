"""Lifecycle helpers for the designated **field-test account(s)**.

Field tests are agent-driven, end-to-end tests that install the product
clean-room in a VM and run through the *real* signup/usage flows against
production Openbase Cloud. To exercise real signup and real email verification,
a field test uses a real, designated account whose verification mail lands in a
Gabe-controlled inbox the testing agent can read (plus-addressing --
``user+slug@gmail.com`` -- yields unlimited distinct real signup addresses in
one inbox).

This command does the two things the product's own flows cannot safely do
around such a run:

- ``--destroy EMAIL`` (pre-test): delete the designated user so the test can
  sign up from scratch, using the canonical account-deletion cascade
  (``user.delete()``; see ``users.views.DeleteUserView``).
- ``--mock-payment EMAIL`` (mid-test, AFTER the real signup): grant paid
  entitlement with a purely local ``payment.Subscription`` row -- no Stripe
  checkout, subscription, or charge.

It never creates users and never mocks email verification: signup and
verification happen for real through the product.

Guardrail
---------
The command refuses to touch any email that is not in an explicit allowlist read
from the environment variable ``FIELD_TEST_ALLOWED_EMAILS`` (comma-separated).
If that variable is empty or unset, the allowlist is empty and the command
refuses everything. This is the primary safety contract: a real customer can
never be destroyed or mutated unless an operator has deliberately listed their
exact email.
"""

import json
import os
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from payment.models import Subscription

# Env var holding the comma-separated allowlist of emails this command may touch.
FIELD_TEST_ALLOWLIST_ENV = "FIELD_TEST_ALLOWED_EMAILS"

# Faked paid entitlement (see ``payment.billing.user_has_active_subscription``:
# entitlement is gated purely on an active Subscription with a future
# ``expiration_date``). Empty ``platform_data`` makes ``subscription_monthly_cents``
# fall back to the default subscription tier, i.e. a normal paid cap, not
# unlimited.
FIELD_TEST_SUBSCRIPTION_TYPE = "field-test"
FIELD_TEST_SUBSCRIPTION_DAYS = 3650


def normalize_email(email: str) -> str:
    return (email or "").strip()


def field_test_allowed_emails() -> frozenset:
    """The case-folded allowlist parsed from ``FIELD_TEST_ALLOWED_EMAILS``.

    Empty or unset -> empty set -> the command refuses every email.
    """
    raw = os.environ.get(FIELD_TEST_ALLOWLIST_ENV, "")
    return frozenset(
        entry.strip().casefold() for entry in raw.split(",") if entry.strip()
    )


def is_allowed_field_test_email(email: str) -> bool:
    normalized = normalize_email(email).casefold()
    return bool(normalized) and normalized in field_test_allowed_emails()


def assert_allowed_field_test_email(email: str) -> None:
    """Raise ``CommandError`` unless ``email`` is in the env allowlist.

    Runs before any read/write so a non-allowlisted user can never be touched.
    """
    if is_allowed_field_test_email(email):
        return
    allowed = field_test_allowed_emails()
    if not allowed:
        msg = (
            f"Refusing to operate on {email!r}: the field-test allowlist is "
            f"empty. Set {FIELD_TEST_ALLOWLIST_ENV} (comma-separated) to the "
            f"exact designated field-test email(s). No changes were made."
        )
        raise CommandError(msg)
    msg = (
        f"Refusing to operate on {email!r}: it is not in the "
        f"{FIELD_TEST_ALLOWLIST_ENV} allowlist. No changes were made."
    )
    raise CommandError(msg)


class Command(BaseCommand):
    help = (
        "Lifecycle helpers for the designated field-test account. "
        "--destroy EMAIL deletes the real designated user (canonical "
        "account-deletion cascade) so a field test can sign up for real; "
        "--mock-payment EMAIL grants paid entitlement after the real signup via "
        "a LOCAL payment.Subscription row (no Stripe charge). It never creates "
        "users and never mocks email verification -- those happen for real "
        "through the product. Refuses any email not listed in the "
        f"{FIELD_TEST_ALLOWLIST_ENV} environment allowlist (empty/unset refuses "
        "everything). Emits JSON to stdout for the field-test harness."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--destroy",
            metavar="EMAIL",
            help=(
                "Pre-test: delete the designated user EMAIL via the canonical "
                "account-deletion cascade. Idempotent: a no-op if absent."
            ),
        )
        group.add_argument(
            "--mock-payment",
            metavar="EMAIL",
            help=(
                "Mid-test (after real signup): grant faked paid entitlement to "
                "EMAIL with a local payment.Subscription row. No provider calls."
            ),
        )

    def handle(self, *args, **options):
        if options["destroy"] is not None:
            action, email = "destroy", options["destroy"]
        else:
            action, email = "mock-payment", options["mock_payment"]

        email = normalize_email(email)
        # Guardrail before any read/write.
        assert_allowed_field_test_email(email)

        if action == "destroy":
            result = self._destroy(email)
        else:
            result = self._mock_payment(email)

        self.stdout.write(json.dumps(result))

    # -- operations -------------------------------------------------------------

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

        # Belt-and-suspenders: re-check the fetched user's stored email.
        assert_allowed_field_test_email(user.email)
        user_id = user.id
        # Canonical account-deletion path: a plain cascade delete, exactly like
        # users.views.DeleteUserView ("delete-account"). Django cascades clean
        # the owned Account, Subscription, auth Token, APNS token, and allauth
        # EmailAddress rows.
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
            msg = (
                f"No user with email {email}: --mock-payment runs AFTER the real "
                f"signup. Sign up through the product first."
            )
            raise CommandError(msg)

        # Belt-and-suspenders: re-check the fetched user's stored email.
        assert_allowed_field_test_email(user.email)
        with transaction.atomic():
            account = user.get_account()
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
