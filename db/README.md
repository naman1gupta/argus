# Database

PostgreSQL 17. The schema is **owned by Django migrations** — they are the
versioned, ordered, reviewable change history that runs on every deploy. The raw
DDL is exported here so the schema can be read (or applied) without running the
application.

| File | What it is |
|---|---|
| [`schema.sql`](schema.sql) | Full DDL exported from the running database with `pg_dump --schema-only` — tables, constraints, every index. Apply with `psql "$DATABASE_URL" -f db/schema.sql` when a DBA provisions the database outside the app. |
| `../server/apps/*/migrations/` | The migration history Django applies (`manage.py migrate`, run automatically on container start). |

Regenerate the DDL after a schema change:

```bash
docker compose exec -T postgres pg_dump -U argus --schema-only --no-owner --no-privileges argus > db/schema.sql
```

Inspect the SQL a migration will execute before it runs:

```bash
docker compose exec -T api python manage.py sqlmigrate telemetry 0001
```

## Tables

| Table | Rows are | Notes |
|---|---|---|
| `telemetry_inferencelog` | one LLM inference call | the hot table: written by the pipeline, read by every dashboard |
| `chat_session` / `chat_message` | conversation + turns | OLTP for the bundled chat app |
| `projects_project` | tenant scope + ingestion key | key stored as SHA-256, never plaintext |
| `accounts_user` | operator accounts | custom user model with a `role` column (admin/member) |
| `django_session` | login sessions | DB-backed, so API replicas are stateless |

## `telemetry_inferencelog` — the design decisions

**Hybrid typed columns + JSONB.** Everything the dashboards filter, sort or
aggregate on is a real typed column (`provider`, `request_model`, `status`,
`latency_ms`, `ttft_ms`, `input_tokens`, `output_tokens`, `cost_usd`,
`started_at`). Only the open-ended tail lives in `raw_metadata JSONB`. Pure JSONB
would have been faster to write and much slower to query — you cannot cheaply
`percentile_cont` over a JSON field, and every dashboard query would degrade into
a full scan.

**`generation_id UNIQUE` is the idempotency key.** Kafka delivery is at-least-once,
so the same event can arrive twice. The unique constraint plus
`bulk_create(ignore_conflicts=True)` on the start event and a deterministic merge
on the end event mean replaying any event yields the same row — proven by
`scripts/burst_demo.py`, which deliberately re-sends a batch.

**ULID primary keys.** Time-ordered like a sequence, unique like a UUID, and
generatable client-side. Inserts stay at the right edge of the B-tree instead of
scattering random UUIDs across pages, and IDs sort chronologically, which is what
makes the cursor pagination on `/insights/logs` work with a plain `id < before`.

**`cost_usd NUMERIC(12,8)`** — not a float. Sub-cent per-call costs summed over
millions of rows is exactly where binary floating point drifts.

**`timestamptz` everywhere** (`USE_TZ=True`), all infrastructure in UTC. Three
separate timestamps are stored — `started_at`, `first_chunk_at`, `completed_at` —
because time-to-first-token and total latency are different SLOs for streaming.

**Nullable telemetry columns are deliberate.** A failed call has no token counts;
an aborted stream has estimated ones flagged by `tokens_estimated`. Storing 0
would silently corrupt cost and latency aggregates, so absent data stays `NULL`.

**Denormalized `session_id` / `project_id` / `end_user_id`, no FK to sessions.**
The SDK is usable by *any* application, so telemetry regularly references sessions
this database has never seen. Foreign keys would reject valid third-party data;
the trade-off is that grouping by session is an index scan rather than a join.

### Indexes and why each exists

| Index | Serves |
|---|---|
| `telemetry_inferencelog_pkey` | ULID primary key |
| `generation_id` UNIQUE | idempotent upserts (the ingestion contract) |
| `inflog_session_time (session_id, started_at)` | session replay + per-conversation aggregates |
| `inflog_provider_model_time (provider, request_model, started_at)` | "cost by model", model comparison, provider filters |
| `inflog_project_time (project_id, started_at)` | tenant-scoped dashboards |
| `inflog_errors_time (started_at) WHERE status='error'` | **partial index** — error dashboards touch ~2% of rows, so the index stays tiny |
| `inflog_started_brin (started_at)` USING BRIN | **BRIN** on an append-only, time-correlated column: range scans over 7/30-day windows at a fraction of a B-tree's size |
| `inflog_meta_gin (raw_metadata)` USING GIN `jsonb_path_ops` | containment queries on the metadata blob; `jsonb_path_ops` is smaller and faster than the default opclass (it supports `@>` but not key-existence — a deliberate trade) |

### Scale path

Documented in [`../docs/DECISIONS.md`](../docs/DECISIONS.md) (ADR-6) and
[`../docs/SCHEMA.md`](../docs/SCHEMA.md): time-based declarative partitioning of
`telemetry_inferencelog` with retention drops → rollup tables for dashboard
aggregates → move analytics to a columnar store (ClickHouse) while Postgres keeps
OLTP. Postgres was kept single-store here deliberately; Langfuse ran this exact
design to tens of thousands of events per minute before splitting, and their
published postmortem is what informs the trigger points above.
