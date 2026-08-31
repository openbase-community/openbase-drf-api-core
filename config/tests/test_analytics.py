from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from config.analytics import (
    AnalyticsDeliveryError,
    AnalyticsEvent,
    get_analytics_receivers,
    notify_analytics_event,
)


def test_analytics_receivers_load_from_entry_points(monkeypatch):
    receiver = object()
    entry_point = SimpleNamespace(load=lambda: receiver)
    entry_points = SimpleNamespace(select=lambda **_kwargs: [entry_point])
    monkeypatch.setattr(
        "config.analytics.importlib.metadata.entry_points", lambda: entry_points
    )
    get_analytics_receivers.cache_clear()

    assert get_analytics_receivers() == (receiver,)
    get_analytics_receivers.cache_clear()


def test_notify_analytics_event_preserves_the_contract(monkeypatch):
    received = []
    event = AnalyticsEvent(
        source="stripe",
        event_name="stripe.invoice.paid",
        external_event_id="evt_123",
        occurred_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    monkeypatch.setattr(
        "config.analytics.get_analytics_receivers", lambda: (received.append,)
    )

    notify_analytics_event(event)

    assert received == [event]


def test_receiver_failure_does_not_break_product_operation(monkeypatch):
    def failing_receiver(_event):
        msg = "analytics unavailable"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        "config.analytics.get_analytics_receivers",
        lambda: (failing_receiver,),
    )

    notify_analytics_event(
        AnalyticsEvent(
            source="internal",
            event_name="billing.portal_session_failed",
            external_event_id="test-event",
            occurred_at=datetime(2026, 8, 31, tzinfo=UTC),
        )
    )


def test_durable_receiver_failure_is_raised_for_upstream_retry(monkeypatch):
    def failing_receiver(_event):
        msg = "analytics unavailable"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        "config.analytics.get_analytics_receivers",
        lambda: (failing_receiver,),
    )
    event = AnalyticsEvent(
        source="stripe",
        event_name="stripe.invoice.paid",
        external_event_id="evt_retry",
        occurred_at=datetime(2026, 8, 31, tzinfo=UTC),
    )

    with pytest.raises(AnalyticsDeliveryError):
        notify_analytics_event(event, require_delivery=True)
