import json

import pytest

URL = "/api/v1/logs"


def post(client, key, batch):
    return client.post(
        URL,
        data=json.dumps({"batch": batch}),
        content_type="application/json",
        headers={"Authorization": f"Bearer {key}"},
    )


def start_event(gen="gen_1", **over):
    body = {
        "generation_id": gen,
        "session_id": "sess_1",
        "provider": "anthropic",
        "request_model": "claude-sonnet-4-5",
        "started_at": "2026-08-16T10:00:00Z",
        "is_streaming": True,
        **over,
    }
    return {"id": f"evt_{gen}_start", "timestamp": "2026-08-16T10:00:00Z",
            "type": "generation-start", "body": body}  # fmt: skip


def end_event(gen="gen_1", **over):
    body = {
        "generation_id": gen,
        "session_id": "sess_1",
        "status": "success",
        "latency_ms": 1500.0,
        "input_tokens": 100,
        "output_tokens": 50,
        **over,
    }
    return {"id": f"evt_{gen}_end", "timestamp": "2026-08-16T10:00:02Z",
            "type": "generation-end", "body": body}  # fmt: skip


@pytest.mark.django_db
def test_valid_batch_is_queued(client, project, fake_bus):
    resp = post(client, project._raw_key, [start_event(), end_event()])
    assert resp.status_code == 202
    data = resp.json()
    assert data["accepted"] == 2 and data["rejected"] == 0 and data["mode"] == "queued"
    assert len(fake_bus.sent) == 2
    assert fake_bus.sent[0][0] == "sess_1"  # partition key = session id


@pytest.mark.django_db
def test_mixed_batch_returns_207_with_per_item_errors(client, project, fake_bus):
    bad = start_event(gen="gen_bad")
    bad["body"]["provider"] = "not-a-provider"
    resp = post(client, project._raw_key, [start_event(), bad])
    assert resp.status_code == 207
    data = resp.json()
    assert data["accepted"] == 1 and data["rejected"] == 1
    statuses = {r["id"]: r["status"] for r in data["results"]}
    assert statuses["evt_gen_1_start"] == 201 and statuses["evt_gen_bad_start"] == 400
    assert len(fake_bus.sent) == 1  # invalid event never reaches Kafka


@pytest.mark.django_db
def test_negative_latency_rejected(client, project, fake_bus):
    resp = post(client, project._raw_key, [end_event(latency_ms=-5)])
    assert resp.status_code == 207
    assert resp.json()["rejected"] == 1


@pytest.mark.django_db
def test_bad_key_is_401(client, project, fake_bus):
    resp = post(client, "argus_sk_wrong", [start_event()])
    assert resp.status_code == 401


@pytest.mark.django_db
def test_kafka_outage_falls_back_to_direct_write(client, project, fake_bus):
    from apps.telemetry.models import InferenceLog

    fake_bus.available = False
    resp = post(client, project._raw_key, [start_event(), end_event()])
    assert resp.status_code == 202
    assert resp.json()["mode"] == "direct"
    row = InferenceLog.objects.get(generation_id="gen_1")
    assert row.status == "success" and row.input_tokens == 100


@pytest.mark.django_db
def test_rate_limit_returns_429(client, project, fake_bus, settings, monkeypatch):
    from apps.telemetry import api as ingest_api
    from apps.telemetry.ratelimit import SlidingWindowLimiter

    monkeypatch.setattr(ingest_api, "ingest_limiter", SlidingWindowLimiter(2, 60))
    for _ in range(2):
        assert post(client, project._raw_key, [start_event()]).status_code == 202
    resp = post(client, project._raw_key, [start_event()])
    assert resp.status_code == 429
    assert resp.json()["retry_after"] > 0
