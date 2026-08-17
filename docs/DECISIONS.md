# Decision records

Ten decisions that shaped this build. For each one: what I chose, why, what I turned down,
and what would have to be true for me to choose differently. I wrote these while building,
not afterwards, which is why a couple of them admit the alternative was close.

---

## ADR-1. Kafka for the ingestion pipeline

Ingestion accepts events, validates them, and produces to a Kafka topic. Single broker in
KRaft mode, 8 partitions, keyed by `session_id`. A consumer group persists to Postgres and
commits offsets by hand after the write succeeds. Poison messages go to a dead-letter topic
after three attempts.

The partition key is doing real work. Keying by session means a `generation-start` is never
processed after its matching `generation-end`, and I get that ordering without paying for
global ordering. Beyond that, at-least-once semantics are explicit here rather than
implied: manual commits after persistence, idempotent writes, and about 80 lines of
consumer code you can read end to end instead of a task framework's internals. And the API
acknowledges in milliseconds no matter how slow the database is, which is the whole point
of putting a log in front of a write. This is also the shape the category has converged on;
Helicone runs request and response logging through Kafka into batched database upserts.

I rejected three alternatives. **Direct synchronous writes** are the simplest thing that
works, and I kept them as the degraded mode when Kafka is unavailable, but as the primary
path they tie client-observed latency to database health and give up the burst buffer.
**Celery** would have been fewer moving parts, but its Redis broker is BRPOP on lists with
a visibility-timeout redelivery hack; consumer groups, replay and dead-lettering are either
hidden or absent, so I'd have been demonstrating `.delay()` rather than event-driven
design. **Redis Streams** is the honest alternative and genuinely right-sized for this
volume — XREADGROUP, XACK and XAUTOCLAIM give you similar semantics in a much lighter
container. Kafka won on partition-key ordering, the dead-letter story, and the fact that I
have operated it before.

If operational simplicity mattered more than ordering and throughput, say a single-node
deployment that will never grow, I'd take Redis Streams. If volume grew toward Helicone
scale, this design is already the scaled shape; you add partitions and consumers.

## ADR-2. A fail-open SDK with bounded buffering

The SDK never raises into the host application, never blocks it, and never slows it down.
Events go into a bounded in-memory queue (10,000, drop-oldest, with a counter), and a
daemon thread ships batches of 20 or once a second, whichever comes first, with three
retries and backoff. There's an `atexit` flush and an explicit `flush()` for short-lived
processes.

The reasoning is that telemetry must never become the outage. An SDK that can throw or
block on its logging backend turns an observability problem into a product incident, and
the customer never signed up for that trade.

The cost is real and I'd rather quantify it than gloss it: a hard crash loses whatever is
in the queue, bounded by 10,000 events or roughly a second of traffic, and an unreachable
collector drops batches after its retries. Both are logged and counted. Delivery is
at-least-once, since retries can duplicate, which is exactly why ingestion is idempotent
end to end (ADR-4).

I considered durable client-side spooling to a write-ahead file. That's the right answer
for a billing-grade pipeline where every event is money, and too heavy for an observability
SDK. Once an event has been accepted, Kafka provides the same guarantee server-side.

## ADR-3. A batch envelope with 207 Multi-Status

`POST /api/v1/logs` takes `{batch: [{id, timestamp, type, body}]}`. Every item validates
independently and the response is either 202, if all were accepted, or 207 with a per-item
`{id, status, error}`.

One malformed event must not reject a batch of good ones. Without per-item results a
batching client either loses valid data or retry-loops the whole batch forever, and in both
cases it can't tell you which event was the problem.

The envelope `id` and `body.generation_id` are deliberately different things: the first is
event identity, used for deduplication, and the second is entity identity, used as the
upsert key. Keeping them separate is what makes "two events, one row" work. The shape
follows Langfuse's public ingestion contract, which is the closest thing this category has
to a standard.

## ADR-4. Two-phase events with idempotent persistence

The SDK emits `generation-start` when the request begins and `generation-end` when it
finishes, errors or is aborted. Starts insert a pending row with `ON CONFLICT DO NOTHING`
against the unique `generation_id`; ends are a deterministic merge. An end that somehow
arrives before its start creates a stub that the late start is not allowed to overwrite.
Replaying any event produces the same final row.

Three reasons. In-flight calls become visible in the live dashboard, which turns
"near-real-time" into something you can watch rather than a property of the pipeline. A
crash mid-generation leaves a truthful pending record instead of nothing at all. And since
at-least-once delivery was already a given, the write path had to be replay-safe regardless,
so I designed for it from the first migration instead of bolting it on.

## ADR-5. Django Ninja rather than Django REST Framework

Ninja for all the APIs.

