"""Single NinjaAPI instance; each app contributes a router.

Swagger UI is served at /api/v1/docs.
"""

from ninja import NinjaAPI

api = NinjaAPI(
    title="Argus — LLM Inference Logging",
    version="1.0.0",
    description="Ingests, stores, and serves LLM inference telemetry.",
)


@api.get("/health", tags=["ops"])
def health(request):
    return {"status": "ok"}
