# Architecture

One repository, three runtime services: `api` (Django on ASGI), `worker` (the Kafka
consumer), and `frontend` (nginx serving the React build and proxying `/api`). Behind
them, Kafka running in KRaft mode and PostgreSQL 17.

## 1. Ingestion flow

How an inference call becomes a row.

```
chat request ──► provider adapter ──► LLM provider (streaming)
                     │ wrapped by argus-sdk
                     │
        ┌────────────┴─────────────┐
        │ generation-start event   │  emitted the moment the call begins
        │ generation-end event     │  emitted at completion, error or abort
        └────────────┬─────────────┘
                     ▼  bounded queue, background thread, batched
        POST /api/v1/logs   Bearer argus_sk_…
                     │  per-item pydantic validation, 202 or 207
                     │  rate limited per key, max 500 events per batch
                     ▼
        Kafka topic `inference_events`, 8 partitions, key = session_id
                     │        same key means same partition, so start
                     │        always precedes end for a given generation
                     ▼
        consumer group `argus-persister`
        · getmany(≤500), persist idempotently, then commit offsets by hand
        · 3 attempts per event, then the DLQ topic `inference_events.dlq`
                     ▼
        Postgres `telemetry_inferencelog`
        · start  →  INSERT … ON CONFLICT DO NOTHING, status pending
        · end    →  fetch, merge, save (deterministic, so replay is safe)
```

Two events per generation rather than one is the decision most of this rests on. A single
event at completion would be simpler, but a request that hangs or crashes would then never
be logged at all, which is exactly the case you most want a record of. The start event
creates a pending row immediately; the end event merges into it.

If the Kafka produce fails, the API doesn't fail with it. It falls back to writing
straight to Postgres, logs a warning, and tells the caller `mode: "direct"` in the
response. Ingestion degrades, it doesn't stop.

On the read side, dashboard aggregates are ordinary Postgres queries (`percentile_cont`
for the latency percentiles, partial and BRIN indexes for the hot filters). The LIVE strip
on the Requests page is an SSE endpoint running a second Kafka consumer, group-less and
starting at the latest offset, so the same topic serves both persistence and the live UI.
Watching a row appear as pending and then resolve is the two-phase event model made
visible.

## 2. Logging strategy

The SDK's contract is one sentence: it must never raise into the host application, block
it, or slow it down. Everything else follows from that.

**Transport.** A bounded deque (10,000 events, drop-oldest with a counter) feeds a daemon
thread that flushes in batches of 20 or once a second, whichever comes first, with three
retries and backoff. A 4xx other than 429 is never retried, since retrying a validation
error just wastes both ends. There's an `atexit` flush, and a `flush()` for scripts that
exit fast. Every path is wrapped in suppress-and-log.

**Integration.** Client wrappers (`wrap_anthropic`, `wrap_openai`, `wrap_gemini`) patch
instance methods only, never the class, so wrapping one client doesn't affect another in
the same process. `wrap_openai` covers any OpenAI-compatible endpoint, which is how Groq
and xAI are supported. There's also a manual `client.generation(...)` context manager and
an `@observe` decorator for code that isn't a provider call. Per-call context rides along
as `argus_context={"session_id": …, "end_user_id": …}` and is popped before the provider
ever sees the kwargs.

**Masking** is a compiled-regex pipeline with checksum validation, applied before
truncation so that a card number split across the truncation boundary can't slip through.
Reasoning in ADR-7.

**Cost** comes from a static per-million-token price table, dated in the source, matched
by longest model prefix, with cached-input discounts applied. An unknown model leaves cost
null rather than reporting a confidently wrong number.

### What streaming actually costs you, per provider

This table is the part that took the longest to get right, and it's the reason the SDK
can't just be a stopwatch around the call.

| Provider | Where usage arrives | The trap |
|---|---|---|
| OpenAI-compatible (Groq, xAI, OpenAI) | a final extra chunk, and only if you send `stream_options={"include_usage": true}` — the SDK injects it | that chunk has an empty `choices` array, so the obvious `chunk.choices[0]` crashes on the one chunk you needed |
| Anthropic | split in two: `input_tokens` on `message_start`, final `output_tokens` and `stop_reason` on `message_delta` | TTFT has to be measured at the first `content_block_delta`; `message_start` arrives before any text and would flatter the number |
| Gemini | `usage_metadata` on every chunk, cumulative, so take the last one | thinking tokens arrive as `thoughts_token_count` and are billed as output, so they're tracked separately and added |
| all of them | — | an aborted stream never delivers a final usage frame, so usage is estimated and flagged with `tokens_estimated=true` |

Latency is three wall-clock timestamps (`started_at`, `first_chunk_at`, `completed_at`)
with `ttft_ms` and `latency_ms` derived from a monotonic clock, so a clock adjustment
mid-request can't produce a negative duration.

## 3. Chat service

