import asyncio
import json
import logging
from datetime import datetime

from django.conf import settings
from django.http import StreamingHttpResponse
from ninja import Router, Schema
from ninja.errors import HttpError

from apps.accounts.security import session_auth
from apps.chat.models import Message, Session
from apps.chat.providers import (
    ADAPTERS,
    ProviderError,
    available_providers,
    default_selection,
)
from apps.projects.models import Project
from apps.telemetry.ratelimit import SlidingWindowLimiter

log = logging.getLogger(__name__)
router = Router(tags=["chat"], auth=session_auth)

CONTEXT_TURNS = 20
provider_limiter = SlidingWindowLimiter(
    max_requests=int(settings.PROVIDER_RATE_LIMIT_PER_MIN), window_seconds=60
)


class SessionOut(Schema):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class MessageOut(Schema):
    id: str
    role: str
    content: str
    generation_id: str | None
    provider: str
    model: str
    created_at: datetime


class SendIn(Schema):
    content: str
    provider: str = "mock"
    model: str = "argus-demo-1"


@router.get("/providers")
def providers(request):
    provider, model = default_selection()
    return {
        "providers": available_providers(),
        "default": {"provider": provider, "model": model},
    }


@router.get("/sessions", response=list[SessionOut])
def list_sessions(request):
    rows = Session.objects.filter(user=request.auth).prefetch_related("messages")
    return [
        SessionOut(
            id=s.id, title=s.title, created_at=s.created_at,
            updated_at=s.updated_at, message_count=len(s.messages.all()),
        )  # fmt: skip
        for s in rows
    ]


@router.post("/sessions", response={201: SessionOut})
def create_session(request):
    s = Session.objects.create(user=request.auth, project=Project.objects.first())
    return 201, SessionOut(
        id=s.id, title=s.title, created_at=s.created_at, updated_at=s.updated_at
    )


@router.get("/sessions/{session_id}/messages", response=list[MessageOut])
def session_messages(request, session_id: str):
    session = _own_session(request, session_id)
    return list(session.messages.all())


@router.delete("/sessions/{session_id}")
def delete_session(request, session_id: str):
    _own_session(request, session_id).delete()
    return {"ok": True}


def _own_session(request, session_id: str) -> Session:
    session = Session.objects.filter(id=session_id, user=request.auth).first()
    if session is None:
        raise HttpError(404, "session not found")
    return session


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


@router.post("/sessions/{session_id}/messages")
async def send_message(request, session_id: str, payload: SendIn):
    user = await request.auser()
    session = await Session.objects.filter(id=session_id, user=user).afirst()
    if session is None:
        raise HttpError(404, "session not found")
    adapter = ADAPTERS.get(payload.provider)
    if adapter is None or payload.model not in adapter.models:
        raise HttpError(400, "unknown provider or model")
    if not adapter.available():
        raise HttpError(400, f"provider '{payload.provider}' has no API key configured")
    allowed, retry_after = provider_limiter.check(payload.provider)
    if not allowed:
        raise HttpError(429, f"provider rate limit hit, retry in {retry_after:.0f}s")

    history = [
        {"role": m.role, "content": m.content}
        async for m in session.messages.order_by("seq").values_list(named=True)
        if m.role in ("user", "assistant")
    ]
    history = history[-CONTEXT_TURNS:] + [{"role": "user", "content": payload.content}]
    seq = await session.messages.acount()
    await Message.objects.acreate(
        session=session, role="user", content=payload.content, seq=seq
    )
    if not session.title:
        session.title = payload.content[:60]
    await session.asave()

    async def stream():
        parts: list[str] = []
        status = "done"
        gen = None
        try:
            gen = adapter.stream(
                payload.model, history, session_id=session.id, end_user_id=user.username
            )
            async for delta in gen:
                parts.append(delta)
                yield _sse("token", {"d": delta})
        except asyncio.CancelledError:
            # Close the adapter chain by hand. The SDK reports an aborted generation
            # from GeneratorExit, and leaving that to garbage collection means the
            # end event may never be emitted — the row stays pending forever.
            if gen is not None:
                await gen.aclose()
            await _save_assistant(session, seq + 1, parts, payload, aborted=True)
            raise
        except (ProviderError, Exception) as exc:  # noqa: BLE001
            log.warning("provider stream failed: %s", exc)
            yield _sse("error", {"detail": str(exc), "error_type": type(exc).__name__})
            status = "error"
        if status == "done":
            message = await _save_assistant(session, seq + 1, parts, payload)
            yield _sse("done", {"message_id": message.id if message else None})

    response = StreamingHttpResponse(stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


async def _save_assistant(session, seq, parts, payload, aborted=False) -> Message | None:
    content = "".join(parts)
    if not content and aborted:
        return None
    return await Message.objects.acreate(
        session=session,
        role="assistant",
        content=content + (" …" if aborted else ""),
        provider=payload.provider,
        model=payload.model,
        seq=seq,
    )
