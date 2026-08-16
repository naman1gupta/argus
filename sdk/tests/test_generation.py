from tests.conftest import CapturingClient


def test_lifecycle_and_masking(capture):
    with capture.generation(
        "anthropic", "claude-sonnet-4-5", prompt="mail me at a@b.com", is_streaming=True
    ) as gen:
        gen.first_chunk()
        gen.end(input_tokens=100, output_tokens=50, finish_reasons=["end_turn"],
                response="sure, noted a@b.com")  # fmt: skip

    (t1, start), (t2, end) = capture.events
    assert t1 == "generation-start" and t2 == "generation-end"
    assert start["prompt_preview"] == "mail me at <EMAIL>"
    assert start["pii_entities_found"] == ["EMAIL"]
    assert start["session_id"] == "sess_t" and start["end_user_id"] == "tester"
    assert end["generation_id"] == start["generation_id"]
    assert end["response_preview"] == "sure, noted <EMAIL>"
    assert end["ttft_ms"] is not None and end["latency_ms"] >= end["ttft_ms"]
    assert end["cost_usd"] == round((100 * 3.0 + 50 * 15.0) / 1e6, 8)


def test_exception_records_error(capture):
    try:
        with capture.generation("groq", "llama-3.3-70b-versatile"):
            raise TimeoutError("upstream timeout")
    except TimeoutError:
        pass
    end = capture.events[-1][1]
    assert end["status"] == "error"
    assert end["error_type"] == "TimeoutError" and "upstream" in end["error_message"]


def test_sample_rate_zero_emits_nothing():
    c = CapturingClient()
    c.sample_rate = 0.0
    with c.generation("mock", "m") as gen:
        gen.end()
    assert c.events == []


def test_log_content_false_strips_previews():
    c = CapturingClient(log_content=False)
    with c.generation("mock", "m", prompt="secret a@b.com") as gen:
        gen.end(response="secret reply")
    start, end = c.events[0][1], c.events[1][1]
    assert start["prompt_preview"] == "" and end["response_preview"] == ""
    assert start["pii_masked"] is False


def test_unknown_model_cost_is_null(capture):
    with capture.generation("anthropic", "claude-99-futuristic") as gen:
        gen.end(input_tokens=10, output_tokens=10)
    assert capture.events[-1][1]["cost_usd"] is None
