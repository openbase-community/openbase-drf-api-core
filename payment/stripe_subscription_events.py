from datetime import UTC, datetime

from django.db import transaction
from django.utils import timezone

from payment.models import Account, Subscription


def stripe_subscription_item(subscription_object):
    items = subscription_object.get("items", {}).get("data", [{}])
    for item in items:
        recurring = item.get("price", {}).get("recurring") or {}
        if recurring.get("usage_type") != "metered":
            return item
    return items[0] if items else {}


def stripe_subscription_product_id(subscription_object) -> str:
    return str(
        stripe_subscription_item(subscription_object)
        .get("price", {})
        .get("product", "")
    )


def stripe_subscription_period_end_timestamp(subscription_object):
    return (
        subscription_object.get("current_period_end")
        or stripe_subscription_item(subscription_object).get("current_period_end")
        or subscription_object.get("trial_end")
    )


def stripe_subscription_is_terminal(subscription_object) -> bool:
    """Return whether Stripe says access has actually ended."""
    return bool(
        subscription_object.get("ended_at")
        or subscription_object.get("status")
        in {"canceled", "incomplete_expired", "unpaid"}
    )


def apply_stripe_subscription_event(  # noqa: PLR0911
    *,
    account: Account,
    event_type: str,
    event_id: str,
    event_created: int | None,
    subscription_object,
) -> str:
    """Apply a Stripe subscription snapshot monotonically."""
    incoming_terminal = bool(
        event_type == "customer.subscription.deleted"
        or stripe_subscription_is_terminal(subscription_object)
    )
    event_stripe_id = str(subscription_object.get("id") or "")

    with transaction.atomic():
        Account.objects.select_for_update().get(pk=account.pk)
        stored_subscription = Subscription.objects.filter(account=account).first()
        if (
            stored_subscription
            and event_id
            and stored_subscription.stripe_event_id == event_id
        ):
            if (
                stored_subscription.stripe_event_terminal
                and not stored_subscription.stripe_terminal_cleanup_completed
            ):
                return "expired"
            return "ignored_duplicate"
        if (
            stored_subscription
            and event_created is not None
            and stored_subscription.stripe_event_created is not None
        ):
            if event_created < stored_subscription.stripe_event_created:
                return "ignored_stale"
            if (
                event_created == stored_subscription.stripe_event_created
                and stored_subscription.stripe_event_terminal
                and not incoming_terminal
            ):
                return "ignored_stale"

        stored_stripe_id = (
            stored_subscription.stripe_subscription_id
            if stored_subscription
            else None
        )
        event_is_for_other_subscription = bool(
            stored_stripe_id
            and event_stripe_id
            and event_stripe_id != stored_stripe_id
        )
        if event_is_for_other_subscription and (
            incoming_terminal or stored_subscription.is_active()
        ):
            return "ignored_other_subscription"

        ordering_defaults = {
            "stripe_event_created": event_created,
            "stripe_event_id": event_id,
            "stripe_event_terminal": incoming_terminal,
            "stripe_terminal_cleanup_completed": not incoming_terminal,
        }
        if incoming_terminal:
            Subscription.objects.update_or_create(
                account=account,
                defaults={
                    "subscription_type": stripe_subscription_product_id(
                        subscription_object
                    ),
                    "expiration_date": timezone.now(),
                    "platform_data": subscription_object,
                    **ordering_defaults,
                },
            )
            return "expired"

        if event_type not in {
            "customer.subscription.created",
            "customer.subscription.updated",
        }:
            return "ignored_event_type"
        period_end = stripe_subscription_period_end_timestamp(subscription_object)
        if not period_end:
            return "missing_period_end"
        Subscription.objects.update_or_create(
            account=account,
            defaults={
                "subscription_type": stripe_subscription_product_id(
                    subscription_object
                ),
                "expiration_date": datetime.fromtimestamp(period_end, tz=UTC),
                "platform_data": subscription_object,
                **ordering_defaults,
            },
        )
        return "synced"
