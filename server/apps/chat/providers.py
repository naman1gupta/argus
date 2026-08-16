"""Provider adapters. Real providers use SDK-wrapped clients (dogfooding:
telemetry flows through the same public ingestion API any customer would use).
The mock provider needs no API key and demonstrates the SDK's manual API."""

import asyncio
import hashlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import argus
from django.conf import settings

_initialized = False


def get_argus() -> argus.ArgusClient:
    global _initialized
    if not _initialized:
        argus.init(
            endpoint=settings.ARGUS_ENDPOINT,
            api_key=settings.CHAT_INGEST_KEY,
            environment="production",
            disabled=settings.ARGUS_DISABLED,
        )
        _initialized = True
    return argus.get_client()


class ProviderError(Exception):
    pass


class Adapter(ABC):
    name: str
    label: str
    models: list[str]

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def stream(self, model, messages, *, session_id, end_user_id) -> AsyncIterator[str]:
        """Yields response text deltas. Telemetry is handled inside."""


class AnthropicAdapter(Adapter):
    name, label = "anthropic", "Anthropic"
    models = ["claude-sonnet-4-5", "claude-haiku-4-5"]

    def available(self):
        return bool(settings.ANTHROPIC_API_KEY)

    def _client(self):
        import anthropic

        return argus.wrap_anthropic(
            anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY), get_argus()
        )

    async def stream(self, model, messages, *, session_id, end_user_id):
        stream = await self._client().messages.create(
            model=model,
            max_tokens=1024,
            messages=messages,
            stream=True,
            argus_context={"session_id": session_id, "end_user_id": end_user_id},
        )
        async for event in stream:
            if getattr(event, "type", "") == "content_block_delta":
                text = getattr(event.delta, "text", None)
                if text:
                    yield text


class OpenAICompatibleAdapter(Adapter):
    """Any endpoint speaking the OpenAI Chat Completions protocol — Groq, xAI,
    OpenAI itself, vLLM, Together. Adding one is a subclass with a base_url."""

    base_url: str
    api_key_setting: str

    @property
    def api_key(self) -> str:
        return getattr(settings, self.api_key_setting, "")

    def available(self):
        return bool(self.api_key)

    def _client(self):
        import openai

        return argus.wrap_openai(
            openai.AsyncOpenAI(api_key=self.api_key, base_url=self.base_url),
            get_argus(),
            provider=self.name,
        )

    async def stream(self, model, messages, *, session_id, end_user_id):
        stream = await self._client().chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            argus_context={"session_id": session_id, "end_user_id": end_user_id},
        )
        async for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if choices and getattr(choices[0].delta, "content", None):
                yield choices[0].delta.content


class GroqAdapter(OpenAICompatibleAdapter):
    name, label = "groq", "Groq"
    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    base_url = "https://api.groq.com/openai/v1"
    api_key_setting = "GROQ_API_KEY"


class OpenAIAdapter(OpenAICompatibleAdapter):
    name, label = "openai", "OpenAI"
    models = ["gpt-5.4-mini", "gpt-5.4"]
    base_url = "https://api.openai.com/v1"
    api_key_setting = "OPENAI_API_KEY"


class XAIAdapter(OpenAICompatibleAdapter):
    name, label = "xai", "xAI (Grok)"
    models = ["grok-4", "grok-4-fast"]
    base_url = "https://api.x.ai/v1"
    api_key_setting = "XAI_API_KEY"


