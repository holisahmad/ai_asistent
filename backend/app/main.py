"""Application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from ai_asistent_core.config import get_settings
from fastapi import FastAPI

from app import __version__
from app.api.routes import auth, chat, files, health, workspaces
from app.audit import configure_audit_logging
from app.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_audit_logging(settings.audit_log_file)
    yield


def create_app() -> FastAPI:
    """App factory."""
    app = FastAPI(
        title="AI Knowledge Assistant API",
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(workspaces.router, prefix="/api/v1")
    app.include_router(files.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    return app
