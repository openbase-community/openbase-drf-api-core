# ruff: noqa: S101

from datetime import UTC, datetime
from types import SimpleNamespace

from payment.analytics import stripe_event_to_analytics_event


def test_stripe_event_to_analytics_event_keeps_only_analytical_fields():
    event = SimpleNamespace(
        id="evt_123",
        type="invoice.paid",
        created=1_788_192_000,
        api_version="2026-06-30",
        livemode=True,
        data=SimpleNamespace(
            object={
                "object": "invoice",
                "id": "in_123",
                "customer": "cus_123",
                "subscription": "sub_123",
                "status": "paid",
                "currency": "usd",
                "amount_paid": 2000,
                "cancellation_details": {
                    "feedback": "too_expensive",
                    "reason": "cancellation_requested",
                    "comment": "private free-form comment must not be copied",
                },
                "customer_email": "must-not-be-copied@example.com",
                "client_secret": "must-not-be-copied",
            }
        ),
    )

    analytics_event = stripe_event_to_analytics_event(event)

    assert analytics_event.source == "stripe"
    assert analytics_event.event_name == "stripe.invoice.paid"
    assert analytics_event.external_event_id == "evt_123"
    assert analytics_event.external_user_id == "cus_123"
    assert analytics_event.occurred_at == datetime.fromtimestamp(1_788_192_000, tz=UTC)
    assert analytics_event.properties == {
        "amount_paid": 2000,
        "cancellation_feedback": "too_expensive",
        "cancellation_reason": "cancellation_requested",
        "currency": "usd",
        "status": "paid",
        "subscription_id": "sub_123",
    }
    assert "customer_email" not in analytics_event.properties
    assert "client_secret" not in analytics_event.properties
    assert "comment" not in analytics_event.properties
