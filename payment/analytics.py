from datetime import UTC, datetime

from config.analytics import AnalyticsEvent

STRIPE_EVENT_NAME_PREFIX = "stripe."
PORTAL_SESSION_REQUESTED = "billing.portal_session_requested"
PORTAL_SESSION_CREATED = "billing.portal_session_created"
PORTAL_SESSION_FAILED = "billing.portal_session_failed"


def _value(mapping, key, default=None):
    if hasattr(mapping, "get"):
        return mapping.get(key, default)
    return getattr(mapping, key, default)


def stripe_event_to_analytics_event(event) -> AnalyticsEvent:
    data = _value(event, "data", {})
    stripe_object = _value(data, "object", {})
    object_type = str(_value(stripe_object, "object", ""))
    object_id = str(_value(stripe_object, "id", ""))
    customer_id = _value(stripe_object, "customer", "")
    if not customer_id and object_type == "customer":
        customer_id = object_id

    subscription_id = _value(stripe_object, "subscription", "")
    if not subscription_id and object_type == "subscription":
        subscription_id = object_id

    properties = {
        key: _value(stripe_object, key)
        for key in (
            "amount",
            "amount_due",
            "amount_paid",
            "amount_remaining",
            "currency",
            "status",
            "cancel_at_period_end",
            "cancellation_reason",
        )
        if _value(stripe_object, key) is not None
    }
    cancellation_details = _value(stripe_object, "cancellation_details", {}) or {}
    for provider_key, analytics_key in (
        ("feedback", "cancellation_feedback"),
        ("reason", "cancellation_reason"),
    ):
        value = _value(cancellation_details, provider_key)
        if value is not None:
            properties[analytics_key] = value
    if subscription_id:
        properties["subscription_id"] = str(subscription_id)

    created = _value(event, "created")
    occurred_at = datetime.fromtimestamp(int(created), tz=UTC)
    return AnalyticsEvent(
        source="stripe",
        event_name=f"{STRIPE_EVENT_NAME_PREFIX}{_value(event, 'type')}",
        external_event_id=str(_value(event, "id")),
        occurred_at=occurred_at,
        external_user_id=str(customer_id or ""),
        properties=properties,
        provenance={
            "collector": "stripe_event",
            "api_version": _value(event, "api_version"),
            "livemode": bool(_value(event, "livemode")),
            "object_type": object_type,
            "object_id": object_id,
        },
    )
