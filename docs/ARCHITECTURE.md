# Architecture

Three runtime services from one repo — **api** (Django/ASGI), **worker** (Kafka
consumer), **frontend** (nginx + React SPA) — plus Kafka (KRaft) and Postgres.

## 1 · The write path (an inference becomes a row)

```
chat request ──► provider adapter ──► LLM provider (streaming SSE)
                     │ wrapped by argus-sdk
                     │
        ┌────────────┴─────────────┐
        │ generation-start event   │  emitted the moment the call begins
        │ generation-end event     │  emitted at completion / error / abort
        └────────────┬─────────────┘
                     ▼  bounded queue, background thread, batches (fail-open)
        POST /api/v1/logs   Bearer argus_sk_…
                     │  per-item pydantic validation → 202 / 207
                     │  rate limit per key · ≤500 events/batch
                     ▼
        Kafka topic `inference_events` (8 partitions, key = session_id)
                     │                       └── same key ⇒ same partition ⇒
                     │                           start always precedes end
                     ▼
        consumer group `argus-persister`
        · getmany(≤500) → idempotent persist → commit offsets (manual)
        · 3 attempts per event → DLQ topic `inference_events.dlq`
                     ▼
        Postgres `telemetry_inferencelog`
        · start ⇒ INSERT … ON CONFLICT DO NOTHING  (status=pending)
        · end   ⇒ fetch-merge-save (deterministic; replay-safe)
```

**Degraded mode:** if the Kafka produce fails, the api falls back to a synchronous
Postgres write and logs a warning; the response reports `mode: "direct"`.

**Read paths:** dashboard aggregates query Postgres (`percentile_cont` for latency
percentiles, filtered/partial indexes for the hot filters). The Requests page's LIVE
feed is an SSE endpoint running a *second, group-less* Kafka consumer at latest
offset — the same topic serves persistence and live UX, and pending→resolved row
transitions in the UI are the two-phase events made visible.

## 2 · The SDK (`sdk/argus`)

**Contract:** never raise into, block, or slow the host application.

- **Transport:** bounded `deque` (10k, drop-oldest + counter) → daemon thread →
  batches of 20 or every 1s → `POST /logs` with 3 retries and backoff. 4xx (except
  429) never retries; `atexit` flush; `flush()` for scripts. Everything is wrapped in
  suppress-and-log.
- **Integration modes:** client wrappers (`wrap_anthropic`, `wrap_openai` — covers any
  OpenAI-compatible endpoint incl. Groq/xAI via `base_url`, `wrap_gemini`), a manual
  `client.generation(...)` context manager, and an `@observe` decorator. Wrappers
  patch instance methods only; per-call context is passed as
  `argus_context={"session_id": …, "end_user_id": …}` and popped before the provider
  sees the kwargs.
- **Masking:** compiled-regex pipeline with checksums (see DECISIONS ADR-7), applied
  mask-then-truncate so a split card number can't evade the pattern.
- **Cost:** static per-MTok price table (dated in source), longest-prefix model match,
  cached-input discounting; unknown model ⇒ cost stays null rather than silently wrong.

### Streaming capture — the per-provider facts this encodes

| Provider | Where usage arrives | Trap handled |
|---|---|---|
| OpenAI-compatible (Groq/xAI/OpenAI) | final extra chunk, only with `stream_options={"include_usage": true}` (SDK injects it) | that chunk has an **empty `choices` array** — naïve `chunk.choices[0]` crashes |
| Anthropic | split: `input_tokens` on `message_start`, final `output_tokens` + `stop_reason` on `message_delta` | TTFT must be measured at the first `content_block_delta`, **not** `message_start` |
| Gemini | `usage_metadata` on **every** chunk, cumulative — take the last | thinking tokens (`thoughts_token_count`) tracked separately; billed as output |
| all | — | **aborted streams** never deliver the final usage frame ⇒ estimate + `tokens_estimated=true`, status `aborted` |

Latency is three timestamps (`started_at`, `first_chunk_at`, `completed_at`) plus
derived `ttft_ms` / `latency_ms`; wall-clock for records, monotonic clock for the
durations.

## 3 · Chat service (`server/apps/chat`)

Provider adapters implement one interface (`stream(model, messages, …) → text deltas`)
and are registered in a dict — adding a provider is one class. Real adapters use
SDK-wrapped clients (**dogfooding**: the bundled app ships telemetry through the same
public ingestion API any customer would). The mock adapter needs no key, exercises the
SDK's manual API, streams word-by-word with realistic TTFT, and fails on demand
(`trigger error`) for demos.

The chat endpoint is an async-generator `StreamingHttpResponse` (SSE) under uvicorn:
`token` events per delta, then `done` / `error`. Client disconnect (the Stop button)
raises `CancelledError` in the generator → partial assistant text is persisted, the
SDK wrapper records `aborted` with estimated usage. Context is rebuilt from stored
messages every turn (server stays stateless; any replica serves any session). GZip
middleware is deliberately absent — it buffers streaming responses.

## 4 · Security & tenancy

- **Users:** session auth (HttpOnly cookie) with CSRF enforced by Ninja's SessionAuth;
  roles `admin` / `member` checked per-router (`admin_auth`); member data access is
  scoped to own sessions/usage in queries, not just hidden in the UI.
- **Ingestion:** Bearer keys per project, stored as SHA-256 (shown once, rotatable);
  every telemetry row carries `project_id`.
- **Rate limits:** sliding window per ingestion key (300/min) and per provider
  (20/min) — the latter also caps spend against free-tier quotas.
- **Budgets:** monthly USD budget per project; dashboard banners at 80% and 100%.

## 5 · Operational notes

- Postgres via psycopg3 with Django's native connection pool (`CONN_MAX_AGE=0` + pool,
  required under ASGI).
- All timestamps UTC (`USE_TZ`); ULID ids (client-generatable, time-ordered — index-
  friendly inserts and sortable ids in logs).
- Compose boot order is health-gated: postgres/kafka healthchecks → api (migrate,
  ensure_topics, bootstrap_demo, seed_demo) → worker/frontend.
- Tests: 41 across two suites — SDK (fail-open, overflow, retries, masking
  false-positives, wrapper streaming incl. abort) and server (validation, 207,
  idempotent replay, end-before-start, RBAC, rate limits, SSE chat via ASGI test
  client, Kafka-outage fallback via injected fake bus).
