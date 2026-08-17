"""Google Gemini (google-genai SDK) instrumentation.

Streaming facts encoded here:
- usage_metadata rides on EVERY chunk and is cumulative — take the last seen
- thinking tokens (thoughts_token_count) bill as output and are tracked separately
"""

import asyncio
import functools

from argus.wrappers._common import estimate_tokens


def wrap_gemini(client, argus_client=None, **gen_ctx):
    from argus import get_client

    argus_client = argus_client or get_client()
    models = client.models
    models.generate_content = _sync_call(models.generate_content, argus_client, gen_ctx)
    models.generate_content_stream = _sync_stream(
        models.generate_content_stream, argus_client, gen_ctx
    )
    aio = getattr(client, "aio", None)
    if aio is not None:
        aio.models.generate_content = _async_call(
            aio.models.generate_content, argus_client, gen_ctx
        )
        aio.models.generate_content_stream = _async_stream(
            aio.models.generate_content_stream, argus_client, gen_ctx
        )
    return client


def _prompt_from_contents(contents) -> str:
    if isinstance(contents, str):
        return contents
    try:
        parts = []
        for item in contents if isinstance(contents, list) else [contents]:
            if isinstance(item, str):
                parts.append(item)
                continue
            for part in getattr(item, "parts", None) or (
                item.get("parts", []) if isinstance(item, dict) else []
            ):
                text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                if text:
                    parts.append(text)
        return "\n".join(parts[-3:])
    except Exception:
        return ""


def _start(argus_client, kwargs, gen_ctx, streaming):
    ctx = {**gen_ctx, **kwargs.pop("argus_context", {})}
    return argus_client.generation(
        "gcp.gemini",
        kwargs.get("model", "unknown"),
        is_streaming=streaming,
        prompt=_prompt_from_contents(kwargs.get("contents")),
        **ctx,
    )


def _usage_kwargs(usage, text, response, aborted=False):
    estimated = usage is None
    return dict(
        status="aborted" if aborted else "success",
        response_model=getattr(response, "model_version", "") if response is not None else "",
        input_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
        output_tokens=(
            (getattr(usage, "candidates_token_count", None) or 0)
            if usage
            else estimate_tokens(text)
        ),
        cached_tokens=getattr(usage, "cached_content_token_count", None) if usage else None,
        reasoning_tokens=getattr(usage, "thoughts_token_count", None) if usage else None,
        tokens_estimated=estimated,
        finish_reasons=_finish(response),
        response=text,
    )


def _finish(response):
    try:
        reason = response.candidates[0].finish_reason
        return [reason.name if hasattr(reason, "name") else str(reason)] if reason else []
    except Exception:
        return []


def _sync_call(original, argus_client, gen_ctx):
    @functools.wraps(original)
    def call(*args, **kwargs):
        gen = _start(argus_client, kwargs, gen_ctx, streaming=False)
        try:
            response = original(*args, **kwargs)
        except Exception as exc:
            gen.end(status="error", error=exc)
            raise
        gen.end(**_usage_kwargs(response.usage_metadata, response.text or "", response))
        return response

    return call


def _async_call(original, argus_client, gen_ctx):
    @functools.wraps(original)
    async def call(*args, **kwargs):
        gen = _start(argus_client, kwargs, gen_ctx, streaming=False)
        try:
            response = await original(*args, **kwargs)
        except Exception as exc:
            gen.end(status="error", error=exc)
            raise
        gen.end(**_usage_kwargs(response.usage_metadata, response.text or "", response))
        return response

    return call


def _sync_stream(original, argus_client, gen_ctx):
    @functools.wraps(original)
    def call(*args, **kwargs):
        gen = _start(argus_client, kwargs, gen_ctx, streaming=True)
        try:
            stream = original(*args, **kwargs)
        except Exception as exc:
            gen.end(status="error", error=exc)
            raise

        def iterate():
            text, usage, last = [], None, None
            try:
                for chunk in stream:
                    last = chunk
                    usage = getattr(chunk, "usage_metadata", None) or usage
                    if chunk.text:
                        gen.first_chunk()
                        text.append(chunk.text)
                    yield chunk
                gen.end(**_usage_kwargs(usage, "".join(text), last))
            except GeneratorExit:
                gen.end(**_usage_kwargs(usage, "".join(text), last, aborted=True))
                raise
            except Exception as exc:
                gen.end(status="error", error=exc, response="".join(text))
                raise

        return iterate()

    return call


def _async_stream(original, argus_client, gen_ctx):
    @functools.wraps(original)
    async def call(*args, **kwargs):
        gen = _start(argus_client, kwargs, gen_ctx, streaming=True)
        try:
            stream = await original(*args, **kwargs)
        except Exception as exc:
            gen.end(status="error", error=exc)
            raise

        async def iterate():
            text, usage, last = [], None, None
            try:
                async for chunk in stream:
                    last = chunk
                    usage = getattr(chunk, "usage_metadata", None) or usage
                    if chunk.text:
                        gen.first_chunk()
                        text.append(chunk.text)
                    yield chunk
                gen.end(**_usage_kwargs(usage, "".join(text), last))
            except (GeneratorExit, asyncio.CancelledError):
                gen.end(**_usage_kwargs(usage, "".join(text), last, aborted=True))
                raise
            except Exception as exc:
                gen.end(status="error", error=exc, response="".join(text))
                raise

        return iterate()

    return call
