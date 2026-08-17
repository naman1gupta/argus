# Argus — LLM Inference Logging System

Argus is a chatbot, a Python SDK that instruments it, an ingestion service behind Kafka,
and a dashboard that reads the result. I built the four pieces as one product because
the interesting problems only show up where they meet: what the SDK can't measure, the
dashboard can't show.

The framing I worked to: an inference log is evidence. If you want to say something
useful about how an AI system behaved (to an auditor, an insurer, or the customer who
got a bad answer), you need the request, the timing, the tokens, the cost, and the
failure, tied to a session, and you need it to still be there after the process that
produced it has gone.

```
 React SPA ──► Chat API (SSE) ──► Groq · Gemini · Anthropic · OpenAI · xAI · Mock
    │                │
    │           argus-sdk    wraps the provider client, never blocks it, masks PII
    │                ▼
    │           POST /api/v1/logs    bearer key, batch envelope, 207 per-item results
    │                ▼
    │           Kafka    partitioned by session_id, manual commits, dead-letter topic
    │                ▼
    │           consumer worker ──► PostgreSQL    idempotent two-phase writes
    │                                   │
    └──── Dashboard APIs ◄─────────────┘         + an SSE live tail off the topic
```

## Running it

Docker is the only prerequisite. No local Python, Node, Kafka or Postgres.

```bash
git clone https://github.com/naman1gupta/argus.git && cd argus
cp .env.example .env
docker compose up --build
```

Open http://localhost:3000.

| Login | Password | Role |
|---|---|---|
| `admin` | `argus-admin` | dashboards, traces, sessions, projects and keys |
| `member` | `argus-member` | chat and their own usage, nothing else |

First boot migrates the database, creates the Kafka topics, makes the two users and a
project, and seeds about 6,000 telemetry events spread over seven days (including a
simulated error burst) so the dashboards have something to show before you've done
anything. Seeded rows are tagged `environment=demo` if you want to filter them out.

Everything works without an API key. The built-in mock provider echoes your message back
instead of answering it, which is deliberate: it exists so the pipeline is reviewable
with zero credentials, not to be a chatbot. For real answers, drop a `GROQ_API_KEY` or
`GEMINI_API_KEY` into `.env` (both have free tiers) and pick that model in the chat.
The same SDK instrumentation captures all of them.

## A tour, in the order I'd click it

**Log in as `admin`.**

**Dashboard.** KPIs with period-over-period deltas, requests by outcome, latency as
p50/p95/p99, cost by model, token usage, top errors, and a risk-signals panel (PII
caught, aborted streams, SLO breaches). Switch the range to 7d and the seeded incident
spike appears. If a project passes its monthly budget, a banner shows up here.

**Requests.** Every inference call. The LIVE strip is an SSE feed consumed straight off
the Kafka topic, so if you leave this page open and chat in another tab you'll watch the
row arrive as `pending` and then resolve. Click a row for the trace: a TTFT-to-completion
waterfall, tokens, cost, and the masked prompt and response. Send yourself a message
with an email address or a card number in it and you'll see them stored as `‹EMAIL›` and
`‹CREDIT_CARD›`, masked inside the SDK before anything left the process. Each trace has
its own URL, so you can paste one into a ticket.

**Chat.** The workload that generates all of the above. Pick a provider, send something,
watch it stream. Hit Stop mid-answer and the turn is marked aborted with usage estimated,
because no provider sends you a final usage frame after you hang up on it, and I'd rather
flag that than quietly guess. Type `trigger error` at the mock provider to see the error
path. Past conversations are listed on the left and resume with their full context.

**Sessions.** Conversations rebuilt from telemetry alone and replayed turn by turn, with
per-turn model, latency, tokens and cost. The evidence CSV export is the audit trail for
a single conversation.

**Projects & keys.** Telemetry is scoped per project. Create one and the ingestion key is
shown exactly once; only its SHA-256 is stored. Set a monthly budget below current spend
and go back to the dashboard to see the alert fire.

**Sign out, log back in as `member`.** The nav collapses to Chat and My usage, and the
admin routes redirect. The restriction is enforced in the API, not just hidden in the UI.

## What the brief asked for, and where it is

