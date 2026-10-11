import asyncio
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from asgiref.sync import iscoroutinefunction
from django.utils.decorators import sync_and_async_middleware


@dataclass
class _RequestState:
    disconnected: bool = False
    active: bool = True
    task: asyncio.Task | None = None


_http_request = ContextVar("sentry_http_request", default=None)
_INTERACTIVE_COMMANDS = {"shell", "dbshell", "shell_plus"}
_COMMAND_LINE_KEYS = {
    "argv",
    "sysargv",
    "command",
    "commandline",
    "cmdline",
    "cmd",
    "args",
    "arguments",
}


def track_http_disconnects(application):
    async def wrapped(scope, receive, send):
        # A mutable, request-local value lets Django's receive and response tasks
        # share the disconnect signal without sharing it with concurrent requests.
        state = _RequestState()
        token = _http_request.set(state)

        async def tracked_receive():
            message = await receive()
            if message["type"] == "http.disconnect":
                state.disconnected = True
            return message

        try:
            return await application(scope, tracked_receive, send)
        finally:
            state.active = False
            _http_request.reset(token)

    return wrapped


@sync_and_async_middleware
def track_request_task(get_response):
    if not iscoroutinefunction(get_response):
        return get_response

    async def wrapped(request):
        state = _http_request.get()
        if state is not None:
            state.task = asyncio.current_task()
        return await get_response(request)

    return wrapped


def is_expected_client_disconnect_event(event, hint):
    state = _http_request.get()
    if state is None or not state.active or not state.disconnected:
        return False
    values = (event.get("exception") or {}).get("values") or []
    if not values or any(value.get("type") != "CancelledError" for value in values):
        return False
    exc_info = hint.get("exc_info")
    if not exc_info or type(exc_info[1]) is not asyncio.CancelledError:
        return False

    # A URL (even /api/csrf/) is not evidence of a disconnect. Require an
    # observed ASGI http.disconnect AND cancellation of the Django request
    # task, recorded by the outermost middleware. Background tasks can inherit
    # this context but have a different task identity. Mixed exception chains
    # remain reportable so a server bug is not hidden.
    try:
        task = asyncio.current_task()
    except RuntimeError:
        # sync_to_async can copy request context into a thread with no loop.
        return False
    return task is not None and task is state.task and task.cancelling() > 0


def _is_management_command():
    executable = Path(sys.argv[0]) if sys.argv else Path()
    return executable.name in {"manage.py", "django-admin", "django-admin.py"} or (
        executable.name == "__main__.py" and executable.parent.name == "django"
    )


def _scrub_command_line_fields(value):
    if isinstance(value, dict):
        for key in list(value):
            normalized = "".join(char for char in key.lower() if char.isalnum())
            if normalized in _COMMAND_LINE_KEYS:
                del value[key]
            else:
                _scrub_command_line_fields(value[key])
    elif isinstance(value, list):
        for item in value:
            _scrub_command_line_fields(item)


def filter_expected_sentry_events(event, hint):
    # Inspect the process, not event extras: SDK scrubbing may already have
    # replaced argv values. Interactive scripts belong in the operator's terminal.
    if len(sys.argv) > 1 and sys.argv[1] in _INTERACTIVE_COMMANDS:
        return None
    if _is_management_command():
        # Retain real job/migration failures, but never their inline arguments.
        for field in ("extra", "contexts", "breadcrumbs"):
            _scrub_command_line_fields(event.get(field))
    if is_expected_client_disconnect_event(event, hint):
        return None
    return filter_expected_websocket_disconnects(event, hint)


WEBSOCKET_KEEPALIVE_TIMEOUT = "keepalive ping timeout"


def filter_expected_websocket_disconnects(event, hint):
    if _is_handled_websocket_disconnect(event):
        return None

    if _is_handled_websocket_keepalive_timeout(event):
        return None

    return event


_WEBSOCKET_DISCONNECT_TYPES = {"ConnectionClosedError", "ConnectionClosedOK"}


def _is_handled_websocket_disconnect(event):
    if event.get("logger") != "asyncio":
        return False

    exception_values = event.get("exception", {}).get("values", [])
    if not exception_values:
        return False

    has_handled_disconnect = any(
        _is_handled_logging_exception(exception_value)
        and exception_value.get("type") in _WEBSOCKET_DISCONNECT_TYPES
        for exception_value in exception_values
    )
    if not has_handled_disconnect:
        return False

    return all(
        _exception_has_only_disconnect_teardown_frames(exception_value)
        for exception_value in exception_values
    )


def _is_handled_logging_exception(exception_value):
    mechanism = exception_value.get("mechanism") or {}
    return mechanism.get("type") == "logging" and mechanism.get("handled") is True


def _exception_has_only_disconnect_teardown_frames(exception_value):
    frames = exception_value.get("stacktrace", {}).get("frames", [])
    return all(_is_disconnect_teardown_frame(frame) for frame in frames)


def _is_disconnect_teardown_frame(frame):
    module = frame.get("module") or ""
    filename = frame.get("filename") or ""
    return (
        module.startswith(("asyncio.", "websockets."))
        or filename.startswith(("asyncio/", "websockets/"))
        or "/asyncio/" in filename
        or "/websockets/" in filename
    )


def _is_handled_websocket_keepalive_timeout(event):
    if event.get("logger") != "asyncio":
        return False

    exception_values = event.get("exception", {}).get("values", [])
    has_websockets_frame = any(
        _exception_has_websockets_frame(exception_value)
        for exception_value in exception_values
    )
    if not has_websockets_frame:
        return False

    for exception_value in exception_values:
        if not _is_handled_logging_exception(exception_value):
            continue

        if exception_value.get("type") != "ConnectionClosedError":
            continue

        if not _exception_mentions_keepalive_timeout(exception_value):
            continue

        return True

    return False


def _exception_mentions_keepalive_timeout(exception_value):
    text = " ".join(
        str(part)
        for part in (
            exception_value.get("value"),
            exception_value.get("message"),
        )
        if part
    )
    return WEBSOCKET_KEEPALIVE_TIMEOUT in text


def _exception_has_websockets_frame(exception_value):
    frames = exception_value.get("stacktrace", {}).get("frames", [])
    return any(
        (frame.get("module") or "").startswith("websockets.")
        or (frame.get("filename") or "").startswith("websockets/")
        for frame in frames
    )
