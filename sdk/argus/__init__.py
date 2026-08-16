"""argus-sdk: capture LLM inference telemetry with zero code changes.

Public API (implemented across the package):

    import argus

    argus.init(endpoint="http://localhost:8000/api/v1", api_key="...")

    client = argus.wrap_anthropic(anthropic.Anthropic())   # or wrap_openai / wrap_gemini
    # ... use the client exactly as before; every call is logged.

Design rule #1: the SDK is fail-open. It must never raise into, block, or
slow down the host application. Telemetry is buffered in a bounded in-memory
queue and shipped by a background thread.
"""

__version__ = "0.1.0"
