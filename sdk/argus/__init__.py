"""argus-sdk: capture LLM inference telemetry with zero code changes.

    import argus, anthropic
    argus.init(endpoint="http://localhost:8000/api/v1", api_key="argus_sk_...")
    client = argus.wrap_anthropic(anthropic.Anthropic())
    # use the client exactly as before — every call (incl. streaming) is logged

Fail-open by design: the SDK never raises into, blocks, or slows down the
host application. Events buffer in a bounded queue and ship in background
batches; call argus.flush() before exit in short-lived scripts.
"""

__version__ = "0.1.0"

import functools

from argus.client import ArgusClient, Generation
from argus.masking import mask
from argus.pricing import estimate_cost
from argus.wrappers import wrap_anthropic, wrap_gemini, wrap_openai

_client: ArgusClient | None = None


def init(endpoint: str, api_key: str, **kwargs) -> ArgusClient:
    global _client
    _client = ArgusClient(endpoint, api_key, **kwargs)
    return _client


def get_client() -> ArgusClient:
    if _client is None:
        raise RuntimeError("argus.init(endpoint=..., api_key=...) must be called first")
    return _client


def flush(timeout: float = 10.0) -> None:
    if _client:
        _client.flush(timeout)


def observe(fn=None, *, operation: str | None = None):
    """Decorator: records latency + errors for any function as an inference-log row."""

    def wrap(func):
        @functools.wraps(func)
        def inner(*args, **kwargs):
            gen = get_client().generation(
                "other", func.__qualname__, operation=operation or "task"
            )
            with gen:
                return func(*args, **kwargs)

        return inner

    return wrap(fn) if fn else wrap


__all__ = [
    "ArgusClient",
    "Generation",
    "estimate_cost",
    "flush",
    "get_client",
    "init",
    "mask",
    "observe",
    "wrap_anthropic",
    "wrap_gemini",
    "wrap_openai",
]  # fmt: skip
