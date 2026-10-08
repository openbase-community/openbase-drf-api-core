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


def test_stripe_event_to_analytics_event_keeps_legacy_invoice_and_charge_revenue_fields():
    # The production webhook endpoint is pinned to a legacy Stripe API version
    # whose invoice payload carries total/subtotal/paid instead of amount_paid.
    legacy_invoice = SimpleNamespace(
        id="evt_legacy_invoice",
        type="invoice.paid",
        created=1_788_192_000,
        api_version="2016-07-06",
        livemode=True,
        data=SimpleNamespace(
            object={
                "object": "invoice",
                "id": "in_legacy",
                "customer": "cus_legacy",
                "subscription": "sub_legacy",
                "currency": "usd",
                "amount_due": 2000,
                "total": 2000,
                "subtotal": 2000,
                "paid": True,
                "lines": {"data": [{"description": "private line item"}]},
            }
        ),
    )
    refunded_charge = SimpleNamespace(
        id="evt_refund",
        type="charge.refunded",
        created=1_788_192_100,
        api_version="2016-07-06",
        livemode=True,
        data=SimpleNamespace(
            object={
                "object": "charge",
                "id": "ch_refund",
                "customer": "cus_legacy",
                "currency": "usd",
                "amount": 2000,
                "amount_refunded": 2000,
                "refunded": True,
                "status": "succeeded",
                "receipt_email": "must-not-be-copied@example.com",
            }
        ),
    )

    invoice_event = stripe_event_to_analytics_event(legacy_invoice)
    charge_event = stripe_event_to_analytics_event(refunded_charge)

    assert invoice_event.event_name == "stripe.invoice.paid"
    assert invoice_event.properties == {
        "amount_due": 2000,
        "currency": "usd",
        "paid": True,
        "subscription_id": "sub_legacy",
        "subtotal": 2000,
        "total": 2000,
    }
    assert charge_event.event_name == "stripe.charge.refunded"
    assert charge_event.external_user_id == "cus_legacy"
    assert charge_event.properties == {
        "amount": 2000,
        "amount_refunded": 2000,
        "currency": "usd",
        "refunded": True,
        "status": "succeeded",
    }
    assert "receipt_email" not in charge_event.properties
