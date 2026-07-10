import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from teams.models import get_user_or_team_ownership_mixin

UserOrTeamOwnershipMixin = get_user_or_team_ownership_mixin(
    "account", on_delete=models.CASCADE, relation_type=models.OneToOneField
)


class Account(UserOrTeamOwnershipMixin):
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal(0))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    customer_id = models.CharField(
        max_length=255, blank=True, help_text="Stripe customer ID"
    )
    apple_uuid = models.UUIDField(blank=True, default="")  # type: ignore

    @property
    def get_email(self):
        if self.user_owner:
            return self.user_owner.email
        elif self.team_owner:
            return self.team_owner.email
        msg = "Account has no owner"
        raise ValueError(msg)

    async def has_active_subscription(self):
        subscription = await Subscription.objects.filter(account=self).afirst()
        return subscription.is_active() if subscription else False

    @property
    def is_personal(self):
        return self.user_owner is not None

    def save(
        self, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        if self.user_owner and self.team_owner:
            msg = "Account cannot have both user_owner and team_owner"
            raise ValidationError(msg)
        if not self.apple_uuid:
            self.apple_uuid = uuid.uuid4()
        super().save(
            force_insert=False, force_update=False, using=None, update_fields=None
        )

    def __str__(self):
        return f"{self.user_owner or self.team_owner} account"


class Subscription(models.Model):
    account = models.OneToOneField(
        Account, related_name="subscription", on_delete=models.CASCADE
    )
    subscription_type = models.CharField(max_length=100)
    expiration_date = models.DateTimeField()
    platform_data = models.JSONField(default=dict, blank=True)
    is_sandbox = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.account} subscription"

    def is_active(self):
        return self.expiration_date > timezone.now()

    # ``platform_data`` holds the raw provider payload (a Stripe subscription
    # object for Stripe-billed subscriptions, an Apple receipt for App Store
    # ones, or arbitrary data for manual grants). The typed accessors below are
    # deliberately defensive about its shape so consuming apps never need to
    # parse the raw payload themselves.

    @property
    def stripe_subscription_id(self) -> str | None:
        """The ``sub_...`` Stripe subscription id, or ``None`` when this
        subscription is not billed through Stripe."""
        if not isinstance(self.platform_data, dict):
            return None
        subscription_id = str(self.platform_data.get("id", ""))
        if not subscription_id.startswith("sub_"):
            return None
        return subscription_id

    @property
    def is_stripe_billed(self) -> bool:
        return self.stripe_subscription_id is not None

    @property
    def stripe_customer_id(self) -> str:
        return self.account.customer_id

    def stripe_price_items(self) -> list[dict]:
        """Item dicts from ``platform_data["items"]["data"]`` that carry a dict
        ``price``; empty for non-Stripe or malformed payloads."""
        if not isinstance(self.platform_data, dict):
            return []
        items = self.platform_data.get("items")
        if not isinstance(items, dict):
            return []
        data = items.get("data")
        if not isinstance(data, list):
            return []
        return [
            item
            for item in data
            if isinstance(item, dict) and isinstance(item.get("price"), dict)
        ]

    def has_price_item(self, price_id: str) -> bool:
        return any(
            item["price"].get("id") == price_id for item in self.stripe_price_items()
        )

    @property
    def monthly_licensed_price_cents(self) -> int | None:
        """Monthly cents of the licensed (non-metered) flat-fee Stripe item.

        Metered add-on items (e.g. usage-overage prices) are skipped. Yearly
        and multi-interval prices are normalized to one month with ceiling
        division. Returns ``None`` when ``platform_data`` carries no usable
        licensed price (non-Stripe subscriptions, manual grants).
        """
        for item in self.stripe_price_items():
            price = item["price"]
            recurring = price.get("recurring")
            recurring = recurring if isinstance(recurring, dict) else {}
            if recurring.get("usage_type") == "metered":
                continue
            unit_amount = price.get("unit_amount")
            if unit_amount is None:
                continue
            interval = recurring.get("interval", "month")
            interval_count = recurring.get("interval_count")
            if interval_count in (None, 0):
                interval_count = 1
            amount = int(unit_amount)
            if interval == "year":
                divisor = 12 * int(interval_count)
                return (amount + divisor - 1) // divisor
            if interval == "month":
                divisor = int(interval_count)
                return (amount + divisor - 1) // divisor
            return amount
        return None
