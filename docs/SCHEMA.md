# Schema design

Three tables covering two different jobs. `chat_session` and `chat_message` are ordinary
OLTP tables that hold conversation state for the chatbot. `telemetry_inferencelog` is
append-mostly and carries everything the ingestion pipeline and the dashboards work on.

```
chat_session 1 ──── n chat_message          (foreign key, cascade)
     │ id (ULID)          │ generation_id ┐
     └────────────────────┴───────────────┴──▶ telemetry_inferencelog.session_id
                          soft join, no FK                       .generation_id
```

## The telemetry table has no foreign keys into the chat tables

This is the decision people ask about first, so it goes first.

The SDK is meant for any application, not only the chatbot that ships in this repo. The
ingestion API therefore has to accept sessions and generations it has never heard of, from
a process it doesn't control, possibly out of order. A foreign key would make that a
constraint violation instead of a valid event.

So `session_id` is a denormalized string. Langfuse does the same thing, copying trace-level
attributes onto every observation row to keep ingestion decoupled and queries flat. The
chatbot happens to use the same ULIDs for its sessions, so the dashboard can still join
chat turns to telemetry whenever both sides exist, but nothing breaks when they don't.

## Typed columns for what you query, JSONB for the rest

Anything the dashboard filters, sorts or aggregates on is a real column with a real type:
provider, model, status, the three timestamps, the derived latencies, token counts, and
cost as `NUMERIC`. Provider-specific extras that nobody queries directly (system
fingerprints, safety ratings, raw usage breakdowns) go into `raw_metadata jsonb` under a
GIN `jsonb_path_ops` index, which is smaller and faster than the default `jsonb_ops` and
only supports containment queries, which is the only JSONB access this exposes anyway.

The two pure approaches both fail here. All-JSONB turns every dashboard aggregate into a
scan over untyped blobs. All-columns needs a migration every time a provider adds a field.
The hybrid is what everyone in this category ends up with.

## Field names follow the OTel GenAI conventions

Provider values and the token names (`input_tokens`, `output_tokens`, `cached_tokens`,
`reasoning_tokens`) mirror the current OpenTelemetry GenAI attribute registry. Note that
`gen_ai.system` and the `prompt_tokens`/`completion_tokens` pair were deprecated in semconv
v1.37; this uses the current names. It costs nothing today and means the table is
OTLP-export-ready instead of needing a translation layer later.

## `generation_id` is the idempotency key

A `generation-start` event inserts a pending row when a call begins, and `generation-end`
completes it. That's what makes in-flight calls visible on the live dashboard, and it means
a process that dies mid-generation still leaves a truthful record.

Because the Kafka pipeline is at-least-once, both writes have to be idempotent. Inserts use
`ON CONFLICT DO NOTHING` against the unique `generation_id`, and the end event is a
deterministic merge. Replaying either one produces the same row, which is what
`scripts/burst_demo.py` demonstrates by deliberately replaying part of its own load.

## Latency is three timestamps and two derived numbers

`started_at`, `first_chunk_at` and `completed_at` are the source of truth, all timestamptz
in UTC. `ttft_ms` and `latency_ms` are precomputed because they appear in essentially every
dashboard query and recomputing them per row per query is waste.

For a streaming response, time-to-first-token and total latency are completely different
numbers, and conflating them hides the metric users actually feel. TTFT is measured at the
first content delta, not the first SSE frame, because several providers send metadata
frames before any text.

## Previews, not full payloads

The full conversation text lives in `chat_message`, where it belongs to the product. The
telemetry row keeps masked, truncated previews only.

Three reasons: rows stay narrow, which matters for analytical scans; a breach of the
telemetry store has a much smaller blast radius than one that includes every prompt and
completion verbatim; and it matches the OTel default of not capturing message content
unless someone opts in.

Masking happens in the SDK before egress, so the previews arrive already masked.
`pii_masked` and `pii_entities_found[]` are stored as queryable columns, which turns "how
often does PII reach this system" into a metric rather than a footnote. For a liability and
audit use case that question is the whole point.

## Nullable telemetry columns, and a `tokens_estimated` flag

Token and cost columns are nullable on purpose. A generation that failed has no token
count, and writing zero would mean it produced nothing, which is a different and false
claim. Null means unknown, and the dashboards treat it that way.

Separately, an aborted stream never receives the provider's final usage frame, so its usage
is estimated and marked with `tokens_estimated`. Analytics can exclude or band those rows
instead of unknowingly averaging guesses with measurements.

## Indexes

| Index | Type | Why it exists |
|---|---|---|
| `generation_id` | unique btree | the idempotency backstop, and the fastest lookup for a single trace |
| `(session_id, started_at)` | btree | session replay and per-session aggregates |
| `(provider, request_model, started_at)` | btree | the dashboard's main group-bys |
| `(started_at)` | btree | time-bucketed charts and range filters |
| `(started_at) WHERE status='error'` | partial btree | error feeds touch a few percent of rows; a full index on a four-value `status` column would be close to useless, and the partial index is a fraction of the size |
| `(started_at)` | BRIN, `pages_per_range=64` | the table is append-only and time-ordered, so BRIN summarises whole page ranges at a tiny fraction of a btree's size and covers wide range scans |
| `raw_metadata` | GIN `jsonb_path_ops` | containment lookups into provider-specific metadata |

Both a btree and a BRIN index on `started_at` is intentional. They serve different queries:
the btree wins on narrow, recent lookups and on ordering, the BRIN costs almost nothing and
wins on the wide scans the charts do. `db/README.md` has the per-index detail.

## ULID primary keys

The SDK can mint an id without a round trip to the database, which matters when the whole
design is about not blocking the caller. They're globally unique and lexicographically
time-ordered, so primary key order roughly matches insert order and the index stays
append-friendly instead of suffering the random churn UUIDv4 causes. As a side benefit
they're sortable when they show up in logs.

## What changes at scale

Postgres serves both jobs comfortably at this volume and well beyond it. The failure mode
is documented rather than hypothetical: Langfuse ran this design and published what
happened at tens of thousands of events per minute, which was IOPS exhaustion as analytical
scans crawled over row-oriented, blob-heavy storage.

The path out, in order: declarative partitioning on `started_at` with retention drops, then
rollup tables for the hot dashboard queries, then move the log table to a columnar store
while Postgres keeps the OLTP work. More in DECISIONS.md, ADR-6.
