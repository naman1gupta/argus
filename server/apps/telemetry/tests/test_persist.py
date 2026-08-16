from datetime import UTC, datetime

import pytest

from apps.telemetry.models import InferenceLog
from apps.telemetry.persist import persist_event

START = {
    "generation_id": "gen_9",
    "session_id": "sess_9",
    "provider": "gcp.gemini",
    "request_model": "gemini-2.5-flash",
    "started_at": datetime(2026, 8, 16, 10, 0, tzinfo=UTC),
    "prompt_preview": "hello <EMAIL>",
    "pii_masked": True,
    "pii_entities_found": ["EMAIL"],
}
END = {
    "generation_id": "gen_9",
    "status": "success",
    "completed_at": datetime(2026, 8, 16, 10, 0, 2, tzinfo=UTC),
    "latency_ms": 2000.0,
    "ttft_ms": 400.0,
    "input_tokens": 10,
    "output_tokens": 20,
    "cost_usd": 0.0001,
    "finish_reasons": ["stop"],
    "pii_masked": True,
    "pii_entities_found": ["PHONE_IN"],
}


@pytest.mark.django_db
def test_two_phase_write_and_merge(project):
    persist_event(project.id, "generation-start", START)
    row = InferenceLog.objects.get(generation_id="gen_9")
    assert row.status == "pending"

    persist_event(project.id, "generation-end", END)
    row.refresh_from_db()
    assert row.status == "success" and row.output_tokens == 20
    assert row.prompt_preview == "hello <EMAIL>"  # start data survives the end merge
    assert row.pii_entities_found == ["EMAIL", "PHONE_IN"]


@pytest.mark.django_db
def test_replay_is_idempotent(project):
    for _ in range(3):
        persist_event(project.id, "generation-start", START)
        persist_event(project.id, "generation-end", END)
    assert InferenceLog.objects.filter(generation_id="gen_9").count() == 1
    assert InferenceLog.objects.get(generation_id="gen_9").status == "success"


@pytest.mark.django_db
def test_end_before_start_creates_stub_then_start_noop(project):
    persist_event(project.id, "generation-end", END)
    row = InferenceLog.objects.get(generation_id="gen_9")
    assert row.status == "success" and row.request_model == "unknown"

    persist_event(project.id, "generation-start", START)
    assert InferenceLog.objects.filter(generation_id="gen_9").count() == 1


@pytest.mark.django_db
def test_end_without_timestamps_still_persists(project):
    """A partial end event (no completed_at/first_chunk_at) must not violate
    NOT NULL and get dead-lettered — it falls back to ingestion time."""
    minimal_end = {"generation_id": "gen_partial", "session_id": "s", "status": "error",
                   "error_type": "ClientAbort"}
    persist_event(project.id, "generation-end", minimal_end)
    row = InferenceLog.objects.get(generation_id="gen_partial")
    assert row.status == "error" and row.started_at is not None
