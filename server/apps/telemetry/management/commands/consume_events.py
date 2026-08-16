import asyncio
import json
import logging
import signal

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.telemetry.persist import persist_event

log = logging.getLogger("consumer")
MAX_ATTEMPTS = 3


class Command(BaseCommand):
    help = "Consumes inference events from Kafka and persists them to Postgres."

    def handle(self, *args, **options):
        asyncio.run(self.run())

    async def run(self):
        self.stopping = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stopping.set)

        consumer = AIOKafkaConsumer(
            settings.KAFKA_EVENTS_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=settings.KAFKA_CONSUMER_GROUP,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda v: json.loads(v.decode()),
        )
        dlq = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v, default=str).encode(),
        )
        await consumer.start()
        await dlq.start()
        log.info("consumer started (group=%s)", settings.KAFKA_CONSUMER_GROUP)
        try:
            while not self.stopping.is_set():
                batches = await consumer.getmany(timeout_ms=1000, max_records=500)
                for _, records in batches.items():
                    for record in records:
                        await self.process(record.value, dlq)
                if batches:
                    await consumer.commit()  # manual commit only after persistence
        finally:
            await consumer.stop()
            await dlq.stop()
            log.info("consumer stopped cleanly")

    async def process(self, event: dict, dlq: AIOKafkaProducer):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                await sync_to_async(persist_event)(
                    event["project_id"], event["type"], event["body"]
                )
                return
            except Exception as exc:
                if attempt == MAX_ATTEMPTS:
                    log.error("dead-lettering event %s: %s", event.get("event_id"), exc)
                    await dlq.send_and_wait(
                        settings.KAFKA_DLQ_TOPIC, {"error": str(exc), "event": event}
                    )
                else:
                    await asyncio.sleep(0.2 * attempt)
