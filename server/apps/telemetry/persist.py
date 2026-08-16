"""Idempotent persistence for generation events — shared by the Kafka consumer
and the direct-write fallback. Replaying any event yields the same final row."""

from apps.telemetry.models import InferenceLog
from apps.telemetry.schemas import GenerationEndBody, GenerationStartBody

END_FIELDS = (
    "status", "response_model", "first_chunk_at", "completed_at", "latency_ms", "ttft_ms",
    "input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens", "tokens_estimated",
    "cost_usd", "finish_reasons", "response_preview", "error_type", "error_message",
)  # fmt: skip


def persist_start(project_id: str, body: GenerationStartBody) -> None:
    InferenceLog.objects.bulk_create(
        [InferenceLog(project_id=project_id, **body.dict())], ignore_conflicts=True
    )


def persist_end(project_id: str, body: GenerationEndBody) -> None:
    row = InferenceLog.objects.filter(
        generation_id=body.generation_id, project_id=project_id
    ).first()
    if row is None:
        # End arrived before start (possible under at-least-once redelivery):
        # create a stub; the late start insert will no-op on the unique key.
        row = InferenceLog(
            project_id=project_id,
            generation_id=body.generation_id,
            session_id=body.session_id,
            provider="other",
            request_model=body.response_model or "unknown",
            started_at=body.completed_at or body.first_chunk_at,
        )
    for f in END_FIELDS:
        value = getattr(body, f)
        if value is not None:
            setattr(row, f, value)
    if body.pii_masked:
        row.pii_masked = True
        row.pii_entities_found = sorted(set(row.pii_entities_found) | set(body.pii_entities_found))
    row.raw_metadata = {**row.raw_metadata, **body.raw_metadata}
    row.save()


def persist_event(project_id: str, event_type: str, body_dict: dict) -> None:
    if event_type == "generation-start":
        persist_start(project_id, GenerationStartBody.model_validate(body_dict))
    else:
        persist_end(project_id, GenerationEndBody.model_validate(body_dict))
