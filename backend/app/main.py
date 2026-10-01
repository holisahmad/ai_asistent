"""Application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes import health
from app.logging import configure_logging
from app.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    yield


def create_app() -> FastAPI:
    """App factory."""
    app = FastAPI(
        title="AI Knowledge Assistant API",
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(health.router)
    return app


app = create_app()
