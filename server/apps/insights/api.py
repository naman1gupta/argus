import asyncio
import csv
import io
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.models import (
    Avg,
    Count,
    DecimalField,
    Max,
    Min,
    Q,
    Sum,
)  # fmt: skip
from django.db.models.functions import Coalesce
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from ninja import Router, Schema

from apps.accounts.security import admin_auth, session_auth
from apps.chat.models import Message, Session
from apps.projects.models import Project
from apps.telemetry.models import InferenceLog

log = logging.getLogger(__name__)
router = Router(tags=["insights"])

SLO_MS = 10_000
ZERO = DecimalField(max_digits=12, decimal_places=8)


def _since(hours: int):
    return timezone.now() - timedelta(hours=hours)


def _base(hours: int, project_id: str | None = None):
    qs = InferenceLog.objects.filter(started_at__gte=_since(hours))
    if project_id:
        qs = qs.filter(project_id=project_id)
    return qs


def _kpis(qs) -> dict:
    agg = qs.aggregate(
        requests=Count("id"),
        errors=Count("id", filter=Q(status="error")),
        cost=Coalesce(Sum("cost_usd"), 0, output_field=ZERO),
        avg_latency=Avg("latency_ms"),
        input_tokens=Coalesce(Sum("input_tokens"), 0),
        output_tokens=Coalesce(Sum("output_tokens"), 0),
    )
    agg["error_rate"] = (agg["errors"] / agg["requests"] * 100) if agg["requests"] else 0.0
    agg["cost"] = float(agg["cost"])
    return agg


@router.get("/overview", auth=admin_auth)
def overview(request, hours: int = 24, project_id: str | None = None):
    current = _kpis(_base(hours, project_id))
    prev_qs = InferenceLog.objects.filter(
        started_at__gte=_since(hours * 2), started_at__lt=_since(hours)
    )
    if project_id:
        prev_qs = prev_qs.filter(project_id=project_id)
    previous = _kpis(prev_qs)
    ttft = list(
        _base(hours, project_id)
        .filter(ttft_ms__isnull=False)
        .values_list("ttft_ms", flat=True)
        .order_by("ttft_ms")
    )
    current["p95_ttft"] = ttft[int(len(ttft) * 0.95)] if ttft else None
    current["streaming_pct"] = (
        _base(hours, project_id).filter(is_streaming=True).count() / current["requests"] * 100
        if current["requests"]
        else 0
    )
    return {"current": current, "previous": previous}


@router.get("/timeseries", auth=admin_auth)
def timeseries(request, hours: int = 24, project_id: str | None = None):
    step = max(int(hours * 3600 / 48), 120)  # ~48 buckets
    where, params = "started_at >= %s", [step, step, _since(hours)]
    if project_id:
        where += " AND project_id = %s"
        params.append(project_id)
    with connection.cursor() as cur:
        cur.execute(
            f"""
            SELECT to_timestamp(floor(extract(epoch FROM started_at) / %s) * %s) AS bucket,
                   count(*) FILTER (WHERE status = 'success')       AS ok,
                   count(*) FILTER (WHERE status = 'error')         AS err,
                   percentile_cont(0.5)  WITHIN GROUP (ORDER BY latency_ms) AS p50,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95,
                   percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99,
                   coalesce(sum(input_tokens), 0)  AS tokens_in,
                   coalesce(sum(output_tokens), 0) AS tokens_out,
                   coalesce(sum(cost_usd), 0)      AS cost
            FROM telemetry_inferencelog
            WHERE {where}
            GROUP BY bucket ORDER BY bucket
            """,
            params,
        )
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    for r in rows:
        r["bucket"] = r["bucket"].isoformat()
        r["cost"] = float(r["cost"])
    return {"step_seconds": step, "buckets": rows}


