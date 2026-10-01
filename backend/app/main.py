"""Application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from ai_asistent_core.config import csv_list, get_settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import auth, chat, files, health, ops, workspaces
from app.audit import configure_audit_logging
from app.logging import configure_logging
from app.observability import install_middlewares


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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=csv_list(get_settings().cors_origins_csv),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    install_middlewares(app)

    app.include_router(health.router)
    app.include_router(ops.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(workspaces.router, prefix="/api/v1")
    app.include_router(files.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    return app
