"""Static price table (USD per 1M tokens), rates as of 2026-08-16.
Longest-prefix match tolerates dated model suffixes. Unknown models -> None
(cost stays null rather than silently wrong). Cached input bills at 0.1x."""

PRICES: dict[str, dict[str, tuple[float, float]]] = {
    "anthropic": {
        "claude-sonnet-4-5": (3.00, 15.00),
        "claude-sonnet-4-6": (3.00, 15.00),
        "claude-haiku-4-5": (1.00, 5.00),
        "claude-opus-4": (5.00, 25.00),
    },
    "gcp.gemini": {
        "gemini-2.5-pro": (1.25, 10.00),
        "gemini-2.5-flash-lite": (0.10, 0.40),
        "gemini-2.5-flash": (0.30, 2.50),
        "gemini-3-flash-preview": (0.50, 3.00),
        "gemini-3.1-flash-lite": (0.10, 0.40),
        "gemini-flash-latest": (0.50, 3.00),
        "gemini-3.7-flash": (1.50, 7.50),
    },
    "groq": {
        "llama-3.3-70b-versatile": (0.59, 0.79),
        "llama-3.1-8b-instant": (0.05, 0.08),
        "openai/gpt-oss-20b": (0.10, 0.50),
    },
    "openai": {
        "gpt-5.4": (2.50, 15.00),
        "gpt-5.4-mini": (0.75, 4.50),
        "gpt-5.4-nano": (0.20, 1.25),
    },
    "mock": {"": (0.0, 0.0)},
}

CACHED_INPUT_FACTOR = 0.1


def estimate_cost(
    provider: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_tokens: int | None = None,
) -> float | None:
    table = PRICES.get(provider, {})
    match = None
    for prefix in sorted(table, key=len, reverse=True):
        if model.startswith(prefix):
            match = table[prefix]
            break
    if match is None or input_tokens is None or output_tokens is None:
        return None
    in_rate, out_rate = match
    cached = cached_tokens or 0
    fresh_in = max(input_tokens - cached, 0)
    cost = (
        fresh_in * in_rate + cached * in_rate * CACHED_INPUT_FACTOR + output_tokens * out_rate
    ) / 1_000_000
    return round(cost, 8)
