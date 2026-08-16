from datetime import datetime
from typing import Literal

from ninja import Schema
from pydantic import Field, field_validator

PREVIEW_MAX = 2000


class GenerationStartBody(Schema):
    generation_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(default="", max_length=200)
    trace_id: str = Field(default="", max_length=64)
    end_user_id: str = Field(default="", max_length=128)
    provider: Literal["anthropic", "openai", "gcp.gemini", "groq", "mock", "other"]
    request_model: str = Field(min_length=1, max_length=100)
    operation: str = Field(default="chat", max_length=32)
    is_streaming: bool = False
    started_at: datetime
    request_params: dict = {}
    prompt_preview: str = Field(default="", max_length=PREVIEW_MAX)
    pii_masked: bool = False
    pii_entities_found: list[str] = []
    environment: str = Field(default="default", max_length=40)
    sdk_release: str = Field(default="", max_length=40)
    raw_metadata: dict = {}


class GenerationEndBody(Schema):
    generation_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(default="", max_length=200)  # keeps partition affinity with start
    status: Literal["success", "error", "aborted"]
    response_model: str = Field(default="", max_length=100)
    first_chunk_at: datetime | None = None
    completed_at: datetime | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    ttft_ms: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    tokens_estimated: bool = False
    cost_usd: float | None = Field(default=None, ge=0)
    finish_reasons: list[str] = []
    response_preview: str = Field(default="", max_length=PREVIEW_MAX)
    pii_masked: bool = False
    pii_entities_found: list[str] = []
    error_type: str = Field(default="", max_length=100)
    error_message: str = Field(default="", max_length=4000)
    raw_metadata: dict = {}

    @field_validator("finish_reasons")
    @classmethod
    def cap_reasons(cls, v):
        return v[:8]


class IngestEvent(Schema):
    id: str = Field(min_length=1, max_length=64)  # envelope id — idempotency/dedup
    timestamp: datetime
    type: Literal["generation-start", "generation-end"]
    body: dict

    def parsed_body(self) -> GenerationStartBody | GenerationEndBody:
        cls = GenerationStartBody if self.type == "generation-start" else GenerationEndBody
        return cls.model_validate(self.body)


class IngestResultItem(Schema):
    id: str
    status: int
    error: str | None = None


class IngestResponse(Schema):
    accepted: int
    rejected: int
    results: list[IngestResultItem]
    mode: Literal["queued", "direct"] = "queued"