The two hottest endpoints in this system are an SSE chat stream and a Kafka live tail, both
async generators, and DRF is sync-only. Ninja gives native `async def`, pydantic v2
validation on the ingestion path (which is the highest-frequency JSON parsing in the app,
and pydantic's Rust core matters there), and OpenAPI at `/api/v1/docs` for free. It's still
entirely Django underneath: same ORM, migrations, auth and middleware.

DRF is the safe, idiomatic default and I'd use it without hesitating inside an existing DRF
codebase. For a greenfield service shaped like this one, Ninja is the better technical fit.
Session-cookie auth still enforces CSRF through Ninja's SessionAuth, so nothing was traded
away on security.

## ADR-6. One Postgres, no ClickHouse

A single Postgres serves both the OLTP tables (users, sessions, projects) and the analytical
one (inference logs), using typed columns plus JSONB and a small number of targeted indexes.

At this volume, and honestly at a hundred thousand events a day, Postgres has enormous
headroom. A second datastore would be complexity I couldn't justify to anyone who had to
operate it.

What makes me comfortable is that the failure mode is documented rather than guessed at.
Langfuse ran this exact design and published the postmortem: at tens of thousands of events
per minute, ingestion latency spiked to around 50 seconds as IOPS were exhausted and
analytical scans crawled over blob-heavy rows.

So the scale path is known and ordered: time-based declarative partitioning with retention
drops, then rollup tables for the dashboard aggregates, and only then move the log table to
a columnar store while Postgres keeps the OLTP work. That last step is Langfuse v3's
architecture, arrived at the same way.

## ADR-7. Masking in the SDK, before egress

PII masking runs inside the SDK, before truncation and before any byte leaves the host
process. The order is prefix-anchored secrets first (API keys, JWTs), then checksummed
numerics (credit cards through Luhn, Aadhaar through Verhoeff, SSN with exclusion rules),
then pattern entities (email, Indian mobile, IPv4). The entities found are stored as a
queryable column, and `log_content=False` drops content entirely while metadata keeps
flowing.

The consensus in this space, from Langfuse's mask hook to OTel GenAI defaulting content
off, is that sensitive data should never leave the producing environment in raw form.
Server-side scrubbing is defence in depth, not the primary control.

Checksums are what make it usable. Bare regex masking is noisy enough that people turn it
off: a random 16-digit order ID fails Luhn and is left alone, and ZIP+4 is excluded from the
SSN pattern. Masking runs before truncation so a card number straddling the truncation
boundary can't escape as two harmless-looking halves.

The limitation, stated plainly: names and addresses need NER, and this doesn't do that.
Microsoft Presidio is the production answer, and its roughly 750MB spaCy model is a bad fit
for an image people are meant to pull and run in a few minutes.

## ADR-8. Wrapper instrumentation rather than a proxy

`wrap_anthropic(client)`, `wrap_openai(client)` and `wrap_gemini(client)` hand back the same
client with its instance methods instrumented. Nothing global is mutated. A manual
`generation()` context manager and an `@observe` decorator cover anything that isn't a
provider call.

A proxy, the Helicone-style base-URL swap, is the easiest integration story to sell, and it
puts the logger directly in the request's critical path. That is precisely the inverse of
ADR-2: a telemetry outage would become an LLM outage. Global monkey-patching is magic at a
distance and the most fragile thing to maintain across provider SDK upgrades. Instance
wrapping is explicit, composable and testable, and per-call context is popped from kwargs
before the provider client ever sees it.

The details that took the longest here, the per-provider streaming usage quirks, are in
ARCHITECTURE.md rather than repeated: OpenAI's usage-bearing final chunk carries an empty
`choices` array, Anthropic splits usage across two event types, Gemini's `usage_metadata`
is cumulative on every chunk, TTFT has to be measured at the first content delta, and
aborted streams get estimated usage behind a `tokens_estimated` flag.

## ADR-9. In-memory rate limiting

Sliding-window limiters per ingestion key and per provider key, held in process.

This is correct for a single API instance, which is what this deployment is, and it costs
nothing to operate. The caveat is straightforward: at N instances the effective limit
becomes N times the configured one. The fix is the same algorithm over Redis, and I've
noted it on the scale path rather than adding a Redis dependency to this repo for one
feature.

## ADR-10. OTel GenAI naming for fields

Column and field names follow the current OpenTelemetry GenAI semantic conventions:
`gen_ai.provider.name` values like `anthropic` and `gcp.gemini`, `input_tokens` and
`output_tokens` rather than the deprecated `prompt_tokens` and `completion_tokens`, and
time-to-first-chunk semantics for TTFT.

It costs nothing now and it means the data is OTLP-export-ready, so nobody downstream has
to write a translation layer. Worth noting that the conventions renamed `gen_ai.system` to
`gen_ai.provider.name` in semconv v1.37, and this uses the current names.

## Deliberately left out

Google OAuth (the login is built to swap: any authenticated Django backend works), a
Prometheus `/metrics` endpoint with Grafana, Slack and email alerting, retention policies,
server-side sampling controls (the SDK has `sample_rate` already), an OTLP export endpoint,
multi-instance rate limiting, and ClickHouse.

Each of those is a real thing a production version needs. I left them out so that every
line that did ship is one I can explain.
