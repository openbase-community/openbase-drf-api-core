"""Policy helpers for production field-test identities."""

import os
import re

from django.core.management import CommandError

FIELD_TEST_ALLOWLIST_ENV = "FIELD_TEST_ALLOWED_EMAILS"

# Resend's delivered+<label>@resend.dev recipient exercises the real production
# send path without delivering to a person's inbox. Requiring our own random run
# label protects unrelated Resend test traffic and gives every field test an
# exact address that can be allowlisted and queried independently.
RESERVED_FIELD_TEST_EMAIL_RE = re.compile(
    r"^delivered\+openbase-field-[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?@resend\.dev$"
)


def normalize_email(email: str) -> str:
    return (email or "").strip().casefold()


def field_test_allowed_emails() -> frozenset[str]:
    """Return normalized, exact allowlist entries; empty means deny all."""
    raw = os.environ.get(FIELD_TEST_ALLOWLIST_ENV, "")
    return frozenset(
        normalize_email(entry) for entry in raw.split(",") if entry.strip()
    )


def is_reserved_field_test_email(email: str) -> bool:
    """Return whether ``email`` is an official Resend field-test recipient."""
    return RESERVED_FIELD_TEST_EMAIL_RE.fullmatch(normalize_email(email)) is not None


def is_allowed_field_test_email(email: str) -> bool:
    normalized = normalize_email(email)
    return (
        bool(normalized)
        and normalized in field_test_allowed_emails()
        and is_reserved_field_test_email(normalized)
    )


def assert_allowed_field_test_email(email: str) -> None:
    """Reject unsafe identities before any account read or write."""
    normalized = normalize_email(email)
    allowed = field_test_allowed_emails()
    if normalized not in allowed:
        if not allowed:
            msg = (
                f"Refusing to operate: {FIELD_TEST_ALLOWLIST_ENV} is empty. "
                "No changes were made."
            )
        else:
            msg = (
                f"Refusing to operate on {normalized!r}: exact membership in "
                f"{FIELD_TEST_ALLOWLIST_ENV} is required. No changes were made."
            )
        raise CommandError(msg)
    if not is_reserved_field_test_email(normalized):
        msg = (
            f"Refusing to operate on {normalized!r}: field-test identities must use "
            "Resend's delivered+openbase-field-<slug>@resend.dev testing-recipient "
            "format. Personal inboxes and other plus-addresses are forbidden even "
            "when allowlisted. No changes were made."
        )
        raise CommandError(msg)
