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


class GroqAdapter(Adapter):
    name, label = "groq", "Groq"
    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    base_url = "https://api.groq.com/openai/v1"

    def available(self):
        return bool(settings.GROQ_API_KEY)

    def _client(self):
        import openai

        return argus.wrap_openai(
            openai.AsyncOpenAI(api_key=settings.GROQ_API_KEY, base_url=self.base_url),
            get_argus(),
            provider="groq",
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


class GeminiAdapter(Adapter):
    name, label = "gcp.gemini", "Google Gemini"
    models = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]

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


MOCK_REPLIES = [
    "Here's what I found. The key idea is to keep telemetry capture out of the request's "
    "critical path: buffer events locally, ship them in the background, and never let the "
    "logging layer take the application down with it. That principle shapes every part of "
    "this system's design.",
    "Good question. For multi-turn conversations the context window is rebuilt from stored "
    "messages on every call, which keeps the server stateless and lets any replica serve any "
    "session. The trade-off is token growth per turn — production systems add summarization.",
    "Sure — refunds for damaged items are processed within 3-5 business days after the claim "
    "is approved. You'll need the order number and a photo of the damage. Once submitted, "
    "you'll receive email confirmation and the amount returns to the original payment method.",
    "Kafka consumer groups rebalance whenever membership changes. Each partition is owned by "
    "exactly one consumer in the group; on rebalance, ownership reshuffles and consumers must "
    "commit offsets carefully to avoid reprocessing or loss — that's why manual commits after "
    "successful persistence matter.",
]


class MockAdapter(Adapter):
    """Zero-key demo provider; exercises the SDK's manual instrumentation API.
    Prompts containing 'trigger error' raise, to demo the error path live."""

    name, label = "mock", "Mock (no key needed)"
    models = ["argus-demo-1"]

    def available(self):
        return True

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
            digest = int(hashlib.sha1(prompt.encode()).hexdigest(), 16)
            reply = MOCK_REPLIES[digest % len(MOCK_REPLIES)]
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


ADAPTERS: dict[str, Adapter] = {
    a.name: a for a in (AnthropicAdapter(), GeminiAdapter(), GroqAdapter(), MockAdapter())
}


def available_providers() -> list[dict]:
    return [
        {"name": a.name, "label": a.label, "models": a.models, "available": a.available()}
        for a in ADAPTERS.values()
    ]
