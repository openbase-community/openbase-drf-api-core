from config.sentry import filter_expected_websocket_disconnects


def _websocket_keepalive_event():
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
                    "type": "ConnectionClosedError",
                    "value": "sent 1011 (internal error) keepalive ping timeout; no close frame received",
                    "mechanism": {"type": "logging", "handled": True},
                    "stacktrace": {"frames": []},
                },
            ]
        },
    }


def test_filter_drops_handled_websocket_keepalive_timeout():
    event = _websocket_keepalive_event()

    assert filter_expected_websocket_disconnects(event, {}) is None


def test_filter_keeps_unhandled_websocket_keepalive_timeout():
    event = _websocket_keepalive_event()
    event["exception"]["values"][1]["mechanism"]["handled"] = False

    assert filter_expected_websocket_disconnects(event, {}) == event


def test_filter_keeps_non_websocket_connection_closed_errors():
    event = _websocket_keepalive_event()
    event["exception"]["values"][0]["stacktrace"]["frames"] = [
        {"filename": "asyncio/streams.py", "module": "asyncio.streams"}
    ]

    assert filter_expected_websocket_disconnects(event, {}) == event
