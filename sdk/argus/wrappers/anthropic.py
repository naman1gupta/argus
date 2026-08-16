"""Anthropic Messages API instrumentation (sync + async, streaming + not).

Streaming telemetry facts this encodes:
- input tokens arrive up-front on `message_start`
- final output tokens + stop_reason arrive on `message_delta` (end of stream)
- TTFT is measured at the first `content_block_delta`, NOT at message_start
- an abandoned stream never sees message_delta -> usage is estimated
"""

import functools

from argus.wrappers._common import estimate_tokens, extract_prompt, pick_params


def wrap_anthropic(client, argus_client=None, **gen_ctx):
    from argus import get_client

    argus_client = argus_client or get_client()
    original = client.messages.create
    is_async = type(client).__name__.startswith("Async")
    wrapper = _async_create(original, argus_client, gen_ctx) if is_async else _sync_create(
        original, argus_client, gen_ctx
    )
    client.messages.create = wrapper
    return client


def _start(argus_client, kwargs, gen_ctx):
    return argus_client.generation(
        "anthropic",
        kwargs.get("model", "unknown"),
        is_streaming=bool(kwargs.get("stream")),
        prompt=extract_prompt(kwargs.get("messages")),
        request_params=pick_params(kwargs),
        **gen_ctx,
    )


class _StreamState:
    def __init__(self):
        self.text = []
        self.input_tokens = None
        self.cached_tokens = None
        self.output_tokens = None
        self.stop_reason = None
        self.response_model = ""

    def feed(self, event, gen):
        etype = getattr(event, "type", "")
        if etype == "message_start":
            usage = event.message.usage
            self.input_tokens = getattr(usage, "input_tokens", None)
            self.cached_tokens = getattr(usage, "cache_read_input_tokens", None)
            self.response_model = getattr(event.message, "model", "")
        elif etype == "content_block_delta":
            gen.first_chunk()
            text = getattr(event.delta, "text", None)
            if text:
                self.text.append(text)
        elif etype == "message_delta":
            self.output_tokens = getattr(event.usage, "output_tokens", None)
            self.stop_reason = getattr(event.delta, "stop_reason", None)

    def end_kwargs(self, aborted: bool):
        full = "".join(self.text)
        estimated = aborted and self.output_tokens is None
        return dict(
            status="aborted" if aborted else "success",
            response_model=self.response_model,
            input_tokens=self.input_tokens,
            output_tokens=estimate_tokens(full) if estimated else self.output_tokens,
            cached_tokens=self.cached_tokens,
            tokens_estimated=estimated,
            finish_reasons=[self.stop_reason] if self.stop_reason else [],
            response=full,
        )


def _end_from_message(gen, message):
    usage = getattr(message, "usage", None)
    text = "".join(
        getattr(b, "text", "") for b in getattr(message, "content", []) if getattr(b, "text", "")
    )
    gen.end(
        response_model=getattr(message, "model", ""),
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        cached_tokens=getattr(usage, "cache_read_input_tokens", None),
        finish_reasons=[message.stop_reason] if getattr(message, "stop_reason", None) else [],
        response=text,
    )


def _sync_create(original, argus_client, gen_ctx):
    @functools.wraps(original)
    def create(*args, **kwargs):
        gen = _start(argus_client, kwargs, gen_ctx)
        try:
            result = original(*args, **kwargs)
        except Exception as exc:
            gen.end(status="error", error=exc)
            raise
        if not kwargs.get("stream"):
            _end_from_message(gen, result)
            return result

        def iterate():
            state = _StreamState()
            try:
                for event in result:
                    state.feed(event, gen)
                    yield event
                gen.end(**state.end_kwargs(aborted=False))
            except GeneratorExit:
                gen.end(**state.end_kwargs(aborted=True))
                raise
            except Exception as exc:
                gen.end(status="error", error=exc, response="".join(state.text))
                raise

        return iterate()

    return create


def _async_create(original, argus_client, gen_ctx):
    @functools.wraps(original)
    async def create(*args, **kwargs):
        gen = _start(argus_client, kwargs, gen_ctx)
        try:
            result = await original(*args, **kwargs)
        except Exception as exc:
            gen.end(status="error", error=exc)
            raise
        if not kwargs.get("stream"):
            _end_from_message(gen, result)
            return result

        async def iterate():
            state = _StreamState()
            try:
                async for event in result:
                    state.feed(event, gen)
                    yield event
                gen.end(**state.end_kwargs(aborted=False))
            except GeneratorExit:
                gen.end(**state.end_kwargs(aborted=True))
                raise
            except Exception as exc:
                gen.end(status="error", error=exc, response="".join(state.text))
                raise

        return iterate()

    return create