| Requirement | Where |
|---|---|
| Chatbot with multi-turn context and a UI | `web/` and `server/apps/chat` — SSE streaming, cancel, resume |
| SDK that captures inference metadata automatically | `sdk/` — wraps Anthropic, Gemini and any OpenAI-compatible client; manual API and an `@observe` decorator too |
| Ingestion service, validate then persist, near real time | `server/apps/telemetry` — batch envelope, pydantic validation, 207 per-item results, Kafka to consumer to Postgres |
| Database schema | `server/apps/*/models.py`, reasoning in [docs/SCHEMA.md](docs/SCHEMA.md) and [db/README.md](db/README.md) |
| Bonus: multi-provider | Six behind one adapter interface. Any OpenAI-compatible endpoint is a subclass with a `base_url` |
| Bonus: streaming | Provider to SSE to browser, with per-provider usage capture and TTFT, including the aborted case |
| Bonus: dashboards | Percentiles, cost, tokens, errors, risk signals, model comparison |
| Bonus: event-driven | Kafka on KRaft, partitioned by session, manual commits, DLQ, degraded direct-write fallback |
| Bonus: sensitive-data masking | Regex plus checksums (Luhn, Verhoeff) in the SDK before egress; `pii_entities_found` is queryable |
| Bonus: containerized | `docker-compose.yml`, five services |
| Bonus: Kubernetes | `deploy/k8s/argus.yaml`, verified on a kind cluster |
| Beyond the brief | Auth and RBAC, hashed per-project keys, rate limiting on ingestion and provider keys, budget alerts, evidence export, live tail, seeded data, light/dark, responsive layout |

## Layout

```
sdk/       argus-sdk, pip-installable, its own test suite
server/    Django 5 + Django Ninja: chat, ingestion, insights, Kafka consumer
web/       React 19 + TypeScript + Tailwind + React Query + Recharts
db/        schema.sql (full DDL) and the index rationale
docs/      ARCHITECTURE · SCHEMA · DECISIONS · MODELS
deploy/    Kubernetes manifests
scripts/   burst_demo.py, the throughput and idempotency proof
```

One codebase, three runtime services: `api` (ASGI), `worker` (the Kafka consumer), and
`frontend` (nginx serving the SPA and proxying `/api`).

## The SDK

```python
pip install argus-sdk          # from this repo: pip install -e sdk

import argus, anthropic
argus.init(endpoint="http://localhost:8000/api/v1", api_key="argus_sk_...",
           session_id=conversation_id, end_user_id=user_id)

client = argus.wrap_anthropic(anthropic.Anthropic())
```

Then use the client exactly as you did before. Every call, streaming included, records
provider, model, latency, TTFT, real token counts, cost and errors, with masked previews
of the content. The SDK is fail-open: it cannot raise into your code, block it, or slow
it down. In a short-lived script call `argus.flush()` before you exit.

## Schema, in brief

PostgreSQL 17. The schema is owned by Django migrations and applied on start.

The main table is `telemetry_inferencelog`, and it's deliberately hybrid: the fields you
filter, sort and aggregate on are real typed columns (provider, model, status, latency,
tokens, `NUMERIC` cost), and everything provider-specific goes in a JSONB `metadata`
column with a GIN `jsonb_path_ops` index. Primary keys are ULIDs, so they sort by
creation time and can be generated client-side without a round trip.

`generation_id` carries a unique constraint, and that one constraint is what makes the
whole pipeline safe: Kafka is at-least-once, so the consumer will occasionally see the
same event twice, and the write collapses instead of duplicating. Telemetry columns are
nullable on purpose, because a generation that failed genuinely has no token count and I
didn't want zeros standing in for missing data.

Three indexes worth calling out: a partial index over errors only (they're a few percent
of rows and always queried alone), a BRIN index on `started_at` (the table is append-only
and time-ordered, so BRIN costs almost nothing and covers every range query), and the GIN
index on metadata. [db/README.md](db/README.md) goes through all of them, and
[db/schema.sql](db/schema.sql) is the full DDL from `pg_dump --schema-only`.

## Trade-offs I made

**Kafka rather than Redis Streams or Celery.** Partition-by-session gives me ordering
where ordering actually matters (the start and end events of one generation), and a real
dead-letter topic. Celery would have been fewer moving parts, but its broker hides the
exact mechanics — offsets, lag, replay — that are the point of an ingestion pipeline.
The cost is honest: Kafka is the heaviest thing in the compose file.

**The SDK is fail-open, not guaranteed-delivery.** Telemetry must never take down the
application it's watching. So the queue is bounded, and when it's full events are dropped
and counted rather than blocking the caller. That loses data in a hard crash. I decided a
bounded, measured loss window beats an unbounded risk to the host application, and the
window is written down rather than hand-waved.

**Wrapper instrumentation, not a proxy.** A proxy is easier to sell, but it puts the
logger in the request's critical path, which is the exact opposite of fail-open.