@router.get("/models", auth=admin_auth)
def models(request, hours: int = 24, project_id: str | None = None):
    rows = (
        _base(hours, project_id)
        .values("provider", "request_model")
        .annotate(
            requests=Count("id"),
            errors=Count("id", filter=Q(status="error")),
            cost=Coalesce(Sum("cost_usd"), 0, output_field=ZERO),
            avg_latency=Avg("latency_ms"),
            avg_ttft=Avg("ttft_ms"),
            input_tokens=Coalesce(Sum("input_tokens"), 0),
            output_tokens=Coalesce(Sum("output_tokens"), 0),
        )
        .order_by("-cost")
    )
    out = []
    for r in rows:
        r["cost"] = float(r["cost"])
        r["error_rate"] = r["errors"] / r["requests"] * 100 if r["requests"] else 0
        out.append(r)
    return out


@router.get("/errors", auth=admin_auth)
def errors(request, hours: int = 24, project_id: str | None = None):
    return list(
        _base(hours, project_id)
        .filter(status="error")
        .exclude(error_type="")
        .values("error_type")
        .annotate(count=Count("id"))
        .order_by("-count")[:8]
    )


@router.get("/risk", auth=admin_auth)
def risk(request, hours: int = 24, project_id: str | None = None):
    qs = _base(hours, project_id)
    entity_counts: dict[str, int] = {}
    for entities in qs.filter(pii_masked=True).values_list("pii_entities_found", flat=True):
        for e in entities:
            entity_counts[e] = entity_counts.get(e, 0) + 1
    return {
        "pii_events": qs.filter(pii_masked=True).count(),
        "pii_entities": sorted(entity_counts.items(), key=lambda kv: -kv[1]),
        "aborted_streams": qs.filter(status="aborted").count(),
        "slo_breaches": qs.filter(latency_ms__gt=SLO_MS).count(),
        "tokens_estimated": qs.filter(tokens_estimated=True).count(),
    }


@router.get("/budgets", auth=admin_auth)
def budgets(request):
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    out = []
    for p in Project.objects.all():
        spend = InferenceLog.objects.filter(
            project_id=p.id, started_at__gte=month_start
        ).aggregate(c=Coalesce(Sum("cost_usd"), 0, output_field=ZERO))["c"]
        budget = float(p.monthly_budget_usd) if p.monthly_budget_usd else None
        out.append(
            {
                "project_id": p.id,
                "name": p.name,
                "month_spend": float(spend),
                "budget": budget,
                "exceeded": budget is not None and float(spend) >= budget,
                "warning": budget is not None and float(spend) >= 0.8 * budget,
            }
        )
    return out


class BudgetIn(Schema):
    monthly_budget_usd: float | None


@router.patch("/budgets/{project_id}", auth=admin_auth)
def set_budget(request, project_id: str, payload: BudgetIn):
    Project.objects.filter(id=project_id).update(monthly_budget_usd=payload.monthly_budget_usd)
    return {"ok": True}


@router.get("/logs", auth=admin_auth)
def logs(
    request,
    hours: int = 24,
    provider: str = "",
    model: str = "",
    status: str = "",
    session_id: str = "",
    end_user_id: str = "",
    q: str = "",
    limit: int = 50,
    before: str = "",
):
    qs = _base(hours)
    if provider:
        qs = qs.filter(provider=provider)
    if model:
        qs = qs.filter(request_model=model)
    if status:
        qs = qs.filter(status=status)
    if session_id:
        qs = qs.filter(session_id=session_id)
    if end_user_id:
        qs = qs.filter(end_user_id=end_user_id)
    if q:
        qs = qs.filter(
            Q(prompt_preview__icontains=q)
            | Q(response_preview__icontains=q)
            | Q(generation_id__icontains=q)
            | Q(session_id__icontains=q)
        )
    if before:
        qs = qs.filter(id__lt=before)
    limit = min(limit, 200)
    rows = list(qs.order_by("-id")[:limit].values())
    return {"rows": rows, "next_before": rows[-1]["id"] if len(rows) == limit else None}


@router.get("/logs/{generation_id}", auth=admin_auth)
def log_detail(request, generation_id: str):
    row = InferenceLog.objects.filter(generation_id=generation_id).values().first()
    return row or (404, {"detail": "not found"})


