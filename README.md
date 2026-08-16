# Argus — LLM Inference Logging System

> Every inference. Captured, measured, accountable.
>
> A chatbot, an auto-instrumenting SDK, an event-driven ingestion pipeline, and an
> observability dashboard — built as one product. Logging is treated not as debugging
> exhaust but as **evidence**: the telemetry an AI system needs to be observable,
> auditable, and ultimately insurable.

```
 React SPA ──► Chat (SSE streaming) ──► Anthropic / Gemini / Groq / Mock
    │                │
    │           argus-sdk  (wraps the provider clients; fail-open, background batching,
    │                │      PII masking, cost estimation — zero changes to call sites)
    │                ▼
    │           POST /api/v1/logs   (Bearer key · batch envelope · 207 multi-status
    │                │               · per-key rate limiting · direct-write fallback)
    │                ▼
    │           Kafka  (topic partitioned by session_id · DLQ · manual commits)
    │                ▼
    │           consumer worker ──► PostgreSQL (idempotent two-phase writes)
    │                                   │
    └──── Dashboard APIs ◄─────────────┘        + SSE live tail straight off the topic
```

## Run it (Docker, no API keys needed)

The only prerequisite is Docker (Desktop or any engine with compose v2) — no local
Python, Node, Kafka, or Postgres required.

```bash
git clone https://github.com/naman1gupta/argus.git && cd argus
cp .env.example .env
docker compose up --build
```

Then open **http://localhost:3000**. Log in and explore — every feature below works
with zero API keys.

The default **mock provider deliberately echoes your message rather than answering it**:
it exists so the full system (SDK capture → Kafka → dashboards) is demoable without
credentials, not to be a chatbot. For real model responses, put `GROQ_API_KEY`,
`GEMINI_API_KEY` or `ANTHROPIC_API_KEY` into `.env` (Groq and Gemini both have free
tiers) and pick that provider in the chat's model selector — the same SDK instrumentation
captures all of them.

| Login | Password | Role |
|---|---|---|
| `admin` | `argus-admin` | Everything: dashboards, traces, sessions, projects & keys |
| `member` | `argus-member` | RBAC-scoped: chat + their own usage only |

First boot runs migrations, creates topics, seeds the demo users/project, and loads
~6,000 realistic telemetry events (7 days, incl. a simulated error-burst incident) so
the dashboards are alive from the first click. Demo rows are tagged `environment=demo`.

## Demo video

A 2½-minute silent walkthrough (captioned) is included with the submission:
login and RBAC → dashboards → chat streaming and mid-stream cancel → the Kafka-backed
live request tail → trace detail with PII masking → session replay → projects,
API keys and budget alerts.

## A guided tour (what to click, in order)

**1 · Log in as `admin`** — note the RBAC hint on the login screen.

**2 · Dashboard** — KPI row (requests, cost, avg latency, p95 TTFT, error rate) with
period-over-period deltas; requests-by-outcome and **latency percentile (p50/p95/p99)**
charts; cost by model; token usage; top error types; a **risk signals** panel
(PII masked counts by entity, aborted streams, SLO breaches); and a model comparison
table. Switch the **1h / 24h / 7d / 30d** range — the 7d view shows the seeded incident
spike. A red banner appears when a project exceeds its monthly **cost budget**.

**3 · Requests** — the near-real-time log. The **LIVE** section is an SSE feed consumed
*directly off the Kafka topic*: keep this page open, send a chat message in another tab,
and watch it land — first as `pending` (the generation-start event), then resolving with
its final status. Filter by provider/status, or full-text search. **Click any row**: the
trace drawer shows a TTFT→streaming waterfall, token/cost tiles, masked prompt/response
previews (try sending a message containing an email or a card number — they arrive as
`‹EMAIL›` / `‹CREDIT_CARD›`, masked in the SDK *before leaving the process*), and the raw
record. Every trace has a **shareable URL** (`/requests/<generation_id>`).

