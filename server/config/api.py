"""Single NinjaAPI instance; each app contributes a router.

Swagger UI is served at /api/v1/docs.
"""

from ninja import NinjaAPI

from apps.accounts.api import router as auth_router
from apps.projects.api import router as projects_router

api = NinjaAPI(
    title="Argus — LLM Inference Logging",
    version="1.0.0",
    description="Ingests, stores, and serves LLM inference telemetry.",
)

api.add_router("/auth", auth_router)
api.add_router("/projects", projects_router)


@api.get("/health", tags=["ops"])
def health(request):
    return {"status": "ok"}
