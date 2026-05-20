import asyncio
import os

import structlog
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
from django.conf import settings

if not settings.configured:
    django.setup()

from taskiq_redis import ListQueueBroker

logger = structlog.get_logger(__name__)

broker = ListQueueBroker(
    url=settings.BROKER_URL,
)

scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker)],
)


def enqueue_task(task, *args, **kwargs) -> None:
    async def _enqueue() -> None:
        producer_broker = ListQueueBroker(url=settings.BROKER_URL)
        await producer_broker.startup()
        try:
            await task.kicker().with_broker(producer_broker).kiq(*args, **kwargs)
        finally:
            await producer_broker.shutdown()

    asyncio.run(_enqueue())
