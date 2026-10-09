import asyncio
import sys

import pytest
from django.conf import settings
from django.core.handlers.asgi import ASGIHandler
from django.test import override_settings
from django.urls import path

from config.sentry import (
    filter_expected_sentry_events,
    track_http_disconnects,
)


async def _view(request, route):
    request.scope["started"].set()
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        event = {"exception": {"values": [{"type": "CancelledError"}]}}
        request.scope["results"].append(
            filter_expected_sentry_events(event, {"exc_info": sys.exc_info()})
        )
        raise


urlpatterns = [path("<path:route>", _view)]


@pytest.mark.parametrize("request_path", ["/api/csrf/", "/_allauth/browser/v1/config"])
def test_real_django_disconnect_cancels_tracked_request(request_path):
    if not settings.configured:
        settings.configure()

    async def run():
        started = asyncio.Event()
        results = []
        messages = iter(
            [
                {"type": "http.request", "body": b"", "more_body": False},
                {"type": "http.disconnect"},
            ]
        )

        async def receive():
            message = next(messages)
            if message["type"] == "http.disconnect":
                await started.wait()
            return message

        async def send(message):
            pytest.fail(f"Disconnected request unexpectedly sent {message['type']}")

        scope = {
            "type": "http",
            "path": request_path,
            "method": "GET",
            "headers": [],
            "query_string": b"",
            "started": started,
            "results": results,
        }
        await asyncio.wait_for(
            track_http_disconnects(ASGIHandler())(scope, receive, send), 5
        )
        assert results == [None]

    with override_settings(
        ROOT_URLCONF=__name__,
        MIDDLEWARE=["config.sentry.track_request_task"],
        FORCE_SCRIPT_NAME=None,
    ):
        asyncio.run(run())
