"""Background transport. Iron rule: never raises, never blocks the host app.

Bounded queue (drop-oldest on overflow), daemon flusher thread, batches of
`flush_at` or every `flush_interval` seconds, retries with backoff, atexit
flush. Short-lived scripts should call argus.flush() before exit."""

import atexit
import logging
import threading
import time
from collections import deque

import httpx

log = logging.getLogger("argus")

RETRY_BACKOFF = (0.5, 1.0, 2.0)


class Transport:
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        flush_at: int = 20,
        flush_interval: float = 1.0,
        max_queue: int = 10_000,
        timeout: float = 5.0,
    ):
        self.url = endpoint.rstrip("/") + "/logs"
        self.flush_at = flush_at
        self.flush_interval = flush_interval
        self.max_queue = max_queue
        self.dropped = 0
        self._queue: deque[dict] = deque()
        self._cond = threading.Condition()
        self._inflight = False
        self._stopped = False
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout
        )
        self._thread = threading.Thread(target=self._run, name="argus-flusher", daemon=True)
        self._thread.start()
        atexit.register(self.shutdown)

    def enqueue(self, event: dict) -> None:
        try:
            with self._cond:
                if len(self._queue) >= self.max_queue:
                    self._queue.popleft()
                    self.dropped += 1
                self._queue.append(event)
                if len(self._queue) >= self.flush_at:
                    self._cond.notify()
        except Exception:
            pass

    def _run(self) -> None:
        while True:
            with self._cond:
                if not self._queue and self._stopped:
                    return
                if len(self._queue) < self.flush_at and not self._stopped:
                    self._cond.wait(timeout=self.flush_interval)
                batch = [self._queue.popleft() for _ in range(min(len(self._queue), self.flush_at))]
                self._inflight = bool(batch)
            if batch:
                self._send(batch)
                with self._cond:
                    self._inflight = False
                    self._cond.notify_all()

    def _send(self, batch: list[dict]) -> None:
        for backoff in (*RETRY_BACKOFF, None):
            try:
                resp = self._post(batch)
                if resp.status_code in (202, 207):
                    if resp.status_code == 207:
                        log.warning("argus: some events rejected: %s", resp.text[:300])
                    return
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    log.warning("argus: batch rejected (%s), not retrying", resp.status_code)
                    return
            except Exception as exc:
                if backoff is None:
                    log.warning("argus: dropping batch of %d after retries: %s", len(batch), exc)
                    return
            if backoff is None:
                return
            time.sleep(backoff)

    def _post(self, batch: list[dict]) -> httpx.Response:
        return self._client.post(self.url, json={"batch": batch})

    def flush(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        with self._cond:
            while (self._queue or self._inflight) and time.monotonic() < deadline:
                self._cond.notify()
                self._cond.wait(timeout=0.05)

    def shutdown(self) -> None:
        try:
            self.flush(timeout=3.0)
            with self._cond:
                self._stopped = True
                self._cond.notify_all()
        except Exception:
            pass
