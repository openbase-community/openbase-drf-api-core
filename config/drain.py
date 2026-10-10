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

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
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

    Async-capable on purpose: a sync-only middleware in the ASGI stack makes
    Django run every inner middleware and view through one thread-sensitive
    worker thread, which serialises the whole API (and starves the health
    probes it is meant to answer).
    """

    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        if iscoroutinefunction(get_response):
            markcoroutinefunction(self)

    def __call__(self, request):
        if iscoroutinefunction(self.get_response):
            return self._async_call(request)
        if _health_probe_while_draining(request):
            return _draining_response()
        return self.get_response(request)

    async def _async_call(self, request):
        if _health_probe_while_draining(request):
            return _draining_response()
        return await self.get_response(request)


def _health_probe_while_draining(request) -> bool:
    return is_draining() and request.path == settings.WEB_HEALTH_CHECK_PATH


def _draining_response() -> HttpResponse:
    return HttpResponse(
        "draining", status=503, content_type="text/plain; charset=utf-8"
    )