class GeminiAdapter(Adapter):
    name, label = "gcp.gemini", "Google Gemini"
    models = ["gemini-flash-latest", "gemini-3-flash-preview", "gemini-3.1-flash-lite"]

    def available(self):
        return bool(settings.GEMINI_API_KEY)

    def _client(self):
        from google import genai

        return argus.wrap_gemini(genai.Client(api_key=settings.GEMINI_API_KEY), get_argus())

    async def stream(self, model, messages, *, session_id, end_user_id):
        contents = [
            {
                "role": "model" if m["role"] == "assistant" else "user",
                "parts": [{"text": m["content"]}],
            }
            for m in messages
        ]
        stream = await self._client().aio.models.generate_content_stream(
            model=model,
            contents=contents,
            argus_context={"session_id": session_id, "end_user_id": end_user_id},
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text


MOCK_NOTES = [
    "Telemetry capture stays off the request's critical path here: events are buffered "
    "locally and shipped in the background, so the logging layer can never take the "
    "application down with it.",
    "Multi-turn context is rebuilt from stored messages on every call, which keeps the "
    "server stateless — any replica can serve any session.",
    "Each inference is logged twice: once when it starts (you see it as pending in the "
    "live tail) and once when it finishes, merged idempotently by generation id.",
    "Streaming telemetry is per-provider: time-to-first-token is measured at the first "
    "content delta, and an aborted stream is flagged with estimated usage rather than a "
    "guess.",
]


class MockAdapter(Adapter):
    """Zero-key demo provider so the system is fully demoable without API keys.

    It does not answer the question — it echoes it and says so, because a canned
    answer to a real question reads as a broken chatbot. Configure any provider
    key for real completions. 'trigger error' raises, to demo the error path.
    """

    name, label = "mock", "Mock — echoes your message (no API key needed)"
    models = ["argus-demo-1"]

    def available(self):
        return True

    def _reply(self, prompt: str, turn_count: int) -> str:
        digest = int(hashlib.sha1(prompt.encode()).hexdigest(), 16)
        note = MOCK_NOTES[digest % len(MOCK_NOTES)]
        asked = prompt.strip()
        if len(asked) > 220:
            asked = asked[:220].rstrip() + "…"
        turn = (
            f" This is turn {turn_count} of our conversation, so multi-turn context works."
            if turn_count > 1
            else ""
        )
        return (
            f'You said: "{asked}". I am the built-in mock provider — I echo your message '
            f"instead of answering it, so the whole system (SDK capture, Kafka pipeline, "
            f"dashboards) is demoable with zero API keys.{turn} Add GROQ_API_KEY, "
            f"GEMINI_API_KEY or ANTHROPIC_API_KEY to your .env and pick that provider above "
            f"for real model responses. Meanwhile, one thing this system does: {note}"
        )

    async def stream(self, model, messages, *, session_id, end_user_id):
        prompt = messages[-1]["content"] if messages else ""
        gen = get_argus().generation(
            "mock", model, is_streaming=True, prompt=prompt,
            session_id=session_id, end_user_id=end_user_id,
        )  # fmt: skip
        text_so_far = []
        try:
            await asyncio.sleep(0.3)
            if "trigger error" in prompt.lower():
                raise ProviderError("simulated provider outage (mock)")
            reply = self._reply(prompt, sum(1 for m in messages if m["role"] == "user"))
            words = reply.split(" ")
            for i, word in enumerate(words):
                gen.first_chunk()
                delta = word if i == 0 else " " + word
                text_so_far.append(delta)
                yield delta
                await asyncio.sleep(0.02)
            gen.end(
                input_tokens=max(sum(len(m["content"]) for m in messages) // 4, 1),
                output_tokens=max(len(reply) // 4, 1),
                finish_reasons=["stop"],
                response=reply,
                response_model=model,
            )
        except asyncio.CancelledError:
            gen.end(status="aborted", tokens_estimated=True,
                    output_tokens=max(len("".join(text_so_far)) // 4, 1),
                    response="".join(text_so_far))  # fmt: skip
            raise
        except ProviderError as exc:
            gen.end(status="error", error=exc)
            raise


# Order matters: this is the order shown in the model picker.
ADAPTERS: dict[str, Adapter] = {
    a.name: a
    for a in (
        GroqAdapter(),       # free tier — default provider
        GeminiAdapter(),     # free tier
        AnthropicAdapter(),  # paid
        OpenAIAdapter(),     # paid
        XAIAdapter(),        # paid
        MockAdapter(),       # no key required
    )
}


def available_providers() -> list[dict]:
    return [
        {
            "name": a.name,
            "label": a.label,
            "models": a.models,
            "available": a.available(),
            "is_default": a.name == settings.DEFAULT_PROVIDER,
        }
        for a in ADAPTERS.values()
    ]


def default_selection() -> tuple[str, str]:
    """Configured default, falling back to mock when its key is absent."""
    adapter = ADAPTERS.get(settings.DEFAULT_PROVIDER)
    if adapter and adapter.available() and settings.DEFAULT_MODEL in adapter.models:
        return adapter.name, settings.DEFAULT_MODEL
    return "mock", "argus-demo-1"
