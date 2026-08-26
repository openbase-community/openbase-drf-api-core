"""Lifecycle management for **field-test users**.

Field tests are agent-driven, end-to-end tests that install the product
clean-room in a VM and run through real signup/usage flows against production
Openbase Cloud. Each run needs a fresh user, but real inboxes are scarce, so
field-test users live under reserved ``example.com`` identities.

Reserved-identity contract
--------------------------
Every field-test user has an email matching exactly::

    ^field-test-[a-z0-9-]+@example\\.com$

``example.com`` is one of the domains the Resend email backend filters (see
``config/email.py`` :func:`is_filtered_email_address`), so these users generate
ZERO real email and carry no deliverability/spam-score risk. Because they can
never *receive* mail, email verification and paid entitlement are provisioned
directly by this command instead of through the normal signup + Stripe flows.

Safety
------
The email pattern above is the primary contract and the guardrail: this command
refuses -- loudly, before any write -- to destroy or modify ANY user whose email
does not match it. Destruction reuses the canonical account-deletion path
(``user.delete()``; see ``users.views.DeleteUserView``) so owned data is
cascade-cleaned exactly like a real account deletion.

This command is EXCLUSIVELY for field-test users. Paid entitlement is faked with
a purely local ``payment.Subscription`` row; no Stripe checkout, subscription,
or charge is ever created. Never point it at a real customer.
"""

import json
import re
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from config.email_verification import ensure_user_email_verified
from payment.models import Subscription

# --- Reserved-identity contract -------------------------------------------------
# The email pattern is the PRIMARY contract and the destroy guardrail. Keep the
# domain in the reserved-and-email-filtered set (example.com/.net/.org) so these
# users can never send or receive real mail.
FIELD_TEST_DOMAIN = "example.com"
FIELD_TEST_EMAIL_PATTERN = re.compile(r"^field-test-[a-z0-9-]+@example\.com$")
# A field-test slug is the ``<slug>`` in field-test-<slug>@example.com.
FIELD_TEST_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")

# --- Faked paid entitlement -----------------------------------------------------
# Paid entitlement in this codebase is gated purely on the presence of a
# ``payment.Subscription`` whose ``expiration_date`` is in the future (see
# ``payment.billing.user_has_active_subscription`` and ``Subscription.is_active``).
# We grant that with a local row only -- no Stripe. Empty ``platform_data`` makes
# ``subscription_monthly_cents`` fall back to the default subscription tier, so the
# field-test user gets a normal paid monthly cap rather than an unlimited one.
FIELD_TEST_SUBSCRIPTION_TYPE = "field-test"
FIELD_TEST_SUBSCRIPTION_DAYS = 3650


def field_test_email_for_slug(slug: str) -> str:
    """Build the reserved email for a field-test ``slug``."""
    return f"field-test-{slug}@{FIELD_TEST_DOMAIN}"


def is_field_test_email(email: str) -> bool:
    """True only for emails matching the reserved field-test contract.

    Case-folded and whitespace-stripped; ``fullmatch`` rejects trailing-newline
    and suffix tricks (e.g. ``field-test-x@example.com.evil.com``).
    """
    normalized = (email or "").strip().casefold()
    return FIELD_TEST_EMAIL_PATTERN.fullmatch(normalized) is not None


def assert_field_test_email(email: str) -> None:
    """Raise ``CommandError`` unless ``email`` matches the reserved contract.

    This is the hard guardrail: it runs before any destructive/mutating write so
    a non-field-test user can never be touched.
    """
    if not is_field_test_email(email):
        msg = (
            f"Refusing to operate on {email!r}: field-test users must match "
            f"{FIELD_TEST_EMAIL_PATTERN.pattern}. No changes were made."
        )
        raise CommandError(msg)