**4 · Chat** — the demo workload. Pick a provider/model (mock needs no key), send a
message, watch it stream. Press **Stop** mid-stream: the turn is marked `aborted ·
partial · usage estimated`, and the telemetry row records estimated tokens — aborted
streams never deliver the provider's final usage frame, so Argus flags rather than
guesses. Include the words `trigger error` to demo the error path. Conversations are
listed on the left — click one to **resume** it with full context.

**5 · Sessions** — conversations reconstructed from telemetry. Pick a session for a
chat-style **replay** with per-turn chips (model, TTFT, latency, tokens, cost, PII
badge → *view trace*), plus session totals. **⬇ Export evidence CSV** produces a
per-session audit trail — the "incident report" for one conversation.

**6 · Projects & keys** — telemetry is scoped per project. Create a project (the
ingestion key is shown **once**; only its SHA-256 is stored), rotate keys, and set a
monthly budget (set it below current spend to see the dashboard alert). The SDK
quickstart at the bottom is the 30-second integration story.

**7 · Sign out → log in as `member`** — the nav collapses to **Chat + My usage**;
admin routes redirect away. *My usage* shows the member their own requests, tokens
burned, cost, and conversations.

**8 · Toggle ☀︎/☾** — full light/dark theming. The layout is responsive down to
mobile widths (hamburger nav, scrollable tables).

## What's implemented vs. the brief

| Requirement | Where |
|---|---|
| Chatbot with multi-turn context + UI | `web/` + `server/apps/chat` (SSE streaming, cancel/resume, context window rebuilt per turn) |
| SDK capturing inference metadata, automatic instrumentation | `sdk/` — `argus-sdk`, wraps Anthropic / OpenAI-compatible / Gemini clients; also a manual API + `@observe` |
| Ingestion service (validate → persist, near-real-time) | `server/apps/telemetry` — batch envelope, pydantic validation, 207 per-item results, Kafka → consumer → Postgres |
| Database schema | `server/apps/*/models.py`, rationale in [docs/SCHEMA.md](docs/SCHEMA.md) |
| **Bonus** multi-provider | Anthropic + Gemini + Groq + mock, behind one adapter interface (any OpenAI-compatible endpoint works via `base_url`) |
| **Bonus** streaming | End-to-end: provider → SSE chat → per-provider streaming usage capture (incl. TTFT and the aborted-stream case) |
| **Bonus** monitoring dashboards | Dashboard page: percentiles, cost, tokens, errors, risk signals |
| **Bonus** event-driven pattern | Kafka (KRaft), partition-by-session ordering, manual commits, DLQ, degraded direct-write mode |
| **Bonus** sensitive-data masking | Regex + checksum (Luhn, Verhoeff) masking in the SDK before egress; queryable `pii_entities_found` |
| **Bonus** containerized deployment | `docker-compose.yml` (5 services) |
| **Bonus** Kubernetes deployment | `deploy/k8s/argus.yaml` — **verified running on a local kind cluster** (app + Postgres + Kafka, 5 pods); steps below |
| Extras | Auth + RBAC, per-project hashed API keys, rate limiting (ingestion + provider), cost budget alerts, evidence CSV export, live tail, seeded demo data, light/dark, responsive |

## Repository layout

```
sdk/       argus-sdk — pip-installable Python SDK (own test suite)
server/    Django 5 + Django Ninja — chat, ingestion, insights APIs, Kafka consumer
web/       React 19 + TypeScript + Tailwind + React Query + Recharts
docs/      ARCHITECTURE.md · SCHEMA.md · DECISIONS.md (ADRs)
deploy/    Kubernetes manifests
```

One codebase, three runtime services: **api** (ASGI), **worker** (Kafka consumer),
**frontend** (nginx serving the SPA + proxying `/api`).

## SDK in 30 seconds

