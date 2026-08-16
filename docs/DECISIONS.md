# Decision Records

Short ADRs: the decision, why, what was rejected, and the condition under which the
rejected option becomes right. Written before/while building, not after.

---

## ADR-1 · Kafka for the ingestion pipeline (vs Redis Streams vs Celery vs direct writes)

**Decision:** Ingestion accepts events, validates, and produces to a Kafka topic
(KRaft single broker, 8 partitions, key = `session_id`); a consumer group persists to
Postgres with manual offset commits after successful writes; poison messages go to a
DLQ topic after 3 attempts.

**Why:** (a) Partitioning by session gives per-conversation ordering — a
`generation-start` is never processed after its `generation-end`, without global
ordering costs. (b) At-least-once semantics are explicit: manual commits after
persistence + idempotent writes, visible in ~80 lines of consumer code rather than
hidden inside a task framework. (c) It absorbs bursts: the API acknowledges in
milliseconds regardless of DB write latency. (d) This is the production-proven shape
for exactly this workload — Helicone runs request/response logging through Kafka into
batched DB upserts.

**Rejected:** *Direct synchronous writes* — simplest, and kept as the degraded mode
(Kafka down → write-through with a warning; availability over purity), but couples
client-observed latency to DB health and drops the burst buffer. *Celery* — its Redis
broker is BRPOP-on-lists with a visibility-timeout redelivery hack; consumer-group
semantics, replay, and dead-lettering are hidden or absent, so it demonstrates
`.delay()` rather than event-driven design. *Redis Streams* — genuinely right-sized
for this scale (XREADGROUP/XACK/XAUTOCLAIM give similar semantics with a lighter
container) and the honest alternative; Kafka won on partition-key ordering, the DLQ
story, and operational familiarity.

**Flip condition:** if operational simplicity mattered more than ordering/throughput
semantics (e.g. a single-node deployment forever), Redis Streams; if volume grew to
Helicone scale, this design already is the scaled shape — add partitions/consumers.

## ADR-2 · Fail-open SDK with bounded buffering (vs guaranteed delivery)

**Decision:** The SDK never raises into, blocks, or slows the host app. Events go to a
bounded in-memory queue (10k, drop-oldest, counted); a daemon thread ships batches
(20 events / 1s, whichever first) with 3 retries + backoff; `atexit` flush; explicit
`flush()` for short-lived processes.

**Why:** Telemetry must never become the outage. An SDK that can throw or block on a
logging backend converts an observability incident into a product incident.

**Cost, quantified:** a hard crash can lose up to `queue_len` buffered events (bounded
by 10k or ~1s of traffic); an unreachable collector drops batches after retries. Both
are logged. Delivery is at-least-once (retries can duplicate), which is why ingestion
is idempotent end-to-end (ADR-4).

**Rejected:** durable client-side spooling (WAL file) — right for billing-grade
pipelines, heavy for an observability SDK; the same guarantee is provided server-side
by Kafka once an event is accepted.

## ADR-3 · Langfuse-style batch envelope with 207 Multi-Status

**Decision:** `POST /api/v1/logs` takes `{batch: [{id, timestamp, type, body}]}`.
Each item validates independently; the response is `202` (all accepted) or `207` with
per-item `{id, status, error}`. Envelope `id` (event identity, dedup) is distinct from
`body.generation_id` (entity identity, upsert key).

**Why:** one malformed event must not reject a batch of good ones — batching clients
otherwise lose valid data or retry-loop entire batches. The event-id/entity-id split
is what makes "two events, one row" (start/end) idempotent. This mirrors Langfuse's
public ingestion contract, the de-facto standard for this product category.

## ADR-4 · Two-phase events (start/end) with idempotent persistence

**Decision:** The SDK emits `generation-start` at request time and `generation-end` at
completion. Starts insert `PENDING` rows (`ON CONFLICT DO NOTHING` on unique
`generation_id`); ends are a deterministic merge; end-before-start creates a stub the
late start can't overwrite. Replaying any event yields the same final row.

**Why:** (a) in-flight calls are visible in the live dashboard — "near-real-time"
becomes a product feature, not just a pipeline property; (b) crashes leave a
truthful `pending` record instead of nothing; (c) at-least-once delivery (ADR-1/2)
demands idempotency anyway, so the write path is designed for replay from the start.

## ADR-5 · Django Ninja (vs Django REST Framework)

**Decision:** Django Ninja for all APIs.

**Why:** native `async def` endpoints (the SSE chat stream and Kafka live-tail
endpoints are async generators; DRF is sync-only), pydantic-v2 validation on the hot
ingestion path (Rust-core parsing of nested JSON), and OpenAPI/Swagger for free at
`/api/v1/docs`. Still 100% Django: ORM, migrations, auth, middleware unchanged.

