import contextlib
import logging
import random
import time
from datetime import UTC, datetime

from ulid import ULID

from argus import masking, pricing
from argus.transport import Transport

log = logging.getLogger("argus")

PREVIEW_LIMIT = 800


def _now() -> datetime:
    return datetime.now(UTC)


class ArgusClient:
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        session_id: str | None = None,
        end_user_id: str = "",
        environment: str = "default",
        sample_rate: float = 1.0,
        log_content: bool = True,
        mask=masking.mask,
        flush_at: int = 20,
        flush_interval: float = 1.0,
        disabled: bool = False,
    ):
        self.session_id = session_id or ""
        self.end_user_id = end_user_id
        self.environment = environment
        self.sample_rate = sample_rate
        self.log_content = log_content
        self.mask = mask
        self.disabled = disabled
        self.transport = (
            None
            if disabled
            else Transport(endpoint, api_key, flush_at=flush_at, flush_interval=flush_interval)
        )

    def _emit(self, event_type: str, body: dict) -> None:
        if self.transport is None:
            return
        with contextlib.suppress(Exception):
            self.transport.enqueue(
                {
                    "id": str(ULID()),
                    "timestamp": _now().isoformat(),
                    "type": event_type,
                    "body": body,
                }
            )

    def _preview(self, text: str) -> tuple[str, bool, list[str]]:
        if not self.log_content or not text:
            return "", False, []
        try:
            masked, entities = self.mask(text)
        except Exception:
            return "", False, []
        return masked[:PREVIEW_LIMIT], bool(entities), entities

    def generation(
        self,
        provider: str,
        model: str,
        *,
        operation: str = "chat",
        is_streaming: bool = False,
        session_id: str | None = None,
        end_user_id: str | None = None,
        prompt: str = "",
        request_params: dict | None = None,
        metadata: dict | None = None,
    ) -> "Generation":
        return Generation(
            self,
            provider=provider,
            model=model,
            operation=operation,
            is_streaming=is_streaming,
            session_id=self.session_id if session_id is None else session_id,
            end_user_id=self.end_user_id if end_user_id is None else end_user_id,
            prompt=prompt,
            request_params=request_params or {},
            metadata=metadata or {},
        )

    def flush(self, timeout: float = 10.0) -> None:
        if self.transport:
            self.transport.flush(timeout)


class Generation:
    """Manual instrumentation handle; the client wrappers use it internally.

    with client.generation("anthropic", "claude-sonnet-4-5", prompt=text) as gen:
        ... call the provider ...
        gen.first_chunk()            # at first content delta (streaming)
        gen.end(status="success", input_tokens=..., output_tokens=..., response=text)
    Exiting on an exception records status="error" automatically.
    """

    def __init__(self, client: ArgusClient, *, provider: str, model: str, **ctx):
        self.client = client
        self.provider = provider
        self.model = model
        self.ctx = ctx
        self.generation_id = "gen_" + str(ULID())
        self.sampled = random.random() < client.sample_rate
        self._t0 = time.monotonic()
        self._started_at = _now()
        self._first_chunk_at: datetime | None = None
        self._ttft_ms: float | None = None
        self._ended = False

        preview, masked, entities = client._preview(ctx.get("prompt", ""))
        if self.sampled:
            client._emit(
                "generation-start",
                {
                    "generation_id": self.generation_id,
                    "session_id": ctx["session_id"],
                    "end_user_id": ctx["end_user_id"],
                    "provider": provider,
                    "request_model": model,
                    "operation": ctx["operation"],
                    "is_streaming": ctx["is_streaming"],
                    "started_at": self._started_at.isoformat(),
                    "request_params": ctx["request_params"],
                    "prompt_preview": preview,
                    "pii_masked": masked,
                    "pii_entities_found": entities,
                    "environment": client.environment,
                    "sdk_release": _sdk_version(),
                    "raw_metadata": ctx["metadata"],
                },
            )

    def first_chunk(self) -> None:
        if self._first_chunk_at is None:
            self._first_chunk_at = _now()
            self._ttft_ms = round((time.monotonic() - self._t0) * 1000, 1)

    def end(
        self,
        status: str = "success",
        *,
        response_model: str = "",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cached_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        tokens_estimated: bool = False,
        finish_reasons: list[str] | None = None,
        response: str = "",
        error: BaseException | None = None,
        metadata: dict | None = None,
    ) -> None:
        if self._ended or not self.sampled:
            self._ended = True
            return
        self._ended = True
        preview, masked, entities = self.client._preview(response)
        cost = pricing.estimate_cost(
            self.provider, response_model or self.model, input_tokens, output_tokens, cached_tokens
        )
        self.client._emit(
            "generation-end",
            {
                "generation_id": self.generation_id,
                "session_id": self.ctx["session_id"],
                "status": status,
                "response_model": response_model,
                "first_chunk_at": (
                    self._first_chunk_at.isoformat() if self._first_chunk_at else None
                ),
                "completed_at": _now().isoformat(),
                "latency_ms": round((time.monotonic() - self._t0) * 1000, 1),
                "ttft_ms": self._ttft_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": cached_tokens,
                "reasoning_tokens": reasoning_tokens,
                "tokens_estimated": tokens_estimated,
                "cost_usd": cost,
                "finish_reasons": finish_reasons or [],
                "response_preview": preview,
                "pii_masked": masked,
                "pii_entities_found": entities,
                "error_type": type(error).__name__ if error else "",
                "error_message": str(error)[:4000] if error else "",
                "raw_metadata": metadata or {},
            },
        )

    def __enter__(self) -> "Generation":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._ended:
            if exc is not None:
                self.end(status="error", error=exc)
            else:
                self.end(status="success")


def _sdk_version() -> str:
    from argus import __version__

    return __version__
