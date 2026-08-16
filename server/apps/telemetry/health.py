import contextlib
import logging

from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.structs import TopicPartition
from django.conf import settings

log = logging.getLogger(__name__)


async def consumer_lag() -> int | None:
    """Sum of (end offset - committed offset) across the events topic; None if unavailable."""
    consumer = AIOKafkaConsumer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS, request_timeout_ms=3000
    )
    admin = AIOKafkaAdminClient(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS, request_timeout_ms=3000
    )
    try:
        await consumer.start()
        await admin.start()
        partitions = consumer.partitions_for_topic(settings.KAFKA_EVENTS_TOPIC) or set()
        tps = [TopicPartition(settings.KAFKA_EVENTS_TOPIC, p) for p in partitions]
        if not tps:
            return 0
        end = await consumer.end_offsets(tps)
        committed = await admin.list_consumer_group_offsets(
            settings.KAFKA_CONSUMER_GROUP, partitions=tps
        )
        lag = 0
        for tp in tps:
            meta = committed.get(tp)
            if meta is not None and meta.offset >= 0:
                lag += max(end[tp] - meta.offset, 0)
        return lag
    except Exception as exc:
        log.warning("consumer lag unavailable: %s", exc)
        return None
    finally:
        with contextlib.suppress(Exception):
            await consumer.stop()
        with contextlib.suppress(Exception):
            await admin.close()