Provider adapters implement one method, `stream(model, messages, …)` yielding text deltas,
and register themselves in a dict. Adding a provider is a class. The real adapters use
SDK-wrapped clients, which means the bundled chat app ships its telemetry through the same
public ingestion API a customer would use. I wanted the demo app to be a customer of the
SDK, not a special case inside it.

The chat endpoint is an async-generator `StreamingHttpResponse` under uvicorn: a `token`
event per delta, then `done` or `error`. When the user hits Stop, the client disconnects,
`CancelledError` is raised inside the generator, the partial assistant text is persisted,
and the SDK wrapper records the turn as aborted with estimated usage. Conversation context
is rebuilt from stored messages on every turn, so the server holds no per-session state and
any replica can serve any conversation. GZip middleware is deliberately not installed,
because it buffers streaming responses and would defeat the whole thing.

## 4. Security and tenancy

Users get session auth over an HttpOnly cookie with CSRF enforced by Ninja's SessionAuth.
Roles are `admin` and `member`, checked per-router, and a member's data access is scoped
inside the queries themselves rather than hidden in the UI.

Ingestion uses per-project bearer keys stored as SHA-256 hashes, displayed once at
creation and rotatable. Every telemetry row carries its `project_id`.

Rate limits are sliding-window, 300/minute per ingestion key and 20/minute per provider
key. The second one is as much about not running up a bill as about load.

Each project can carry a monthly USD budget, with dashboard banners at 80% and 100%.

The trust model is that the SDK is untrusted input. Everything it sends is re-validated at
ingestion.

## 5. Failure handling assumptions

What breaks, what happens, and what you lose. I'd rather write the losses down than imply
there aren't any.

| Failure | Behaviour | What's lost |
|---|---|---|
| Ingestion API unreachable from the SDK | three retries with backoff, then the batch is dropped, logged and counted; the host app never notices | up to one batch per retry cycle, bounded and observable |
| Host application crashes | the in-memory buffer dies with it | up to 10,000 buffered events, roughly the last second of traffic |
| Kafka down | the API writes synchronously to Postgres instead and reports `mode: "direct"` | nothing; ingestion responses just get slower |
| Worker down or crash-looping | events pile up in Kafka (7-day retention) and `/health` reports rising `consumer_lag`, visible in the UI footer | nothing; persistence is delayed, and offsets are only committed after a successful write |
| Broker not up yet when the worker starts | the worker retries the connection with capped backoff rather than exiting, so a cold start where everything boots at once settles on its own | nothing |
| Poison event that always raises | three attempts, then dead-lettered to `inference_events.dlq` with the error attached, offset committed | nothing; it's quarantined for inspection instead of blocking the partition |
| Duplicate delivery from at-least-once, retries or replay | unique `generation_id` plus a deterministic end-merge | nothing; `scripts/burst_demo.py` demonstrates it |
| Provider stream aborted mid-flight | recorded as aborted with estimated usage and `tokens_estimated=true` | nothing, but the token counts are flagged as estimates rather than presented as fact |
| Postgres down | the one dependency with no degraded mode: ingestion 500s, though events already in Kafka simply wait | nothing already in Kafka; SDK-side events retry and then drop as above |

## 6. Scaling considerations

In the order I'd actually reach for them.

1. **API.** Stateless, so horizontal replicas behind a load balancer. Sessions are
   database-backed already. The one thing that has to change is the rate limiter, which is
   in-process today and would need to move to Redis at more than one replica (ADR-9).
2. **Worker.** Add replicas up to the partition count, currently 8. Kafka rebalances
   ownership itself, and because the writes are idempotent, the redelivery that a rebalance
   causes is harmless.
3. **Kafka.** It's already the shock absorber for bursts of 10× to 100×; the burst script
   accepts on the order of 10,000 events/second on a laptop. Sustained growth means more
   partitions and brokers.
4. **Postgres.** Time-partition the log table and add retention drops, then rollup tables
   for the dashboard aggregates, and only then move analytics to ClickHouse while Postgres
   keeps the OLTP work. The trigger for that last step is in ADR-6, and it is a volume
   number rather than a feeling.
5. **Content.** Previews are capped today. Capturing full payloads would mean bodies in
   object storage with references in the rows, which is the same shape Langfuse v3 and
   Helicone settled on.

## 7. Operational notes

Postgres is reached through psycopg3 with Django's native connection pool, which under ASGI
means `CONN_MAX_AGE=0` plus the pool rather than persistent connections.

All timestamps are UTC. Primary keys are ULIDs: time-ordered, so inserts stay
index-friendly, and sortable when they show up in logs.

Compose boot order is health-gated. Postgres and Kafka come up healthy first, then the API
runs migrations, creates topics and seeds, then the worker and frontend start.

There are 47 tests across the two suites. The SDK side covers fail-open behaviour, queue
overflow, retries, masking false positives, and wrapper streaming including the abort case.
The server side covers validation, the 207 response, idempotent replay, an end event
arriving before its start, RBAC, rate limits, SSE chat through the ASGI test client, and
the Kafka-outage fallback using an injected fake bus.
