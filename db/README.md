# Database

PostgreSQL 17. The schema is owned by Django migrations, since those are the versioned,
ordered, reviewable history that actually runs on deploy. The raw DDL is exported here as
well so the schema can be read, or applied, without running the application at all.

| File | What it is |
|---|---|
| [`schema.sql`](schema.sql) | The full DDL, exported from the running database with `pg_dump --schema-only`: tables, constraints and every index. Apply it with `psql "$DATABASE_URL" -f db/schema.sql` if a DBA provisions the database outside the app. |
| `../server/apps/*/migrations/` | The migration history Django applies, run automatically on container start. |

Regenerate the DDL after a schema change:

```bash
docker compose exec -T postgres pg_dump -U argus --schema-only --no-owner --no-privileges argus > db/schema.sql
```

See the SQL a migration will run, before it runs:

```bash
docker compose exec -T api python manage.py sqlmigrate telemetry 0001
```

## Tables

| Table | A row is | Notes |
|---|---|---|
| `telemetry_inferencelog` | one LLM inference call | the hot table: written by the pipeline, read by every dashboard |
| `chat_session` / `chat_message` | a conversation and its turns | OLTP for the bundled chat app |
| `projects_project` | a tenant scope and its ingestion key | the key is stored as SHA-256, never in plaintext |
| `accounts_user` | an operator account | custom user model with a `role` column |
| `django_session` | a login session | database-backed, so API replicas stay stateless |

## Why `telemetry_inferencelog` looks the way it does

**Typed columns with a JSONB tail.** Everything the dashboards filter, sort or aggregate on
is a real typed column: `provider`, `request_model`, `status`, `latency_ms`, `ttft_ms`,
the token counts and `cost_usd`. Only the provider-specific tail that nobody queries directly
goes into `raw_metadata`. Pure JSONB would have been quicker to write and much slower to
live with, because you can't cheaply run `percentile_cont` over a JSON field and every
dashboard query would decay into a full scan.

**`generation_id UNIQUE` is the idempotency key.** Kafka delivery is at-least-once, so the
same event will arrive twice sooner or later. The unique constraint, plus
`ignore_conflicts=True` on the start event and a deterministic merge on the end event, means
replaying any event lands on the same row. `scripts/burst_demo.py` proves it by re-sending
part of its own batch on purpose.

**ULID primary keys.** Time-ordered like a sequence, unique like a UUID, and generatable
client-side without a round trip. Inserts stay at the right edge of the B-tree instead of
scattering random UUIDs across pages, and because the IDs sort chronologically, the cursor
pagination on `/insights/logs` is a plain `id < before` rather than a keyset over two
columns.

**`cost_usd` is `NUMERIC(12,8)`, not a float.** Sub-cent per-call costs summed over millions
of rows is exactly the situation where binary floating point drifts, and "our spend report
is off by a few dollars and we don't know why" is not a bug I want to debug later.

**`timestamptz` everywhere, UTC everywhere.** Three separate timestamps are stored
(`started_at`, `first_chunk_at`, `completed_at`) because for a streaming response
time-to-first-token and total latency are two different SLOs and collapsing them loses the
one users feel.

**Nullable telemetry columns are deliberate.** A failed call has no token count, and an
aborted stream has an estimated one flagged by `tokens_estimated`. Writing 0 instead would
quietly corrupt every cost and latency aggregate downstream, so missing data stays NULL and
the dashboards render the gap.

**`session_id`, `project_id` and `end_user_id` are denormalized, with no FK to the chat
tables.** The SDK is meant to be used by any application, so telemetry routinely references
sessions this database has never seen. A foreign key would reject perfectly valid
third-party data. The trade is that grouping by session is an index scan rather than a
join, which the `(session_id, started_at)` index handles.

## Every index, and what it's for

| Index | Serves |
|---|---|
| `telemetry_inferencelog_pkey` | the ULID primary key |
| `generation_id` UNIQUE | idempotent upserts, and the fastest path to one trace |
| `inflog_session_time (session_id, started_at)` | session replay and per-conversation aggregates |
| `inflog_model_time (provider, request_model, started_at)` | cost by model, the model comparison table, provider filters |
| `telemetry_inferencelog_project_id_*` | tenant-scoped queries |
| `inflog_errors_time (started_at) WHERE status='error'` | a partial index. Errors are a couple of percent of rows and are always queried on their own, so the index stays tiny. A full index on a four-value `status` column would barely earn its keep |
| `inflog_time (started_at)` | the default dashboard window filter and ordering |
| `inflog_started_brin (started_at)` BRIN | the table is append-only and time-correlated, so BRIN stores per-block ranges instead of per-row pointers. It's a fraction of a B-tree's size and covers the 7 and 30-day scans well |
| `inflog_meta_gin (raw_metadata)` GIN `jsonb_path_ops` | containment queries into metadata. `jsonb_path_ops` is smaller and faster than the default opclass and supports `@>` but not key-existence, which is a trade I made knowingly since containment is the only JSONB access the API exposes |

Keeping both a B-tree and a BRIN index on `started_at` is intentional rather than an
oversight. They win on different queries: the B-tree on narrow recent lookups and ordering,
BRIN on the wide range scans behind the charts, at almost no storage cost.

## Scale path

Set out in [`../docs/DECISIONS.md`](../docs/DECISIONS.md) (ADR-6) and
[`../docs/SCHEMA.md`](../docs/SCHEMA.md): declarative time partitioning with retention
drops, then rollup tables for the dashboard aggregates, then analytics onto a columnar store
while Postgres keeps the OLTP work.

Postgres was kept as a single store here on purpose. Langfuse ran this same design up to
tens of thousands of events per minute before splitting, and their published postmortem is
where the trigger points above come from rather than my own guesswork.
