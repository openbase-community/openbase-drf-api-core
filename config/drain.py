"""Process-level shutdown drain state.

When the web process receives SIGTERM during a rollout, the gunicorn worker
shim the platform ships (``openbase_gunicorn_worker``) calls :func:`begin`
and then runs the app's ``WEB_DRAIN_HOOKS`` before letting uvicorn shut down.
While draining, :class:`DrainingHealthMiddleware` answers the health-check
path with 503 so the edge proxy stops routing new connections to this
process and sends them to the incoming task instead.
"""

from __future__ import annotations

import threading

from django.conf import settings
from django.http import HttpResponse

_draining = threading.Event()


def begin() -> None:
    _draining.set()


def is_draining() -> bool:
    return _draining.is_set()


def reset() -> None:
    """Tests only: a fresh process never drains until told to."""
    _draining.clear()


class DrainingHealthMiddleware:
    """503 on the health-check path while this process is draining.

    Everything else keeps being served normally: in-flight requests and
    long-lived websockets finish on this process, only new routing moves.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_draining() and request.path == settings.WEB_HEALTH_CHECK_PATH:
            return HttpResponse(
                "draining", status=503, content_type="text/plain; charset=utf-8"
            )
        return self.get_response(request)
