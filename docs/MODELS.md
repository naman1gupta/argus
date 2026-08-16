# Model providers & defaults

## Default model

| | |
|---|---|
| **Default provider** | `groq` |
| **Default model** | `llama-3.3-70b-versatile` |
| **Why** | Groq has a genuinely free API tier, so the reviewer can run real inference without a paid account, and its very low time-to-first-token makes the streaming and TTFT telemetry obvious in a demo. |
| **Configured by** | `DEFAULT_PROVIDER` / `DEFAULT_MODEL` in `.env` — the chat UI reads the default from `GET /api/v1/chat/providers`, so changing the env var changes what the app selects on load. |
| **Fallback** | If the default provider has no key configured, the app automatically falls back to the built-in `mock` provider so the system is never broken out of the box. |

## Supported providers

All five real providers go through the same SDK instrumentation, so the telemetry
(latency, TTFT, token usage, cost, errors, masked previews) is identical no matter
which one serves the request.

| Provider | Models exposed | Wire protocol | Key env var | Status in this submission |
|---|---|---|---|---|
| **Groq** ⭐ default | `llama-3.3-70b-versatile`, `llama-3.1-8b-instant` | OpenAI-compatible | `GROQ_API_KEY` | **Configured — free tier** |
| **Google Gemini** | `gemini-flash-latest`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite` | Google GenAI | `GEMINI_API_KEY` | **Configured — free tier** |
| **Anthropic** | `claude-sonnet-4-5`, `claude-haiku-4-5` | Anthropic Messages | `ANTHROPIC_API_KEY` | Implemented, key not supplied (paid) |
| **OpenAI** | `gpt-5.4-mini`, `gpt-5.4` | OpenAI Chat Completions | `OPENAI_API_KEY` | Implemented, key not supplied (paid) |
| **xAI (Grok)** | `grok-4`, `grok-4-fast` | OpenAI-compatible | `XAI_API_KEY` | Implemented, key not supplied (paid) |
| **Mock** | `argus-demo-1` | — | none | Always available |

> **Disclaimer on keys.** Anthropic, OpenAI and xAI have no free API tier, so no
> paid keys are bundled with this submission. Their adapters are fully implemented
> and appear in the model picker marked *(no key)* — add a key to `.env`, restart,
> and they activate with no code change. The two providers with free tiers
> (**Groq** and **Gemini**) are wired up and were used for the demo, with **Groq's
> `llama-3.3-70b-versatile` as the default**. The `mock` provider needs no key at
> all, so every feature is demoable with zero credentials.

## Adding another provider

Two shapes, both small:

- **OpenAI-compatible endpoint** (vLLM, Together, Fireworks, Azure OpenAI, any
  self-hosted gateway) — subclass `OpenAICompatibleAdapter` with a `base_url`,
  a key setting and a model list. That is the whole change:

  ```python
  class TogetherAdapter(OpenAICompatibleAdapter):
      name, label = "together", "Together AI"
      models = ["meta-llama/Llama-3.3-70B-Instruct-Turbo"]
      base_url = "https://api.together.xyz/v1"
      api_key_setting = "TOGETHER_API_KEY"
  ```

- **Native SDK** (a provider with its own protocol) — implement `Adapter.stream()`
  and add an SDK wrapper that knows where that provider reports token usage.
  `sdk/argus/wrappers/` has one module per protocol; see `gemini.py` for the
  shape, including the cumulative-usage handling that provider requires.

Register the class in `ADAPTERS` in `server/apps/chat/providers.py` and it appears
in the UI, the cost table and the dashboards automatically.

## Cost attribution

Per-model prices live in `sdk/argus/pricing.py` (USD per million tokens, dated in
the file). Cost is computed in the SDK at capture time using the *response* model
where the provider reports one, with cached-input tokens discounted. An unknown
model yields a `null` cost rather than a wrong number — the dashboards show the
gap instead of quietly under-reporting spend.
