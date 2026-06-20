from __future__ import annotations

import asyncio

from channels_redis.core import create_pool

from config.settings import _redis_channel_layer_host


def test_channel_layer_redis_host_omits_ssl_kwargs_for_plain_redis():
    assert _redis_channel_layer_host(
        "redis://redis.internal:6379/0",
        debug=False,
        uses_tls=False,
    ) == "redis://redis.internal:6379/0"


def test_plain_redis_channel_layer_host_creates_pool_without_ssl_kwargs():
    host = _redis_channel_layer_host(
        "redis://redis.internal:6379/0",
        debug=False,
        uses_tls=False,
    )

    pool = create_pool({"address": host})

    asyncio.run(pool.disconnect())


def test_channel_layer_redis_host_adds_ssl_kwargs_only_for_rediss():
    assert _redis_channel_layer_host(
        "rediss://redis.internal:6379/0?ssl_cert_reqs=none",
        debug=False,
        uses_tls=True,
    ) == {
        "address": "rediss://redis.internal:6379/0?ssl_cert_reqs=none",
        "ssl_cert_reqs": None,
    }
