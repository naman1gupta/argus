# Providers and the default model

## The default

The app starts on Groq's `llama-3.3-70b-versatile`.

I picked it for two reasons. Groq has a genuinely free API tier, so whoever reviews this
can run real inference without opening a paid account. And its time-to-first-token is low
enough that the TTFT and streaming telemetry are obvious in a demo rather than being lost
in noise.

It's set by `DEFAULT_PROVIDER` and `DEFAULT_MODEL` in `.env`. The chat UI reads the default
from `GET /api/v1/chat/providers` rather than hardcoding it, so changing the environment
variable changes what the app selects on load. If the default provider has no key
configured, the app falls back to the built-in mock so it's never broken out of the box.

## What's supported

All five real providers go through the same SDK instrumentation, so latency, TTFT, token
usage, cost, errors and masked previews come out identical no matter which one served the
request. That's the point of the adapter layer.

| Provider | Models | Wire protocol | Env var | In this submission |
|---|---|---|---|---|
| Groq (default) | `llama-3.3-70b-versatile`, `llama-3.1-8b-instant` | OpenAI-compatible | `GROQ_API_KEY` | configured, free tier |
| Google Gemini | `gemini-flash-latest`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite` | Google GenAI | `GEMINI_API_KEY` | configured, free tier |
| Anthropic | `claude-sonnet-4-5`, `claude-haiku-4-5` | Anthropic Messages | `ANTHROPIC_API_KEY` | implemented, no key supplied |
| OpenAI | `gpt-5.4-mini`, `gpt-5.4` | OpenAI Chat Completions | `OPENAI_API_KEY` | implemented, no key supplied |
| xAI | `grok-4`, `grok-4-fast` | OpenAI-compatible | `XAI_API_KEY` | implemented, no key supplied |
| Mock | `argus-demo-1` | none | none | always available |

**On the missing keys.** Anthropic, OpenAI and xAI have no free tier, so I haven't bundled
paid keys with a public submission. Their adapters are complete and they show up in the
model picker marked "no key"; add a key to `.env`, restart, and they work with no code
change. The two free-tier providers, Groq and Gemini, are wired up and were used to record
the demo. The mock provider needs no credentials at all, which is why every feature in the
system is reviewable with an empty `.env`.

## Adding one

There are two shapes, and one of them is nearly free.

If the provider speaks the OpenAI Chat Completions protocol, which covers vLLM, Together,
Fireworks, Azure OpenAI and most self-hosted gateways, it's a subclass:

```python
class TogetherAdapter(OpenAICompatibleAdapter):
    name, label = "together", "Together AI"
    models = ["meta-llama/Llama-3.3-70B-Instruct-Turbo"]
    base_url = "https://api.together.xyz/v1"
    api_key_setting = "TOGETHER_API_KEY"
```

That's the entire change. Register it in `ADAPTERS` in `server/apps/chat/providers.py` and
it appears in the UI, the cost table and the dashboards on its own.

If the provider has its own protocol, you implement `Adapter.stream()` and add an SDK
wrapper that knows where that provider reports token usage, which is the part that's never
the same twice. `sdk/argus/wrappers/` has one module per protocol; `gemini.py` is the
clearest example, including the cumulative-usage handling that one needs.

## Cost

Prices live in `sdk/argus/pricing.py` as USD per million tokens, with the date they were
taken written in the file, because they go stale and a number without a date is a trap.

Cost is computed in the SDK at capture time, using the response model where the provider
reports one (it isn't always the model you asked for), with cached input tokens discounted
at the provider's cached rate.

An unknown model produces a null cost rather than a plausible-looking wrong one. The
dashboards show the gap. Under-reporting spend silently is worse than admitting you don't
know the price of something.
