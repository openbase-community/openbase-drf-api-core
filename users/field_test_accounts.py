"""Policy helpers for production field-test identities."""

import re

from django.core.management import CommandError

# Resend's delivered+<label>@resend.dev recipient exercises the real production
# send path without delivering to a person's inbox. Requiring our own random run
# label protects unrelated Resend test traffic and gives every field test an
# exact address that can be queried independently.
RESERVED_FIELD_TEST_EMAIL_RE = re.compile(
    r"^delivered\+openbase-field-[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?@resend\.dev$"
)


def normalize_email(email: str) -> str:
    return (email or "").strip().casefold()


def is_reserved_field_test_email(email: str) -> bool:
    """Return whether ``email`` is an official Resend field-test recipient."""
    return RESERVED_FIELD_TEST_EMAIL_RE.fullmatch(normalize_email(email)) is not None


def assert_reserved_field_test_email(email: str) -> None:
    """Reject unsafe identities before any account read or write."""
    normalized = normalize_email(email)
    if not is_reserved_field_test_email(normalized):
        msg = (
            f"Refusing to operate on {normalized!r}: field-test identities must use "
            "Resend's delivered+openbase-field-<slug>@resend.dev testing-recipient "
            "format. Personal inboxes and other plus-addresses are forbidden. "
            "No changes were made."
        )
        raise CommandError(msg)
