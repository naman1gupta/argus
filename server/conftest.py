import pytest
from django.contrib.auth import get_user_model

from apps.projects.models import Project


@pytest.fixture(autouse=True)
def _argus_disabled(settings):
    settings.ARGUS_DISABLED = True
    settings.GROQ_API_KEY = ""
    settings.GEMINI_API_KEY = ""
    settings.ANTHROPIC_API_KEY = ""
    settings.OPENAI_API_KEY = ""
    settings.XAI_API_KEY = ""


@pytest.fixture
def project(db):
    p = Project(name="test-project")
    p._raw_key = p.issue_key()
    p.save()
    return p


@pytest.fixture
def admin_user(db):
    return get_user_model().objects.create_user(
        username="admin", password="pw-admin", role="admin"
    )


@pytest.fixture
def member_user(db):
    return get_user_model().objects.create_user(
        username="member", password="pw-member", role="member"
    )


@pytest.fixture
def fake_bus(monkeypatch):
    """Captures Kafka sends in-memory; set .available=False to simulate an outage."""

    class FakeBus:
        def __init__(self):
            self.sent = []
            self.available = True

    fake = FakeBus()

    async def send_many(items):
        if not fake.available:
            return False
        fake.sent.extend(items)
        return True

    from apps.telemetry import api as ingest_api

    monkeypatch.setattr(ingest_api.bus, "send_many", send_many)
    return fake
