"""Policy helpers for production field-test identities and credentials."""

import os
import re

from django.core.management import CommandError

from config.email import is_non_delivery_email_domain

FIELD_TEST_ALLOWLIST_ENV = "FIELD_TEST_ALLOWED_EMAILS"
FIELD_TEST_PASSWORD_ENV = "FIELD_TEST_ACCOUNT_PASSWORD"  # noqa: S105

# Requiring the product-specific local-part as well as the shared non-delivery
# domain policy protects unrelated fixture users that happen to use an example
# domain. The email backend uses the same policy to suppress provider calls.
RESERVED_LOCAL_PART_RE = re.compile(
    r"^openbase-field-(?:test-)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)

# Keep an explicit denylist as defense in depth. The reserved-domain rule below
# rejects every ordinary provider, including providers not named here.
PERSONAL_EMAIL_DOMAINS = frozenset(
    {
        "aol.com",
        "fastmail.com",
        "gmail.com",
        "googlemail.com",
        "hotmail.com",
        "icloud.com",
        "live.com",
        "me.com",
        "msn.com",
        "outlook.com",
        "proton.me",
        "protonmail.com",
        "yahoo.com",
        "ymail.com",
    }
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
    """Return whether ``email`` is an explicitly reserved non-delivery identity."""
    normalized = normalize_email(email)
    if normalized.count("@") != 1:
        return False
    local_part, domain = normalized.rsplit("@", 1)
    if "+" in local_part or domain in PERSONAL_EMAIL_DOMAINS:
        return False
    if RESERVED_LOCAL_PART_RE.fullmatch(local_part) is None:
        return False
    return is_non_delivery_email_domain(domain)


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
            "an openbase-field-<slug> local-part on example.com, example.net, "
            "example.org, or a .test/.invalid domain. Personal email providers and "
            "plus-addressing are forbidden even when allowlisted. No changes were made."
        )
        raise CommandError(msg)


def field_test_password() -> str:
    """Read the provision password from the environment without echoing it."""
    password = os.environ.get(FIELD_TEST_PASSWORD_ENV, "")
    if not password:
        msg = (
            f"{FIELD_TEST_PASSWORD_ENV} must be present in the task environment for "
            "--provision. Passwords are never accepted as command arguments."
        )
        raise CommandError(msg)
    return password
