import functools
import importlib.metadata
from collections.abc import Callable
from typing import Any

import structlog
from django.contrib.sessions.backends.base import SessionBase
from django.http import HttpRequest

logger = structlog.get_logger(__name__)

JWT_ANALYTICS_ENTRY_POINT_GROUP = "api_core.jwt_analytics"

JwtIssuedReceiver = Callable[..., None]


@functools.cache
def get_jwt_analytics_receivers() -> tuple[JwtIssuedReceiver, ...]:
    entry_points = importlib.metadata.entry_points()
    return tuple(
        entry_point.load()
        for entry_point in entry_points.select(group=JWT_ANALYTICS_ENTRY_POINT_GROUP)
    )


def notify_jwt_issued(
    *,
    user: Any,
    session: SessionBase,
    source: str,
    request: HttpRequest | None = None,
) -> None:
    for receiver in get_jwt_analytics_receivers():
        try:
            receiver(user=user, session=session, source=source, request=request)
        except Exception:
            logger.exception(
                "jwt_analytics_receiver_failed",
                receiver=getattr(receiver, "__module__", repr(receiver)),
                source=source,
            )
