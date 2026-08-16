import json

import pytest


def login(client, username, password):
    return client.post(
        "/api/v1/auth/login",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
    )


@pytest.mark.django_db
def test_login_me_logout_flow(client, admin_user):
    assert login(client, "admin", "wrong").status_code == 401
    resp = login(client, "admin", "pw-admin")
    assert resp.status_code == 200 and resp.json()["role"] == "admin"
    assert client.get("/api/v1/auth/me").json()["username"] == "admin"


@pytest.mark.django_db
def test_rbac_member_cannot_access_projects(client, member_user):
    login(client, "member", "pw-member")
    assert client.get("/api/v1/projects").status_code == 401


@pytest.mark.django_db
def test_admin_can_create_project_and_key_shown_once(client, admin_user):
    login(client, "admin", "pw-admin")
    csrf = client.cookies.get("csrftoken")
    resp = client.post(
        "/api/v1/projects",
        data=json.dumps({"name": "p2"}),
        content_type="application/json",
        headers={"X-CSRFToken": csrf.value if csrf else ""},
    )
    assert resp.status_code == 201
    key = resp.json()["ingestion_key"]
    assert key.startswith("argus_sk_")
    listing = client.get("/api/v1/projects").json()
    assert all("ingestion_key" not in p for p in listing)


@pytest.mark.django_db
def test_duplicate_project_name_returns_409_not_500(client, admin_user):
    login(client, "admin", "pw-admin")
    client.get("/api/v1/auth/me")
    csrf = client.cookies.get("csrftoken")
    headers = {"X-CSRFToken": csrf.value if csrf else ""}
    body = json.dumps({"name": "dupe"})
    post = lambda: client.post(  # noqa: E731
        "/api/v1/projects", data=body, content_type="application/json", headers=headers
    )
    first, second = post(), post()
    assert first.status_code == 201
    assert second.status_code == 409


@pytest.mark.django_db
def test_missing_log_detail_returns_404(client, admin_user):
    login(client, "admin", "pw-admin")
    resp = client.get("/api/v1/insights/logs/gen_does_not_exist")
    assert resp.status_code == 404
