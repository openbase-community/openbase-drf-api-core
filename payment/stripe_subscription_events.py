from datetime import UTC, datetime

from django.conf import settings
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


def stripe_subscription_period_start_timestamp(subscription_object):
    return subscription_object.get("current_period_start") or stripe_subscription_item(
        subscription_object
    ).get("current_period_start")


def stripe_subscription_is_terminal(subscription_object) -> bool:
    """Return whether Stripe says access has actually ended."""
    return bool(
        subscription_object.get("ended_at")
        or subscription_object.get("status")
        in {"canceled", "incomplete_expired", "unpaid"}
    )


# Statuses where the subscription exists but nothing has been paid for the
# current period: ``incomplete`` (first invoice not yet paid, e.g. a failed or
# pending card) and ``paused`` (trial ended without a payment method). They
# grant no access, but they are not terminal either: Stripe can still move
# them to ``active``, so resources are not torn down.
STRIPE_NO_ACCESS_STATUSES = frozenset({"incomplete", "paused"})


def stripe_subscription_grants_access(subscription_object) -> bool:
    return subscription_object.get("status") not in STRIPE_NO_ACCESS_STATUSES


def stripe_subscription_period_is_unpaid(subscription_object) -> bool:
    """Whether the snapshot's current period must not extend access: an
    unpaid status, or ``past_due`` (renewal invoice failed, Smart Retries
    still running) unless the deployment grants access while past due."""
    if not stripe_subscription_grants_access(subscription_object):
        return True
    return (
        subscription_object.get("status") == "past_due"
        and not settings.OPENBASE_STRIPE_PAST_DUE_GRANTS_ACCESS
    )


def unpaid_period_expiration(
    subscription_object, stored_subscription, period_end: datetime
) -> datetime:
    """Expiration for a ``past_due`` snapshot. Stripe advances the period at
    renewal before the renewal invoice is paid (and the "updated" snapshot
    for that rollover is still active), so the snapshot's period end would
    read as paid through the new, unpaid month. Access never runs past what
    was already granted or past the unpaid period's start, whichever is
    earlier; the active snapshot after a successful retry re-grants it."""
    expiration = period_end
    period_start = stripe_subscription_period_start_timestamp(subscription_object)
    if period_start:
        expiration = min(expiration, datetime.fromtimestamp(period_start, tz=UTC))
    granted_through = (
        stored_subscription.expiration_date if stored_subscription else timezone.now()
    )
    return min(expiration, granted_through)


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
            # Stripe stamps the incomplete "created" event and the "updated"
            # event for its successful first payment with the same second, and
            # delivery order is not guaranteed: never let that unpaid snapshot
            # revoke a paid one from the same second. The shield is deliberately
            # NOT extended to past_due: a stored active row is as likely to be
            # the still-active period rollover (unpaid) as a paid retry, and
            # nothing in the snapshot tells them apart, so the tie goes to the
            # unpaid reading. The rare paid retry stamped in the same second
            # as its past_due re-grants on the next subscription snapshot.
            if (
                event_created == stored_subscription.stripe_event_created
                and not incoming_terminal
                and not stripe_subscription_grants_access(subscription_object)
                and stored_subscription.is_active()
            ):
                return "ignored_stale"

        stored_stripe_id = (
            stored_subscription.stripe_subscription_id if stored_subscription else None
        )
        event_is_for_other_subscription = bool(
            stored_stripe_id and event_stripe_id and event_stripe_id != stored_stripe_id
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
        if not stripe_subscription_grants_access(subscription_object):
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
            return "no_access"
        period_end = stripe_subscription_period_end_timestamp(subscription_object)
        if not period_end:
            return "missing_period_end"
        expiration_date = datetime.fromtimestamp(period_end, tz=UTC)
        result = "synced"
        if stripe_subscription_period_is_unpaid(subscription_object):
            expiration_date = unpaid_period_expiration(
                subscription_object, stored_subscription, expiration_date
            )
            result = "past_due"
        Subscription.objects.update_or_create(
            account=account,
            defaults={
                "subscription_type": stripe_subscription_product_id(
                    subscription_object
                ),
                "expiration_date": expiration_date,
                "platform_data": subscription_object,
                **ordering_defaults,
            },
        )
        return result
