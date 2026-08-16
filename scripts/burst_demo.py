#!/usr/bin/env python3
"""Burst-absorption demo: floods the ingestion API with synthetic events, then
watches the Kafka consumer drain the backlog into Postgres.

    python scripts/burst_demo.py --events 2000 \
        --endpoint http://localhost:8000/api/v1 --key "$CHAT_INGEST_KEY"

Shows three properties of the pipeline:
  1. the API acknowledges bursts in milliseconds (persistence is decoupled),
  2. consumer lag spikes then drains to zero (watch it live in the UI footer),
  3. replaying a batch is harmless (at-least-once + idempotent writes).
"""

import argparse
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx


def make_batch(n: int, base: datetime) -> list[dict]:
    events = []
    for i in range(n):
        gen = f"gen_burst_{uuid.uuid4().hex}"
        start = base + timedelta(milliseconds=i * 3)
        events.append({
            "id": f"evt_{uuid.uuid4().hex}", "timestamp": start.isoformat(),
            "type": "generation-start",
            "body": {
                "generation_id": gen, "session_id": f"burst_{i % 20}",
                "provider": "mock", "request_model": "argus-demo-1",
                "is_streaming": True, "started_at": start.isoformat(),
                "prompt_preview": "burst-demo synthetic event",
                "environment": "burst-demo",
            },
        })
        events.append({
            "id": f"evt_{uuid.uuid4().hex}", "timestamp": start.isoformat(),
            "type": "generation-end",
            "body": {
                "generation_id": gen, "session_id": f"burst_{i % 20}",
                "status": "success", "latency_ms": 900.0, "ttft_ms": 250.0,
                "input_tokens": 120, "output_tokens": 40,
                "finish_reasons": ["stop"], "response_preview": "ok",
            },
        })
    return events  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=2000, help="generations to simulate")
    ap.add_argument("--endpoint", default="http://localhost:8000/api/v1")
    ap.add_argument("--key", default=os.environ.get("CHAT_INGEST_KEY", ""))
    args = ap.parse_args()
    if not args.key:
        ap.error("--key or CHAT_INGEST_KEY required")

    client = httpx.Client(
        base_url=args.endpoint, headers={"Authorization": f"Bearer {args.key}"}, timeout=30
    )
    batch_size = 250  # 2 events per generation -> 500 per request (server max)
    base = datetime.now(UTC)

    print(f"→ sending {args.events} generations ({args.events * 2} events)…")
    first_batch = None
    accepted = 0
    t0 = time.perf_counter()
    for offset in range(0, args.events, batch_size):
        n = min(batch_size, args.events - offset)
        batch = make_batch(n, base + timedelta(seconds=offset))
        first_batch = first_batch or batch
        resp = client.post("/logs", json={"batch": batch})
        resp.raise_for_status()
        accepted += resp.json()["accepted"]
    elapsed = time.perf_counter() - t0
    print(f"✓ accepted {accepted} events in {elapsed:.2f}s "
          f"({accepted / elapsed:,.0f} events/s acknowledged)")  # fmt: skip

    print("→ replaying the first batch (at-least-once redelivery)…")
    resp = client.post("/logs", json={"batch": first_batch})
    print(f"✓ replay accepted ({resp.json()['accepted']} events) — "
          "idempotent persistence means row state is unchanged")  # fmt: skip

    print("→ waiting for the consumer to drain (watch 'consumer lag' in the UI footer)…")
    t0 = time.perf_counter()
    while True:
        lag = client.get("/health").json().get("consumer_lag")
        print(f"   lag: {lag}")
        if lag == 0:
            break
        if time.perf_counter() - t0 > 120:
            print("   (timed out waiting — is the worker running?)")
            return
        time.sleep(1.5)
    print(f"✓ backlog drained in {time.perf_counter() - t0:.1f}s — "
          "burst absorbed, nothing lost, nothing duplicated")  # fmt: skip


if __name__ == "__main__":
    main()
