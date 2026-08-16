"""Single NinjaAPI instance; each app contributes a router.

Swagger UI is served at /api/v1/docs.
"""

from ninja import NinjaAPI

from apps.accounts.api import router as auth_router
from apps.chat.api import router as chat_router
from apps.insights.api import router as insights_router
from apps.projects.api import router as projects_router
from apps.telemetry.api import router as ingest_router

api = NinjaAPI(
    title="Argus — LLM Inference Logging",
    version="1.0.0",
    description="Ingests, stores, and serves LLM inference telemetry.",
)

api.add_router("/auth", auth_router)
api.add_router("/projects", projects_router)
api.add_router("/chat", chat_router)
api.add_router("/insights", insights_router)
api.add_router("", ingest_router)


@api.get("/health", tags=["ops"])
async def health(request):
    """Liveness + pipeline observability: total consumer-group lag on the events topic."""
    from apps.telemetry.health import consumer_lag

    return {"status": "ok", "consumer_lag": await consumer_lag()}
