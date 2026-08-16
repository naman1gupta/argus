import pytest

from argus.client import ArgusClient


class CapturingClient(ArgusClient):
    def __init__(self, **kwargs):
        super().__init__("http://unused", "k", disabled=True, **kwargs)
        self.events = []

    def _emit(self, event_type, body):
        self.events.append((event_type, body))


@pytest.fixture
def capture():
    return CapturingClient(session_id="sess_t", end_user_id="tester")
