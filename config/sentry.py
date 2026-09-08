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
