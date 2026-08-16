# Argus — LLM Inference Logging System

> Observability → auditability → insurability: capture every LLM inference with
> zero code changes, stream it through an event pipeline, and turn it into
> queryable evidence.

**Status: under active development.** Full README (quickstart, architecture,
feature tour) lands with the final submission.

## Layout

```
sdk/     argus-sdk — auto-instrumentation SDK (pip-installable, fail-open)
server/  Django (Ninja) — chat backend, ingestion API, query APIs, Kafka consumer
web/     React (Vite + TS) — chat UI + observability dashboard
docs/    Architecture, schema rationale, decision records
deploy/  Kubernetes manifests
```

## Quickstart (dev)

```bash
cp .env.example .env        # works with zero API keys via the mock provider
docker compose up -d postgres kafka
cd server && python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate
.venv/bin/uvicorn config.asgi:application --port 8000
# in another shell:
cd web && npm install && npm run dev
```
