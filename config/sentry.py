WEBSOCKET_KEEPALIVE_TIMEOUT = "keepalive ping timeout"


def filter_expected_websocket_disconnects(event, hint):
    if _is_handled_websocket_keepalive_timeout(event):
        return None

    return event


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
        mechanism = exception_value.get("mechanism") or {}
        if mechanism.get("type") != "logging" or mechanism.get("handled") is not True:
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