@router.get("/sessions", auth=admin_auth)
def sessions(request, hours: int = 168, limit: int = 50):
    rows = (
        _base(hours)
        .exclude(session_id="")
        .values("session_id")
        .annotate(
            requests=Count("id"),
            errors=Count("id", filter=Q(status="error")),
            cost=Coalesce(Sum("cost_usd"), 0, output_field=ZERO),
            tokens=Coalesce(Sum("input_tokens"), 0) + Coalesce(Sum("output_tokens"), 0),
            avg_latency=Avg("latency_ms"),
            first_at=Min("started_at"),
            last_at=Max("started_at"),
            end_user_id=Max("end_user_id"),
        )
        .order_by("-last_at")[: min(limit, 200)]
    )
    out = list(rows)
    titles = dict(
        Session.objects.filter(id__in=[r["session_id"] for r in out]).values_list("id", "title")
    )
    for r in out:
        r["cost"] = float(r["cost"])
        r["title"] = titles.get(r["session_id"], "")
    return out


@router.get("/sessions/{session_id}", auth=admin_auth)
def session_replay(request, session_id: str):
    messages = list(
        Message.objects.filter(session_id=session_id)
        .order_by("seq")
        .values("id", "role", "content", "provider", "model", "seq", "created_at")
    )
    logs = list(InferenceLog.objects.filter(session_id=session_id).order_by("started_at").values())
    title = Session.objects.filter(id=session_id).values_list("title", flat=True).first() or ""
    return {"session_id": session_id, "title": title, "messages": messages, "logs": logs}


@router.get("/sessions/{session_id}/evidence.csv", auth=admin_auth)
def evidence_csv(request, session_id: str):
    """Per-session audit trail export — the 'incident report' for one conversation."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "generation_id", "started_at", "completed_at", "provider", "model", "status",
        "latency_ms", "ttft_ms", "input_tokens", "output_tokens", "cost_usd",
        "pii_entities_masked", "error_type", "finish_reasons",
    ])  # fmt: skip
    for r in InferenceLog.objects.filter(session_id=session_id).order_by("started_at"):
        writer.writerow([
            r.generation_id, r.started_at.isoformat(),
            r.completed_at.isoformat() if r.completed_at else "",
            r.provider, r.request_model, r.status, r.latency_ms, r.ttft_ms,
            r.input_tokens, r.output_tokens, r.cost_usd,
            "|".join(r.pii_entities_found), r.error_type, "|".join(r.finish_reasons),
        ])  # fmt: skip
    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="evidence_{session_id}.csv"'
    return response


@router.get("/my/usage", auth=session_auth)
def my_usage(request, hours: int = 720):
    qs = _base(hours).filter(end_user_id=request.auth.username)
    kpis = _kpis(qs)
    ttft = list(
        qs.filter(ttft_ms__isnull=False).values_list("ttft_ms", flat=True).order_by("ttft_ms")
    )
    kpis["p95_ttft"] = ttft[int(len(ttft) * 0.95)] if ttft else None
    recent = list(
        Session.objects.filter(user=request.auth)
        .annotate(message_count=Count("messages"))
        .values("id", "title", "updated_at", "message_count")[:10]
    )
    return {"kpis": kpis, "recent_sessions": recent}


@router.get("/tail", auth=admin_auth)
async def tail(request):
    """SSE live tail straight off the Kafka topic (offset = SSE id)."""
    from aiokafka import AIOKafkaConsumer

    async def stream():
        consumer = AIOKafkaConsumer(
            settings.KAFKA_EVENTS_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=None,
            auto_offset_reset="latest",
            value_deserializer=lambda v: json.loads(v.decode()),
        )
        try:
            await consumer.start()
        except Exception as exc:  # noqa: BLE001
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n".encode()
            return
        try:
            yield b": connected\n\n"
            while True:
                batches = await consumer.getmany(timeout_ms=10_000, max_records=100)
                if not batches:
                    yield b": keepalive\n\n"
                    continue
                for tp, records in batches.items():
                    for r in records:
                        payload = json.dumps(r.value)
                        sse_id = f"{tp.partition}-{r.offset}"
                        yield f"id: {sse_id}\nevent: log\ndata: {payload}\n\n".encode()
        except asyncio.CancelledError:
            raise
        finally:
            await consumer.stop()

    response = StreamingHttpResponse(stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
