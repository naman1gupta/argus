import json

import pytest

from apps.chat.models import Message, Session


@pytest.fixture
def logged_in(client, member_user, settings):
    settings.ARGUS_DISABLED = True
    client.post(
        "/api/v1/auth/login",
        data=json.dumps({"username": "member", "password": "pw-member"}),
        content_type="application/json",
    )
    return client


def csrf_headers(client):
    csrf = client.cookies.get("csrftoken")
    return {"X-CSRFToken": csrf.value if csrf else ""}


@pytest.mark.django_db
def test_chat_requires_login(client):
    assert client.get("/api/v1/chat/sessions").status_code == 401


@pytest.mark.django_db
def test_providers_lists_mock_always(logged_in):
    provs = {p["name"]: p for p in logged_in.get("/api/v1/chat/providers").json()}
    assert provs["mock"]["available"] is True
    assert set(provs) == {"anthropic", "gcp.gemini", "groq", "mock"}


@pytest.mark.django_db
def test_session_crud_and_ownership(logged_in, admin_user, project):
    logged_in.get("/api/v1/auth/me")
    resp = logged_in.post("/api/v1/chat/sessions", headers=csrf_headers(logged_in))
    assert resp.status_code == 201
    sid = resp.json()["id"]
    assert any(s["id"] == sid for s in logged_in.get("/api/v1/chat/sessions").json())

    other = Session.objects.create(user=admin_user)
    assert logged_in.get(f"/api/v1/chat/sessions/{other.id}/messages").status_code == 404


async def _async_login_and_session(async_client, project):
    await async_client.post(
        "/api/v1/auth/login",
        data=json.dumps({"username": "member", "password": "pw-member"}),
        content_type="application/json",
    )
    await async_client.get("/api/v1/auth/me")
    csrf = async_client.cookies.get("csrftoken")
    headers = {"X-CSRFToken": csrf.value if csrf else ""}
    resp = await async_client.post("/api/v1/chat/sessions", headers=headers)
    return resp.json()["id"], headers


async def _post_message(async_client, sid, headers, content):
    resp = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        data=json.dumps({"content": content, "provider": "mock", "model": "argus-demo-1"}),
        content_type="application/json",
        headers=headers,
    )
    chunks = [c async for c in resp.streaming_content]
    return resp, b"".join(chunks).decode()


@pytest.mark.django_db(transaction=True)
async def test_send_message_streams_and_persists(async_client, member_user, project):
    sid, headers = await _async_login_and_session(async_client, project)
    resp, body = await _post_message(async_client, sid, headers, "what is the refund policy?")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "text/event-stream"
    assert "event: token" in body and "event: done" in body

    msgs = [m async for m in Message.objects.filter(session_id=sid).order_by("seq")]
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert len(msgs[1].content) > 20
    session = await Session.objects.aget(id=sid)
    assert session.title.startswith("what is the refund")


@pytest.mark.django_db(transaction=True)
async def test_mock_error_path_emits_error_event(async_client, member_user, project):
    sid, headers = await _async_login_and_session(async_client, project)
    _, body = await _post_message(async_client, sid, headers, "please trigger error now")
    assert "event: error" in body and "simulated provider outage" in body


@pytest.mark.django_db
def test_unknown_provider_rejected(logged_in, project):
    logged_in.get("/api/v1/auth/me")
    sid = logged_in.post("/api/v1/chat/sessions", headers=csrf_headers(logged_in)).json()["id"]
    resp = logged_in.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        data=json.dumps({"content": "hi", "provider": "nope", "model": "x"}),
        content_type="application/json",
        headers=csrf_headers(logged_in),
    )
    assert resp.status_code == 400
