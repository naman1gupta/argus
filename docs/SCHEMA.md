# Schema Design & Rationale

Three tables across two concerns: **conversation state** (`chat_session`,
`chat_message` — OLTP, powers the chatbot) and **inference telemetry**
(`telemetry_inferencelog` — append-mostly, powers ingestion and analytics).

```
chat_session 1 ──── n chat_message          (FK, cascade)
     │ id (ULID)          │ generation_id ┐
     └────────────────────┴───────────────┴──▶ telemetry_inferencelog.session_id /
                          soft join, no FK      .generation_id
```

## Decisions and why

### 1. Telemetry has **no foreign keys** into chat tables
The SDK is designed for *any* application, not just our bundled chatbot — the
ingestion API must accept sessions and generations the chat app has never heard
of. `session_id` is a denormalized string (Langfuse does the same: trace-level
attributes are copied onto every observation row to keep queries fast and
ingestion decoupled). The chatbot's session ids happen to be the same ULIDs, so
the dashboard can still join chat turns to telemetry when both exist.

### 2. Typed columns for query dimensions, JSONB for the long tail
Everything the dashboard filters or aggregates on (provider, model, status,
latency, tokens, cost, timestamps) is a typed, indexable column. Provider-
specific extras that we don't query (system fingerprints, safety ratings, raw
usage breakdowns) go to `raw_metadata jsonb` with a GIN `jsonb_path_ops` index —
smaller and faster than the default `jsonb_ops`, at the cost of supporting only
containment queries (`@>`), which is the only JSONB access pattern we expose.
A pure-JSONB design would make every dashboard aggregate a full-scan over
untyped blobs; a pure-column design would need a migration for every provider
quirk. The hybrid is the standard resolution.

### 3. Column names follow OpenTelemetry GenAI semantic conventions
`provider` values and the token-count names (`input_tokens`, `output_tokens`,
`cached_tokens`, `reasoning_tokens`) mirror the current OTel GenAI attribute
registry (`gen_ai.provider.name`, `gen_ai.usage.input_tokens`, …; note
`gen_ai.system` and `prompt_tokens`/`completion_tokens` were deprecated in
semconv v1.37). Adopting the standard makes the schema OTLP-export-ready and
spares every future consumer a translation layer.

### 4. Two-phase writes with `generation_id` as the idempotency key
A `generation-start` event inserts a PENDING row when a call begins; the
`generation-end` event completes it. This makes in-flight calls visible in the
live dashboard (near-real-time is a product feature, not just a pipeline
property). The Kafka pipeline is at-least-once, so both writes are idempotent:
inserts use `ON CONFLICT DO NOTHING` on the unique `generation_id`; the end
event is a deterministic UPDATE — replaying either produces the same final row.

### 5. Latency stored as three timestamps + two derived milliseconds
`started_at` / `first_chunk_at` / `completed_at` are the source of truth
(timestamptz, UTC, `USE_TZ=True`); `ttft_ms` and `latency_ms` are precomputed
because they're on every dashboard query. For streaming responses TTFT
(time-to-first-token) and total latency are very different numbers, and TTFT is
measured at the first *content* delta — not the first SSE frame.

### 6. Previews, not full payloads
Full conversation text lives in `chat_message` where it belongs to the product.
The telemetry row stores masked, truncated previews only: keeps rows narrow for
analytics, limits blast radius of a telemetry-store breach, and matches the
OTel default of not capturing message content unless explicitly opted in.
Masking happens in the SDK **before egress** (previews arrive pre-masked);
`pii_masked` and `pii_entities_found[]` make redaction itself queryable — for
an audit/liability use case, "how often does PII hit this system" is a metric,
not a footnote.

### 7. `tokens_estimated` flag
Aborted streams never deliver the provider's final usage frame (OpenAI's
`include_usage` chunk, Anthropic's `message_delta`). Rather than dropping usage
or silently guessing, estimated counts are flagged — analytics can exclude or
band them.

### 8. Indexes
- `(session_id, started_at)` — session replay and per-session aggregates.
- `(provider, request_model, started_at)` — the dashboard's main group-bys.
- `(started_at)` — time-bucketed charts; would become BRIN if the table grew
  append-only into hundreds of millions of rows.
- Partial index on `started_at WHERE status='error'` — error feeds touch a tiny
  fraction of rows; a full index on `status` (4 values) would be near-useless.
- Unique `generation_id` — the idempotency backstop.

### 9. ULID primary keys
Client-generatable (the SDK mints ids without a round-trip), globally unique,
and lexicographically time-ordered — so PK order ≈ time order, which keeps
inserts append-friendly (no UUIDv4 index churn) and ids sortable in logs.

## What we'd change at scale
Postgres comfortably serves both OLTP and analytics at take-home and early-
production volumes. The documented failure mode (Langfuse ran exactly this
design and published the postmortem) arrives at ~tens of thousands of events
per minute: IOPS exhaustion on row-oriented storage under analytical scans.
The migration path, in order: (1) monthly/weekly declarative partitioning on
`started_at` + retention drops, (2) rollup tables for hot dashboard queries,
(3) move `inference_logs` to a columnar store (ClickHouse/Timescale) while
Postgres keeps OLTP — see DECISIONS.md.
