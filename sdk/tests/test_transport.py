import time

import pytest

from argus.transport import Transport


class Resp:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""


@pytest.fixture
def transport(monkeypatch):
    t = Transport("http://collector.invalid/api/v1", "k", flush_at=5, flush_interval=0.05)
    t.batches = []
    monkeypatch.setattr(t, "_post", lambda batch: (t.batches.append(list(batch)), Resp(202))[1])
    yield t
    t.shutdown()


def test_batches_and_flush(transport):
    for i in range(12):
        transport.enqueue({"n": i})
    transport.flush(timeout=3)
    sent = [e for b in transport.batches for e in b]
    assert len(sent) == 12
    assert all(len(b) <= 5 for b in transport.batches)


def test_fail_open_when_endpoint_down():
    t = Transport("http://127.0.0.1:1/api/v1", "k", flush_at=2, flush_interval=0.05, timeout=0.2)
    start = time.monotonic()
    for i in range(20):
        t.enqueue({"n": i})
    assert time.monotonic() - start < 0.1  # enqueue never blocks on network
    t.flush(timeout=1)  # must not raise


def test_drop_oldest_on_overflow(monkeypatch):
    t = Transport("http://collector.invalid", "k", flush_at=1000, flush_interval=999, max_queue=10)
    for i in range(25):
        t.enqueue({"n": i})
    assert t.dropped == 15
    assert len(t._queue) == 10 and t._queue[0]["n"] == 15


def test_retry_then_success(monkeypatch):
    t = Transport("http://collector.invalid", "k", flush_at=1, flush_interval=0.05)
    calls = []

    def post(batch):
        calls.append(1)
        return Resp(500 if len(calls) < 3 else 202)

    monkeypatch.setattr(t, "_post", post)
    monkeypatch.setattr("argus.transport.RETRY_BACKOFF", (0.01, 0.01, 0.01))
    t.enqueue({"n": 1})
    t.flush(timeout=3)
    assert len(calls) == 3
