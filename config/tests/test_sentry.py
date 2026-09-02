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


def test_filter_drops_handled_websocket_normal_close():
    event = _websocket_normal_close_event()

    assert filter_expected_websocket_disconnects(event, {}) is None


def test_filter_keeps_unhandled_websocket_normal_close():
    event = _websocket_normal_close_event()
    event["exception"]["values"][1]["mechanism"]["handled"] = False

    assert filter_expected_websocket_disconnects(event, {}) == event


def test_filter_keeps_non_websocket_connection_closed_ok_events():
    event = _websocket_normal_close_event()
    event["exception"]["values"][0]["stacktrace"]["frames"] = [
        {"filename": "asyncio/streams.py", "module": "asyncio.streams"}
    ]

    assert filter_expected_websocket_disconnects(event, {}) == event


def test_filter_keeps_websocket_connection_closed_error_events():
    event = _websocket_normal_close_event()
    event["exception"]["values"][1]["type"] = "ConnectionClosedError"

    assert filter_expected_websocket_disconnects(event, {}) == event
