"""OpenAI-compatible Chat Completions instrumentation. One wrapper covers
OpenAI, Groq, and xAI (they share the wire protocol; pass `provider=`).

Streaming facts encoded here:
- usage requires stream_options={"include_usage": true}; we inject it
- the final usage chunk has an EMPTY `choices` array — never index blindly
- an aborted stream never receives that chunk -> usage is estimated
"""

import functools

from argus.wrappers._common import estimate_tokens, extract_prompt, pick_params


def wrap_openai(client, argus_client=None, provider: str = "openai", **gen_ctx):
    from argus import get_client

    argus_client = argus_client or get_client()
    original = client.chat.completions.create
    is_async = type(client).__name__.startswith("Async")
    factory = _async_create if is_async else _sync_create
    client.chat.completions.create = factory(original, argus_client, provider, gen_ctx)
    return client


def _start(argus_client, provider, kwargs, gen_ctx):
    return argus_client.generation(
        provider,
        kwargs.get("model", "unknown"),
        is_streaming=bool(kwargs.get("stream")),
        prompt=extract_prompt(kwargs.get("messages")),
        request_params=pick_params(kwargs),
        **gen_ctx,
    )


def _inject_usage_option(kwargs):
    if kwargs.get("stream") and "stream_options" not in kwargs:
        kwargs["stream_options"] = {"include_usage": True}


class _StreamState:
    def __init__(self):
        self.text = []
        self.usage = None
        self.finish = None
        self.response_model = ""

    def feed(self, chunk, gen):
        self.response_model = getattr(chunk, "model", "") or self.response_model
        if getattr(chunk, "usage", None):
            self.usage = chunk.usage
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return  # final usage-only chunk
        delta = choices[0].delta
        content = getattr(delta, "content", None)
        if content:
            gen.first_chunk()
            self.text.append(content)
        if getattr(choices[0], "finish_reason", None):
            self.finish = choices[0].finish_reason

    def end_kwargs(self, aborted: bool):
        full = "".join(self.text)
        estimated = self.usage is None
        cached = None
        if self.usage is not None:
            details = getattr(self.usage, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", None) if details else None
        return dict(
            status="aborted" if aborted else "success",
            response_model=self.response_model,
            input_tokens=getattr(self.usage, "prompt_tokens", None) if self.usage else None,
            output_tokens=(
                getattr(self.usage, "completion_tokens", None)
                if self.usage
                else estimate_tokens(full)
            ),
            cached_tokens=cached,
            tokens_estimated=estimated,
            finish_reasons=[self.finish] if self.finish else [],
            response=full,
        )


def _end_from_completion(gen, completion):
    usage = getattr(completion, "usage", None)
    details = getattr(usage, "prompt_tokens_details", None) if usage else None
    choice = completion.choices[0] if getattr(completion, "choices", None) else None
    gen.end(
        response_model=getattr(completion, "model", ""),
        input_tokens=getattr(usage, "prompt_tokens", None),
        output_tokens=getattr(usage, "completion_tokens", None),
        cached_tokens=getattr(details, "cached_tokens", None) if details else None,
        finish_reasons=[choice.finish_reason] if choice and choice.finish_reason else [],
        response=(choice.message.content or "") if choice else "",
    )


def _sync_create(original, argus_client, provider, gen_ctx):
    @functools.wraps(original)
    def create(*args, **kwargs):
        _inject_usage_option(kwargs)
        gen = _start(argus_client, provider, kwargs, gen_ctx)
        try:
            result = original(*args, **kwargs)
        except Exception as exc:
            gen.end(status="error", error=exc)
            raise
        if not kwargs.get("stream"):
            _end_from_completion(gen, result)
            return result

        def iterate():
            state = _StreamState()
            try:
                for chunk in result:
                    state.feed(chunk, gen)
                    yield chunk
                gen.end(**state.end_kwargs(aborted=False))
            except GeneratorExit:
                gen.end(**state.end_kwargs(aborted=True))
                raise
            except Exception as exc:
                gen.end(status="error", error=exc, response="".join(state.text))
                raise

        return iterate()

    return create


def _async_create(original, argus_client, provider, gen_ctx):
    @functools.wraps(original)
    async def create(*args, **kwargs):
        _inject_usage_option(kwargs)
        gen = _start(argus_client, provider, kwargs, gen_ctx)
        try:
            result = await original(*args, **kwargs)
        except Exception as exc:
            gen.end(status="error", error=exc)
            raise
        if not kwargs.get("stream"):
            _end_from_completion(gen, result)
            return result

        async def iterate():
            state = _StreamState()
            try:
                async for chunk in result:
                    state.feed(chunk, gen)
                    yield chunk
                gen.end(**state.end_kwargs(aborted=False))
            except GeneratorExit:
                gen.end(**state.end_kwargs(aborted=True))
                raise
            except Exception as exc:
                gen.end(status="error", error=exc, response="".join(state.text))
                raise

        return iterate()

    return create