**Rejected:** DRF — the safe idiomatic default and the right call in an existing DRF
codebase; for a greenfield service whose two hottest endpoints are async streaming and
high-frequency JSON validation, Ninja is the technically stronger fit (cf. Kogan.com's
published DRF→Ninja migration). Session-cookie auth still enforces CSRF via Ninja's
SessionAuth.

## ADR-6 · Postgres only (vs adding ClickHouse/Timescale)

**Decision:** One Postgres serves both OLTP (users, sessions, projects) and analytics
(inference_logs), with typed columns + JSONB and targeted indexes (see SCHEMA.md).

**Why:** at take-home/early-production volume (even 100k events/day) Postgres has
enormous headroom; a second database would be resume-driven complexity. The failure
mode is known precisely: Langfuse ran this exact design and published the postmortem —
at tens of thousands of events *per minute*, ingestion latency spiked to ~50s on IOPS
exhaustion and analytical scans over blob-heavy rows.

**Scale path (in order):** time-based declarative partitioning + retention drops →
rollup tables for dashboard aggregates → move `inference_logs` to a columnar store
(ClickHouse) while Postgres keeps OLTP — i.e. Langfuse v3's architecture.

## ADR-7 · Masking client-side, before egress (vs server-side only)

**Decision:** PII masking runs inside the SDK, before truncation and before any byte
leaves the host process: prefix-anchored secrets (API keys, JWTs) → checksummed
numerics (credit cards via Luhn, Aadhaar via Verhoeff, SSN with exclusion rules) →
pattern entities (email, Indian mobile, IPv4). Entities found are stored as a
queryable column; `log_content=False` omits content entirely (metadata still flows).

**Why:** the industry consensus (Langfuse mask hook, OTel GenAI content-off-by-default)
is that sensitive data should never leave the producing environment in raw form —
server-side scrubbing is defense-in-depth, not the primary control. Checksums kill the
false positives that make bare regex masking noisy (a random 16-digit order id fails
Luhn; ZIP+4 is excluded from SSN). Honest limitation, documented: person names and
addresses need NER — Microsoft Presidio is the production path (its ~750MB spaCy model
is a poor fit for a demo image).

## ADR-8 · Wrapper instrumentation (vs proxy vs global monkey-patching)

**Decision:** `wrap_anthropic(client)` / `wrap_openai(client)` / `wrap_gemini(client)`
return the same client with instance methods instrumented; nothing global is mutated.
A manual `generation()` context manager and `@observe` cover non-standard cases.

**Why:** a proxy (Helicone-style base_url swap) is the easiest integration but puts
the logger in the request critical path — a telemetry outage becomes an LLM outage,
the exact inverse of ADR-2. Global monkey-patching is magic at a distance and the most
fragile surface across SDK upgrades. Instance wrapping is explicit, composable, and
testable; per-call context (`argus_context={session_id, end_user_id}`) is popped
before kwargs reach the provider.

**The hard-won details** (per-provider streaming usage capture) are documented in
ARCHITECTURE.md: OpenAI's usage-bearing final chunk has an empty `choices` array;
Anthropic splits usage across `message_start`/`message_delta`; Gemini's
`usage_metadata` is cumulative on every chunk; TTFT is measured at the first *content*
delta; aborted streams get estimated usage with a `tokens_estimated` flag.

## ADR-9 · In-memory rate limiting (vs shared store)

**Decision:** Sliding-window limiters per ingestion key and per provider, in-process.

**Why:** correct for a single api instance (this deployment); zero moving parts.
Honest caveat: at N instances the effective limit is N×; the fix is the same algorithm
over a shared store (Redis) — noted for the scale path rather than adding a Redis
dependency solely for this.

## ADR-10 · OTel GenAI semantic conventions for field names

**Decision:** Column/field names follow the current OpenTelemetry GenAI registry:
`gen_ai.provider.name` values (`anthropic`, `gcp.gemini`, …), `input_tokens` /
`output_tokens` (not the deprecated `prompt_tokens`/`completion_tokens`),
`time_to_first_chunk` semantics for TTFT.

**Why:** makes the data OTLP-export-ready and spares every future consumer a
translation layer. Note: the conventions renamed `gen_ai.system` →
`gen_ai.provider.name` in semconv v1.37 (Aug 2025); we adopt the current names.

## Deliberately out of scope

Google OAuth (login is designed to swap: any authenticated Django backend works),
Prometheus `/metrics` + Grafana (ops layer; the product dashboard was the deliverable),
Slack/email alerting, retention policies, head-based sampling (SDK has `sample_rate`;
server-side controls at scale), OTLP export endpoint, multi-instance rate limiting,
ClickHouse (ADR-6). Chosen to keep every shipped line reviewable and defended.
