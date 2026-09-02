from config.sentry import filter_expected_websocket_disconnects


def _websocket_normal_close_event():
    return {
        "logger": "asyncio",
        "level": "error",
        "exception": {
            "values": [
                {
                    "type": "CancelledError",
                    "value": None,
                    "mechanism": {"type": "logging", "handled": True},
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "websockets/legacy/protocol.py",
                                "module": "websockets.legacy.protocol",
                            }
                        ]
                    },
                },
                {
                    "type": "ConnectionClosedOK",
                    "value": "received 1000 (OK); then sent 1000 (OK)",
                    "mechanism": {"type": "logging", "handled": True},
                    "stacktrace": {"frames": []},
                },
            ]
        },
    }


def test_filter_drops_handled_websocket_normal_close_with_websocket_frame():
    event = _websocket_normal_close_event()

    assert filter_expected_websocket_disconnects(event, {}) is None


def test_filter_drops_handled_websocket_normal_close_with_system_only_frames():
    event = _websocket_normal_close_event()
    event["exception"]["values"][0]["stacktrace"]["frames"] = [
        {"filename": "asyncio/streams.py", "module": "asyncio.streams"}
    ]

    assert filter_expected_websocket_disconnects(event, {}) is None


def test_filter_drops_handled_websocket_keepalive_timeout():
    event = _websocket_normal_close_event()
    event["exception"]["values"][0]["stacktrace"]["frames"] = [
        {"filename": "asyncio/streams.py", "module": "asyncio.streams"}
    ]
    event["exception"]["values"][1]["type"] = "ConnectionClosedError"
    event["exception"]["values"][1]["value"] = "keepalive ping timeout"

    assert filter_expected_websocket_disconnects(event, {}) is None


def test_filter_keeps_unhandled_websocket_normal_close():
    event = _websocket_normal_close_event()
    event["exception"]["values"][1]["mechanism"]["handled"] = False

    assert filter_expected_websocket_disconnects(event, {}) == event


def test_filter_keeps_websocket_disconnects_with_application_frames():
    event = _websocket_normal_close_event()
    event["exception"]["values"][0]["stacktrace"]["frames"] = [
        {"filename": "config/asgi.py", "module": "config.asgi"}
    ]

    assert filter_expected_websocket_disconnects(event, {}) == event


def test_filter_keeps_non_asyncio_websocket_disconnect_events():
    event = _websocket_normal_close_event()
    event["logger"] = "django.request"

    assert filter_expected_websocket_disconnects(event, {}) == event
