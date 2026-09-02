def filter_expected_websocket_disconnects(event, hint):
    if _is_handled_websocket_normal_close(event):
        return None

    return event


def _is_handled_websocket_normal_close(event):
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

        if exception_value.get("type") == "ConnectionClosedOK":
            return True

    return False


def _exception_has_websockets_frame(exception_value):
    frames = exception_value.get("stacktrace", {}).get("frames", [])
    return any(
        (frame.get("module") or "").startswith("websockets.")
        or (frame.get("filename") or "").startswith("websockets/")
        for frame in frames
    )
