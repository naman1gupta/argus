import asyncio

import pytest

from apps.telemetry.management.commands.consume_events import Command


class FlakyClient:
    """Refuses the first N connections, the way a broker that is still booting does."""

    def __init__(self, failures):
        self.failures, self.calls = failures, 0

    async def start(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("kafka not ready")


async def test_worker_waits_for_a_broker_that_is_still_booting():
    cmd = Command()
    cmd.stopping = asyncio.Event()
    client = FlakyClient(failures=3)

    await cmd.start_when_ready(client, attempts=10, base_delay=0)

    assert client.calls == 4  # three refusals, then connected — no crash-loop


async def test_worker_gives_up_after_the_attempt_budget():
    cmd = Command()
    cmd.stopping = asyncio.Event()
    client = FlakyClient(failures=99)

    with pytest.raises(ConnectionError):
        await cmd.start_when_ready(client, attempts=3, base_delay=0)
    assert client.calls == 3
