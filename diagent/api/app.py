"""FastAPI application factory."""

from fastapi import FastAPI

from diagent.api.routes.alerts import router as alerts_router
from diagent.api.routes.evaluations import router as evaluations_router
from diagent.api.routes.health import router as health_router
from diagent.api.routes.runs import router as runs_router


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="Diagent",
        description="AI Agent & RAG Observability Backend",
        version="0.1.0",
    )
    app.include_router(runs_router)
    app.include_router(evaluations_router)
    app.include_router(alerts_router)
    app.include_router(health_router)
    return app


app = create_app()