**207 multi-status on ingestion.** One malformed event in a batch of fifty shouldn't
reject the other forty-nine, and the client needs to know which one broke.

**Django Ninja over DRF.** Async endpoints for SSE, pydantic validation on the hot
ingestion path, and OpenAPI for free.

**One Postgres, no ClickHouse.** At this size Postgres is the right answer and a second
datastore would be a liability. The point where that flips, and the order I'd do the
migration in, is written down in DECISIONS.md instead of pre-built.

**Masking in the SDK, before egress.** Sensitive data never leaves the producing process
in the clear. Card numbers are Luhn-checked and Aadhaar numbers Verhoeff-checked first,
so order IDs don't get false-flagged.

## Tests and development

```bash
docker compose up -d postgres kafka
cd server && python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate && .venv/bin/python manage.py bootstrap_demo
.venv/bin/python manage.py ensure_topics && .venv/bin/python manage.py seed_demo
.venv/bin/uvicorn config.asgi:application --port 8000      # terminal 1
.venv/bin/python manage.py consume_events                  # terminal 2
cd web && npm install && npm run dev                       # terminal 3, port 5173

cd server && .venv/bin/python -m pytest         # 21 tests
cd sdk && ../server/.venv/bin/python -m pytest  # 24 tests
```

45 tests in total, covering SDK fail-open behaviour, masking and the provider wrappers on
one side, and ingestion validation, idempotency, RBAC and SSE on the other. CI runs both
suites plus lint and a web build on every push.

Swagger is at http://localhost:8000/api/v1/docs.

To push load through the pipeline and watch consumer lag in the UI footer:

```bash
python scripts/burst_demo.py --events 2000 --key argus_sk_dev-chat-key-change-me
```

The burst deliberately replays a slice of its own events, so the row count coming out is
lower than the event count going in. That difference is the idempotency proof.

## Troubleshooting

Ports 3000 and 8000 need to be free. The Postgres and Kafka host ports are only there for
host-based development and can be moved: `POSTGRES_HOST_PORT=5433 KAFKA_HOST_PORT=29093
docker compose up`.

To start over: `docker compose down -v && docker compose up`.

To watch the pipeline work: `docker compose logs -f worker` while you chat.

## Kubernetes

Verified on a local [kind](https://kind.sigs.k8s.io) cluster. The same manifests target a
real cluster once you swap `imagePullPolicy: Never` for a registry and the emptyDir
volumes for PVCs.

```bash
kind create cluster --name argus
docker compose build
kind load docker-image argus-api:latest argus-frontend:latest --name argus
kubectl apply -f deploy/k8s/argus.yaml
kubectl rollout status deploy/argus-api
kubectl port-forward svc/argus-frontend 8080:80
```

Five pods: api (with a migrate-and-seed init container), worker, frontend, Postgres and
Kafka. Two details in there are fixes for real bugs I hit while verifying. Pods set
`enableServiceLinks: false`, because Kubernetes otherwise injects `POSTGRES_PORT=tcp://…`
for the postgres Service and clobbers the app's own environment variable. And the API
readiness probe is an exec probe that sends an explicit `Host` header, so `ALLOWED_HOSTS`
can stay strict instead of being widened to accept the kubelet's pod-IP requests.

## Providers

Groq, Google Gemini, Anthropic, OpenAI and xAI sit behind one adapter interface, plus the
keyless mock. The default is `groq` / `llama-3.3-70b-versatile`, set by `DEFAULT_PROVIDER`
and `DEFAULT_MODEL` and falling back to the mock when no key is present. Anthropic, OpenAI
and xAI have no free tier, so I haven't bundled keys for them; their adapters are complete
and appear in the picker marked "no key". Adding a key to `.env` activates them with no
code change. Full matrix in [docs/MODELS.md](docs/MODELS.md).

## Further reading

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — ingestion flow, logging strategy, scaling, failure handling
- [docs/DECISIONS.md](docs/DECISIONS.md) — the ADRs, each with what I rejected and what would change my mind
- [docs/SCHEMA.md](docs/SCHEMA.md) — schema reasoning and the scale path
- [db/README.md](db/README.md) — DDL and index-by-index rationale
- [docs/MODELS.md](docs/MODELS.md) — providers, default model, cost attribution

## What I'd do with more time

I'd rather name these than half-build them: Google OAuth instead of username/password,
a Prometheus `/metrics` endpoint with Grafana dashboards, alerting into Slack or email,
retention and downsampling policies, OTLP export so this can feed an existing observability
stack, sampling controls for high-volume tenants, and table partitioning as the first step
on the road to a columnar store. The reasoning for each is in DECISIONS.md.
