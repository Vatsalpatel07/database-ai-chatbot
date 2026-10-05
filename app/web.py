from __future__ import annotations

from fastapi import FastAPI

from app.api.routes.database import router as database_router
from app.api.routes.frontend import router as frontend_router
from app.api.routes.health import router as health_router
from app.core.config import settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    configure_logging()

    application = FastAPI(
        title=settings.app_name,
    )

    application.include_router(frontend_router)
    application.include_router(database_router)
    application.include_router(health_router)

    return application


app = create_app()