```python
pip install argus-sdk          # in this repo: pip install -e sdk

import argus, anthropic
argus.init(endpoint="http://localhost:8000/api/v1", api_key="argus_sk_...",
           session_id=conversation_id, end_user_id=user_id)

client = argus.wrap_anthropic(anthropic.Anthropic())
# use the client exactly as before — every call, streaming included, is logged:
# provider, model, latency, TTFT, tokens (real usage frames), cost, errors,
# masked content previews. The SDK is fail-open: it can never raise into,
# block, or slow down your application. argus.flush() before exit in scripts.
```

## Development & tests

```bash
docker compose up -d postgres kafka
cd server && python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate && .venv/bin/python manage.py bootstrap_demo
.venv/bin/python manage.py ensure_topics && .venv/bin/python manage.py seed_demo
.venv/bin/uvicorn config.asgi:application --port 8000      # terminal 1
.venv/bin/python manage.py consume_events                  # terminal 2
cd web && npm install && npm run dev                       # terminal 3 → :5173

# tests (41): SDK fail-open/masking/wrappers + API validation/idempotency/RBAC/SSE
cd server && .venv/bin/python -m pytest        # server suite
cd sdk && ../server/.venv/bin/python -m pytest # sdk suite
```

Interactive API docs (Swagger) at **http://localhost:8000/api/v1/docs**.

Stress-test the pipeline (needs `pip install httpx`; watch consumer lag in the UI footer):

```bash
python scripts/burst_demo.py --events 2000 --key argus_sk_dev-chat-key-change-me
```

## Troubleshooting

- **Port already in use**: the app uses 3000 (UI) and 8000 (API). Postgres/Kafka host
  ports are only for host-based dev and can be remapped without touching the app:
  `POSTGRES_HOST_PORT=5433 KAFKA_HOST_PORT=29093 docker compose up`.
- **Reset everything** (fresh DB + reseed): `docker compose down -v && docker compose up`.
- **Watch the pipeline**: `docker compose logs -f worker` while you chat.

## Run it on Kubernetes (self-hosted)

Verified end-to-end on a local [kind](https://kind.sigs.k8s.io) cluster — the same
manifests target any cluster (swap `imagePullPolicy: Never` for a registry, and the
emptyDir volumes for PVCs).

```bash
kind create cluster --name argus
docker compose build                                            # builds argus-api / argus-frontend
kind load docker-image argus-api:latest argus-frontend:latest --name argus
kubectl apply -f deploy/k8s/argus.yaml
kubectl rollout status deploy/argus-api
kubectl port-forward svc/argus-frontend 8080:80                 # → http://localhost:8080
```

Deploys 5 pods: `argus-api` (ASGI, with a migrate/seed init container), `argus-worker`
(Kafka consumer), `argus-frontend` (nginx + SPA), plus single-node `postgres` and
`kafka`. Two details worth noting — both real bugs found while verifying: pods set
`enableServiceLinks: false` (Kubernetes otherwise injects `POSTGRES_PORT=tcp://…` for
the postgres Service, clobbering the app's own env var), and the API readiness probe
is an exec probe sending an explicit `Host` header, so `ALLOWED_HOSTS` stays strict
instead of being widened to accept the kubelet's pod-IP requests.

## Design notes

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — ingestion flow, SDK internals, streaming mechanics
- [docs/SCHEMA.md](docs/SCHEMA.md) — schema rationale, indexing, scale path
- [docs/DECISIONS.md](docs/DECISIONS.md) — ADRs: Kafka vs Redis Streams vs Celery, Ninja vs DRF, Postgres vs ClickHouse, 207 multi-status, fail-open trade-offs, masking placement, and what changes at 100× scale

## What I'd improve with more time

Documented as future work rather than half-built: Google OAuth, Prometheus `/metrics` +
Grafana, alerting channels (Slack/email), retention policies, OTLP export, sampling
controls, table partitioning → ClickHouse at scale. Details in DECISIONS.md.
