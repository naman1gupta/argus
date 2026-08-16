import asyncio

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Idempotently creates the Kafka topics (events + DLQ)."

    def handle(self, *args, **options):
        asyncio.run(self.run())

    async def run(self):
        admin = AIOKafkaAdminClient(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
        await admin.start()
        try:
            topics = [
                NewTopic(
                    name=settings.KAFKA_EVENTS_TOPIC,
                    num_partitions=settings.KAFKA_EVENTS_PARTITIONS,
                    replication_factor=1,
                ),
                NewTopic(name=settings.KAFKA_DLQ_TOPIC, num_partitions=1, replication_factor=1),
            ]
            for topic in topics:
                try:
                    await admin.create_topics([topic])
                    self.stdout.write(f"created topic {topic.name}")
                except TopicAlreadyExistsError:
                    self.stdout.write(f"topic {topic.name} exists")
        finally:
            await admin.close()
