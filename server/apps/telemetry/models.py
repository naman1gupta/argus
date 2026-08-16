from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import BrinIndex, GinIndex
from django.db import models

from apps.chat.models import new_ulid


class InferenceLog(models.Model):
    """One LLM inference call.

    Column names follow the OpenTelemetry GenAI semantic conventions
    (gen_ai.provider.name, gen_ai.usage.input_tokens, time_to_first_chunk, ...)
    so exported data maps onto the industry standard without translation.

    Rows are written by the Kafka consumer in two phases: a `generation-start`
    event inserts a PENDING row the moment a call begins; the matching
    `generation-end` event fills in usage, latency, and final status.
    `generation_id` is the entity identity and idempotency key — replaying
    either event is harmless.
    """

    class Provider(models.TextChoices):
        ANTHROPIC = "anthropic"
        OPENAI = "openai"
        GEMINI = "gcp.gemini"
        GROQ = "groq"
        MOCK = "mock"
        OTHER = "other"

    class Status(models.TextChoices):
        PENDING = "pending"
        SUCCESS = "success"
        ERROR = "error"
        ABORTED = "aborted"

    id = models.CharField(primary_key=True, max_length=26, default=new_ulid, editable=False)
    generation_id = models.CharField(max_length=64, unique=True)
    # Denormalized (no FKs): telemetry must ingest sessions/users the chat app
    # has never seen — the SDK is usable by any external application.
    session_id = models.CharField(max_length=200, blank=True, default="")
    trace_id = models.CharField(max_length=64, blank=True, default="")
    project_id = models.CharField(max_length=26, db_index=True)
    end_user_id = models.CharField(max_length=128, blank=True, default="")

    provider = models.CharField(max_length=32, choices=Provider.choices)
    request_model = models.CharField(max_length=100)
    response_model = models.CharField(max_length=100, blank=True, default="")
    operation = models.CharField(max_length=32, default="chat")
    is_streaming = models.BooleanField(default=False)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    error_type = models.CharField(max_length=100, blank=True, default="")
    error_message = models.TextField(blank=True, default="")

    started_at = models.DateTimeField()
    first_chunk_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    latency_ms = models.FloatField(null=True, blank=True)
    ttft_ms = models.FloatField(null=True, blank=True)

    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    cached_tokens = models.IntegerField(null=True, blank=True)
    reasoning_tokens = models.IntegerField(null=True, blank=True)
    # True when usage was estimated client-side (e.g. stream aborted before
    # the provider's final usage frame arrived).
    tokens_estimated = models.BooleanField(default=False)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    finish_reasons = ArrayField(models.CharField(max_length=40), default=list, blank=True)

    request_params = models.JSONField(default=dict, blank=True)
    prompt_preview = models.TextField(blank=True, default="")
    response_preview = models.TextField(blank=True, default="")
    pii_masked = models.BooleanField(default=False)
    pii_entities_found = ArrayField(models.CharField(max_length=40), default=list, blank=True)

    environment = models.CharField(max_length=40, default="default")
    sdk_release = models.CharField(max_length=40, blank=True, default="")
    raw_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["session_id", "started_at"], name="inflog_session_time"),
            models.Index(
                fields=["provider", "request_model", "started_at"], name="inflog_model_time"
            ),
            models.Index(fields=["started_at"], name="inflog_time"),
            models.Index(
                fields=["started_at"],
                name="inflog_errors_time",
                condition=models.Q(status="error"),
            ),
            # Append-only, time-correlated column: BRIN stores per-block ranges
            # instead of per-row pointers — a fraction of a B-tree's size for the
            # 7/30-day range scans the dashboards run.
            BrinIndex(fields=["started_at"], name="inflog_started_brin", pages_per_range=64),
            GinIndex(
                fields=["raw_metadata"], name="inflog_meta_gin", opclasses=["jsonb_path_ops"]
            ),
        ]
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.generation_id} {self.provider}/{self.request_model} [{self.status}]"
