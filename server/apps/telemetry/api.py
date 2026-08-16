import logging

from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import HttpRequest
from ninja import Router, Schema
from ninja.security import HttpBearer
from pydantic import ValidationError

from apps.projects.models import Project
from apps.telemetry import bus, persist
from apps.telemetry.ratelimit import SlidingWindowLimiter
from apps.telemetry.schemas import IngestEvent, IngestResponse, IngestResultItem

log = logging.getLogger(__name__)
router = Router(tags=["ingest"])

MAX_BATCH = 500
ingest_limiter = SlidingWindowLimiter(
    max_requests=int(settings.INGEST_RATE_LIMIT_PER_MIN), window_seconds=60
)


class IngestKeyAuth(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str):
        return Project.authenticate_key(token)


class IngestEnvelope(Schema):
    batch: list[dict]


class RateLimited(Schema):
    detail: str
    retry_after: float


@router.post(
    "/logs",
    auth=IngestKeyAuth(),
    response={202: IngestResponse, 207: IngestResponse, 400: dict, 429: RateLimited},
)
async def ingest_logs(request, envelope: IngestEnvelope):
    project: Project = request.auth
    allowed, retry_after = ingest_limiter.check(project.id)
    if not allowed:
        return 429, RateLimited(detail="ingestion rate limit exceeded", retry_after=retry_after)
    if not envelope.batch:
        return 400, {"detail": "empty batch"}
    if len(envelope.batch) > MAX_BATCH:
        return 400, {"detail": f"batch exceeds {MAX_BATCH} events"}

    results: list[IngestResultItem] = []
    mode = "queued"
    for item in envelope.batch:
        try:
            event = IngestEvent.model_validate(item)
            body = event.parsed_body()
        except ValidationError as exc:
            eid = str(item.get("id", "?")) if isinstance(item, dict) else "?"
            results.append(
                IngestResultItem(id=eid, status=400, error=str(exc.errors()[0]["msg"]))
            )
            continue
        payload = {
            "project_id": project.id,
            "event_id": event.id,
            "type": event.type,
            "body": body.dict(),
        }
        key = body.session_id or body.generation_id
        if not await bus.send_event(key, payload):
            mode = "direct"
            await sync_to_async(persist.persist_event)(project.id, event.type, body.dict())
        results.append(IngestResultItem(id=event.id, status=201))

    rejected = sum(1 for r in results if r.status >= 400)
    response = IngestResponse(
        accepted=len(results) - rejected, rejected=rejected, results=results, mode=mode
    )
    return (207 if rejected else 202), response
