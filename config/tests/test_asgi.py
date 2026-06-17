from __future__ import annotations

from asgiref.sync import async_to_sync

from config.asgi import AllowMissingOriginValidator


async def _ok_app(scope, receive, send):
    await send({"type": "websocket.accept"})


async def _message_for_scope(scope):
    messages = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        messages.append(message)

    await AllowMissingOriginValidator(_ok_app)(scope, receive, send)
    return messages[0]


def test_websocket_validator_allows_non_browser_clients_without_origin():
    message = async_to_sync(_message_for_scope)(
        {
            "type": "websocket",
            "path": "/api/openbase/audio/cartesia/tts/websocket/",
            "headers": [(b"host", b"app.openbase.cloud")],
        }
    )

    assert message["type"] == "websocket.accept"


def test_websocket_validator_detects_browser_origin():
    assert AllowMissingOriginValidator.has_origin(
        {
            "type": "websocket",
            "path": "/api/openbase/audio/cartesia/tts/websocket/",
            "headers": [
                (b"host", b"app.openbase.cloud"),
                (b"origin", b"https://evil.example"),
            ],
        }
    )
