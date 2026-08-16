"""Kafka access for the api process: lazy singleton producer with fail-open send."""

import json
import logging

from aiokafka import AIOKafkaProducer
from django.conf import settings

log = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        p = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v, default=str).encode(),
            key_serializer=lambda k: k.encode() if k else None,
            linger_ms=5,
            request_timeout_ms=5000,
        )
        await p.start()
        _producer = p
    return _producer


async def send_event(key: str, event: dict) -> bool:
    """Returns False when Kafka is unavailable so callers can fall back to a direct write."""
    return await send_many([(key, event)])


async def send_many(items: list[tuple[str, dict]]) -> bool:
    """Produces a whole batch, awaiting acks once at the end (not per event).
    All-or-nothing: on failure the caller falls back to direct writes."""
    global _producer
    try:
        producer = await get_producer()
        futures = [
            await producer.send(settings.KAFKA_EVENTS_TOPIC, value=event, key=key)
            for key, event in items
        ]
        for fut in futures:
            await fut
        return True
    except Exception as exc:
        _producer = None
        log.warning("kafka unavailable, falling back to direct write: %s", exc)
        return False
