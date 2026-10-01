"""Database engine/session + Redis client (satu sumber untuk backend & worker)."""

from collections.abc import Generator

from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_asistent_core.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_redis: Redis | None = None


def get_engine() -> Engine:
    """Lazily create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Lazily create the session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def get_redis() -> Redis:
    """Lazily create the Redis client (text mode, untuk cek/health)."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


_rq_redis: Redis | None = None


def get_rq_connection() -> Redis:
    """Koneksi Redis biner khusus RQ (job payload pickle butuh bytes)."""
    global _rq_redis
    if _rq_redis is None:
        _rq_redis = Redis.from_url(get_settings().redis_url)
    return _rq_redis


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a DB session with commit/rollback."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
