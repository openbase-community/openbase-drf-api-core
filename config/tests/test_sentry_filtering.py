import asyncio
import json
import sys

import pytest
import sentry_sdk
from sentry_sdk.integrations.argv import ArgvIntegration
from sentry_sdk.transport import Transport

from config.sentry import (
    filter_expected_sentry_events,
    track_http_disconnects,
    track_request_task,
)


@pytest.mark.parametrize("command", ["shell", "dbshell", "shell_plus"])
@pytest.mark.parametrize("extra", [{}, {"sys.argv": "[Filtered]"}])
def test_interactive_commands_never_report(monkeypatch, command, extra):
    monkeypatch.setattr(
        sys, "argv", ["manage.py", command, "-c", "user@example.invalid"]
    )
    assert filter_expected_sentry_events({"extra": extra}, {}) is None


@pytest.mark.parametrize(
    "launcher",
    [
        "manage.py",
        "/app/manage.py",
        "django-admin",
        "django-admin.py",
        "/lib/django/__main__.py",
    ],
)
@pytest.mark.parametrize("command", ["migrate", "backfill", "run_jobs"])
def test_management_errors_keep_diagnostics_without_command_lines(
    monkeypatch, launcher, command
):
    argv = [launcher, command, "--email=user@example.invalid"]
    monkeypatch.setattr(sys, "argv", argv)
    event = {
        "exception": {"values": [{"type": "RuntimeError", "value": "job failed"}]},
        "extra": {
            "sys.argv": argv,
            "command_line": "user@example.invalid",
            "nested": [{"argv": argv}],
            "job_id": 123,
        },
        "contexts": {"process": {"command-line": argv, "pid": 123}},
        "breadcrumbs": {"values": [{"data": {"cmdline": argv, "status": "started"}}]},
    }
    assert filter_expected_sentry_events(event, {}) is event
    assert "example.invalid" not in json.dumps(event)
    assert event["exception"]["values"][0]["value"] == "job failed"
    assert event["extra"]["job_id"] == 123
    assert event["contexts"]["process"]["pid"] == 123
    assert sys.argv == argv


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["uvicorn"],
        ["uvicorn", "config.asgi:application"],
        ["taskiq", "worker", "shell"],
    ],
)
def test_non_management_events_are_unchanged(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", argv)
    event = {"extra": {"sys.argv": ["server"], "args": "diagnostic"}}
    assert filter_expected_sentry_events(event, {}) is event
    assert event["extra"]["args"] == "diagnostic"


@pytest.mark.parametrize(
    ("command", "expected_count"),
    [("migrate", 1), ("backfill", 1), ("shell", 0), ("dbshell", 0), ("shell_plus", 0)],
)
def test_sdk_payload_scrubs_argv(monkeypatch, command, expected_count):
    monkeypatch.setattr(
        sys, "argv", ["manage.py", command, "--email=user@example.invalid"]
    )
    events = []

    class RecordingTransport(Transport):
        def capture_envelope(self, envelope):
            events.extend(
                item.payload.json for item in envelope.items if item.type == "event"
            )

    client = sentry_sdk.Client(
        dsn="https://public@example.invalid/1",
        transport=RecordingTransport(),
        before_send=filter_expected_sentry_events,
        include_local_variables=False,
        default_integrations=False,
        integrations=[ArgvIntegration()],
    )
    with sentry_sdk.isolation_scope() as scope:
        scope.set_client(client)
        sentry_sdk.capture_exception(RuntimeError("job failed"))
    client.close()
    assert len(events) == expected_count
    assert "example.invalid" not in json.dumps(events)


def _event(path):
    return {
        "exception": {"values": [{"type": "CancelledError"}]},
        "request": {"url": f"https://app.example.invalid{path}"},
    }


async def _cancelled_request(
    path, *, disconnect=True, background=False, mixed=False, manual=False, thread=False
):
    event = _event(path)
    if mixed:
        event["exception"]["values"].append({"type": "RuntimeError"})
    result = []
    started = asyncio.Event()

    async def capture():
        started.set()
        try:
            if manual:
                raise asyncio.CancelledError
            await asyncio.Future()
        except asyncio.CancelledError:
            hint = {"exc_info": sys.exc_info()}
            if thread:
                result.append(
                    await asyncio.to_thread(filter_expected_sentry_events, event, hint)
                )
            else:
                result.append(filter_expected_sentry_events(event, hint))

    async def response(request):
        if background:
            task = asyncio.create_task(capture())
            await started.wait()
            task.cancel()
            await task
        else:
            await capture()

    async def application(scope, receive, send):
        if disconnect:
            await receive()
        task = asyncio.create_task(track_request_task(response)(None))
        if not background and not manual:
            await started.wait()
            task.cancel()
        await task

    async def receive():
        return {"type": "http.disconnect"}

    await track_http_disconnects(application)(
        {"type": "http", "path": path}, receive, None
    )
    return event, result[0]


@pytest.mark.parametrize(
    "path", ["/api/csrf/", "/_allauth/browser/v1/config", "/api/jobs/", "/"]
)
def test_observed_disconnect_drops_request_cancellation_on_any_path(path):
    _, result = asyncio.run(_cancelled_request(path))
    assert result is None


@pytest.mark.parametrize(
    "options",
    [
        {"disconnect": False},
        {"background": True},
        {"mixed": True},
        {"manual": True},
        {"thread": True},
    ],
)
def test_real_task_cancellations_and_mixed_errors_remain_reported(options):
    event, result = asyncio.run(_cancelled_request("/api/csrf/", **options))
    assert result is event


def test_url_or_transaction_alone_is_not_disconnect_evidence():
    event = _event("/api/csrf/")
    event["transaction"] = "/api/csrf/"
    assert filter_expected_sentry_events(event, {}) is event


def test_request_context_is_reset_after_completion():
    asyncio.run(_cancelled_request("/"))
    event = _event("/")
    assert filter_expected_sentry_events(event, {}) is event


def test_concurrent_requests_do_not_share_disconnect_state():
    async def run():
        return await asyncio.gather(
            _cancelled_request("/"), _cancelled_request("/", disconnect=False)
        )

    disconnected, connected = asyncio.run(run())
    assert disconnected[1] is None
    assert connected[1] is connected[0]


def test_synchronous_middleware_is_passthrough():
    def response(request):
        return request

    assert track_request_task(response) is response
