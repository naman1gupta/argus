import asyncio
from types import SimpleNamespace as NS

import pytest

from argus.wrappers.anthropic import wrap_anthropic
from argus.wrappers.openai_compat import wrap_openai


def anthropic_events():
    return [
        NS(type="message_start",
           message=NS(model="claude-sonnet-4-5",
                      usage=NS(input_tokens=472, cache_read_input_tokens=0))),
        NS(type="content_block_start"),
        NS(type="content_block_delta", delta=NS(text="Hello")),
        NS(type="content_block_delta", delta=NS(text=" world")),
        NS(type="content_block_stop"),
        NS(type="message_delta", delta=NS(stop_reason="end_turn"), usage=NS(output_tokens=312)),
        NS(type="message_stop"),
    ]  # fmt: skip


class FakeAnthropic:
    def __init__(self, events):
        self._events = events
        self.messages = NS(create=self._create)

    def _create(self, **kwargs):
        return iter(self._events)


def test_anthropic_stream_capture(capture):
    client = wrap_anthropic(FakeAnthropic(anthropic_events()), argus_client=capture)
    out = list(client.messages.create(
        model="claude-sonnet-4-5", stream=True,
        messages=[{"role": "user", "content": "hi"}],
    ))  # fmt: skip
    assert len(out) == 7
    start, end = capture.events[0][1], capture.events[1][1]
    assert start["is_streaming"] is True and start["provider"] == "anthropic"
    assert end["input_tokens"] == 472 and end["output_tokens"] == 312
    assert end["finish_reasons"] == ["end_turn"] and end["tokens_estimated"] is False
    assert end["response_preview"] == "Hello world"
    assert end["ttft_ms"] is not None


def test_anthropic_aborted_stream_estimates_usage(capture):
    client = wrap_anthropic(FakeAnthropic(anthropic_events()), argus_client=capture)
    stream = client.messages.create(model="claude-sonnet-4-5", stream=True,
                                    messages=[{"role": "user", "content": "hi"}])  # fmt: skip
    for i, _ in enumerate(stream):
        if i == 3:  # stop mid-stream, before message_delta usage arrives
            stream.close()
            break
    end = capture.events[-1][1]
    assert end["status"] == "aborted" and end["tokens_estimated"] is True
    assert end["output_tokens"] >= 1  # estimated from accumulated text


def test_anthropic_provider_error(capture):
    client = FakeAnthropic([])

    def boom(**kwargs):
        raise ConnectionError("api down")

    client.messages.create = boom
    wrap_anthropic(client, argus_client=capture)
    with pytest.raises(ConnectionError):
        client.messages.create(model="m", messages=[])
    assert capture.events[-1][1]["status"] == "error"


def openai_chunks():
    return [
        NS(model="llama-3.3-70b-versatile", usage=None,
           choices=[NS(delta=NS(content=None, role="assistant"), finish_reason=None)]),
        NS(model="llama-3.3-70b-versatile", usage=None,
           choices=[NS(delta=NS(content="Hey"), finish_reason=None)]),
        NS(model="llama-3.3-70b-versatile", usage=None,
           choices=[NS(delta=NS(content=" there"), finish_reason="stop")]),
        NS(model="llama-3.3-70b-versatile", choices=[],   # final usage-only chunk
           usage=NS(prompt_tokens=20, completion_tokens=6, prompt_tokens_details=None)),
    ]  # fmt: skip


class FakeOpenAI:
    def __init__(self, chunks):
        self._chunks = chunks
        self.captured_kwargs = None
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.captured_kwargs = kwargs
        return iter(self._chunks)


def test_openai_stream_injects_usage_option_and_survives_empty_choices(capture):
    fake = FakeOpenAI(openai_chunks())
    client = wrap_openai(fake, argus_client=capture, provider="groq")
    list(client.chat.completions.create(model="llama-3.3-70b-versatile", stream=True,
                                        messages=[{"role": "user", "content": "hi"}]))  # fmt: skip
    assert fake.captured_kwargs["stream_options"] == {"include_usage": True}
    end = capture.events[-1][1]
    assert end["input_tokens"] == 20 and end["output_tokens"] == 6
    assert end["response_preview"] == "Hey there"
    assert capture.events[0][1]["provider"] == "groq"


def test_openai_non_stream(capture):
    completion = NS(
        model="gpt-5.4-mini",
        usage=NS(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None),
        choices=[NS(finish_reason="stop", message=NS(content="hi back"))],
    )
    fake = FakeOpenAI([])
    fake.chat.completions.create = lambda **kw: completion
    client = wrap_openai(fake, argus_client=capture)
    client.chat.completions.create(model="gpt-5.4-mini", messages=[])
    end = capture.events[-1][1]
    assert end["status"] == "success" and end["output_tokens"] == 5
    assert end["cost_usd"] is not None


class AsyncFakeOpenAI:
    """Async client whose stream blocks forever after the first chunk, so a
    consumer cancelling mid-stream is what ends it."""

    def __init__(self):
        self.chat = NS(completions=NS(create=self._create))

    async def _create(self, **kwargs):
        async def gen():
            yield NS(model="llama-3.3-70b-versatile", usage=None,
                     choices=[NS(delta=NS(content="Hello"), finish_reason=None)])  # fmt: skip
            await asyncio.Event().wait()  # never resolves; the caller must cancel

        return gen()


@pytest.mark.asyncio
async def test_async_stream_cancelled_mid_flight_is_aborted(capture):
    """A cancelled async stream must still be recorded.

    ASGI servers cancel the task on client disconnect, which raises CancelledError
    inside the stream loop rather than GeneratorExit. CancelledError is a
    BaseException, so a bare `except Exception` misses it and the generation would
    stay pending forever.
    """
    client = wrap_openai(AsyncFakeOpenAI(), argus_client=capture)
    stream = await client.chat.completions.create(
        model="llama-3.3-70b-versatile", stream=True,
        messages=[{"role": "user", "content": "hi"}],
    )  # fmt: skip

    async def consume():
        async for _ in stream:
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    end = capture.events[-1][1]
    assert end["status"] == "aborted"
    assert end["tokens_estimated"] is True
    assert end["output_tokens"] >= 1
