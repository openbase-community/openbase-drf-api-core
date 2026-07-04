"""Subscription tier table, supplied by the consuming app.

api-core ships no pricing menu of its own. App packages define
``SUBSCRIPTION_TIERS`` (and ``DEFAULT_SUBSCRIPTION_TIER_CENTS``) in their
``api_core.settings`` entry-point module:

    SUBSCRIPTION_TIERS = {
        2000: {
            "plan": "pro",
            "name": "Pro",
            "price_setting": "OPENBASE_STRIPE_PRO_PRICE_ID",
            "trial_period_days": 1,  # optional
        },
    }

Keys are the monthly price in cents. ``plan`` indexes into
``OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS``; ``price_setting`` names the env var
to mention when that price ID is missing.
"""

from django.conf import settings
from rest_framework.exceptions import ValidationError


def subscription_tier_table() -> dict[int, dict]:
    return settings.SUBSCRIPTION_TIERS


def default_subscription_tier_cents() -> int:
    return settings.DEFAULT_SUBSCRIPTION_TIER_CENTS


def validate_subscription_tier_cents(value) -> int:
    """Return the exact configured tier for ``value``, else raise ValidationError."""
    amount = int(value or default_subscription_tier_cents())
    if amount not in subscription_tier_table():
        msg = "Unsupported subscription tier."
        raise ValidationError(msg)
    return amount


def subscription_tier(value) -> dict:
    return subscription_tier_table()[validate_subscription_tier_cents(value)]


def floor_subscription_tier_cents(amount_cents: int) -> int:
    """Floor an arbitrary charged amount to the highest tier it covers.

    Used when deriving a spend cap from a provider-reported charge (which may
    include prorations or legacy prices), unlike ``validate_subscription_tier_cents``
    which rejects anything not exactly on the menu.
    """
    if amount_cents <= 0:
        return 0
    for tier_cents in sorted(subscription_tier_table(), reverse=True):
        if amount_cents >= tier_cents:
            return tier_cents
    return 0


def subscription_tier_price_id(value) -> str:
    tier = subscription_tier(value)
    price_ids = getattr(settings, "OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS", {})
    price_id = price_ids.get(tier["plan"], "").strip()
    if not price_id:
        msg = (
            f"Stripe Price ID is not configured for {tier['name']}. "
            f"Set {tier['price_setting']}."
        )
        raise ValidationError(msg)
    return price_id
