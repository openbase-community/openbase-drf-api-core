import functools
import importlib.metadata
from collections.abc import Callable
from datetime import datetime  # noqa: TC003
from typing import NamedTuple

import structlog

logger = structlog.get_logger(__name__)


class AnalyticsEvent(NamedTuple):
    source: str
    event_name: str
    external_event_id: str
    occurred_at: datetime
    external_user_id: str = ""
    anonymous_id: str = ""
    session_id: str = ""
    properties: dict | None = None
    provenance: dict | None = None


AnalyticsReceiver = Callable[[AnalyticsEvent], None]


class AnalyticsDeliveryError(RuntimeError):
    """A durable analytics delivery failed and should be retried upstream."""


@functools.cache
def get_analytics_receivers() -> tuple[AnalyticsReceiver, ...]:
    entry_points = importlib.metadata.entry_points()
    return tuple(
        entry_point.load()
        for entry_point in entry_points.select(group="api_core.analytics")
    )


def notify_analytics_event(
    event: AnalyticsEvent,
    *,
    require_delivery: bool = False,
) -> None:
    first_error = None
    for receiver in get_analytics_receivers():
        try:
            receiver(event)
        except Exception as exc:
            # Analytics is observational. A failed sink must not turn a valid
            # login, portal session, or payment webhook into a product outage.
            logger.exception(
                "Analytics receiver failed",
                source=event.source,
                event_name=event.event_name,
            )
            first_error = first_error or exc
    if first_error is not None and require_delivery:
        msg = "A durable analytics receiver failed."
        raise AnalyticsDeliveryError(msg) from first_error