class Command(BaseCommand):
    help = (
        "Manage the lifecycle of a field-test user "
        "(field-test-<slug>@example.com). EXCLUSIVELY for field tests: emails "
        "under example.com are filtered by the email backend (no real mail), so "
        "this command provisions verified email and a FAKE paid subscription "
        "(a local payment.Subscription row -- never a real Stripe charge). It "
        "refuses to destroy or modify any user whose email does not match the "
        "reserved ^field-test-[a-z0-9-]+@example\\.com$ pattern. Emits JSON to "
        "stdout so the field-test harness can consume the email/password/user id."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--create",
            metavar="SLUG",
            help=(
                "Create field-test-SLUG@example.com with a generated strong "
                "password (printed as JSON), verified email, and faked paid "
                "entitlement. Fails if the user already exists."
            ),
        )
        group.add_argument(
            "--destroy",
            metavar="SLUG",
            help=(
                "Delete field-test-SLUG@example.com via the canonical "
                "account-deletion path (cascade-cleans owned data). Idempotent: "
                "a no-op if the user does not exist."
            ),
        )
        group.add_argument(
            "--recycle",
            metavar="SLUG",
            help=(
                "Destroy-if-exists then create field-test-SLUG@example.com. Use "
                "this to get a guaranteed-fresh field-test user."
            ),
        )

    def handle(self, *args, **options):
        if options["create"] is not None:
            action, raw_slug = "create", options["create"]
        elif options["destroy"] is not None:
            action, raw_slug = "destroy", options["destroy"]
        else:
            action, raw_slug = "recycle", options["recycle"]

        slug = self._validate_slug(raw_slug)
        email = field_test_email_for_slug(slug)
        # Belt-and-suspenders: even though we constructed the email from a
        # validated slug, run the guardrail before doing anything.
        assert_field_test_email(email)

        if action == "create":
            result = self._create(email)
        elif action == "destroy":
            result = self._destroy(email)
        else:  # recycle
            destroyed = self._destroy(email)
            result = self._create(email)
            result["action"] = "recycle"
            result["destroyed_existing"] = destroyed["destroyed"]

        self.stdout.write(json.dumps(result))

    # -- helpers ----------------------------------------------------------------

    def _validate_slug(self, raw_slug: str) -> str:
        slug = (raw_slug or "").strip()
        if not FIELD_TEST_SLUG_PATTERN.fullmatch(slug):
            msg = (
                f"Invalid field-test slug {raw_slug!r}: must match "
                r"[a-z0-9-]+ (lowercase letters, digits, and hyphens)."
            )
            raise CommandError(msg)
        return slug

    def _create(self, email: str) -> dict:
        # Guardrail before the first write.
        assert_field_test_email(email)
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            msg = (
                f"Field-test user {email} already exists. Use --recycle to "
                f"replace it, or --destroy first."
            )
            raise CommandError(msg)

        password = secrets.token_urlsafe(24)
        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                password=password,
                first_name="Field",
                last_name="Test",
            )
            # Provision the two things a filtered example.com user can never get
            # on its own: a verified email and paid entitlement.
            ensure_user_email_verified(user)
            self._grant_faked_paid_entitlement(user)

        return {
            "action": "create",
            "email": user.email,
            "user_id": user.id,
            "password": password,
            "verified": True,
            "entitled": True,
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

        # HARD GUARDRAIL: never delete a user whose stored email is not a
        # field-test identity, even if it was somehow fetched here.
        assert_field_test_email(user.email)

        user_id = user.id
        # Canonical account-deletion path: a plain cascade delete, exactly like
        # users.views.DeleteUserView ("delete-account"). Do NOT hand-roll a
        # partial delete -- Django cascades clean the owned Account,
        # Subscription, auth Token, APNS token, allauth EmailAddress rows, etc.
        user.delete()
        return {
            "action": "destroy",
            "email": email,
            "destroyed": True,
            "user_id": user_id,
        }

    def _grant_faked_paid_entitlement(self, user) -> None:
        """Give ``user`` a paid-equivalent state with LOCAL records only.

        No payment provider is contacted. Entitlement is gated on an active
        ``payment.Subscription`` (future ``expiration_date``); we create one
        directly. This is only ever safe for field-test users.
        """
        account = user.get_account()
        Subscription.objects.update_or_create(
            account=account,
            defaults={
                "subscription_type": FIELD_TEST_SUBSCRIPTION_TYPE,
                "expiration_date": (
                    timezone.now() + timedelta(days=FIELD_TEST_SUBSCRIPTION_DAYS)
                ),
                "platform_data": {"provider": "field-test", "manual_grant": True},
            },
        )
