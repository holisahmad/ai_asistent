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
    """Lazily create the SQLAlchemy engine.

    Supabase Transaction Pooler (pgbouncer, port 6543) tidak mendukung
    prepared statements. psycopg3 membuat prepared statement secara otomatis
    setelah threshold tertentu, menyebabkan DuplicatePreparedStatement error.
    Fix: set prepare_threshold=0 via connect_args untuk disable sepenuhnya.
    """
    global _engine
    if _engine is None:
        url = get_settings().database_url
        # Cek apakah ini Supabase Transaction Pooler (port 6543 atau pooler URL)
        is_pooler = (
            ".pooler.supabase.com" in url
            or ":6543/" in url
        )
        connect_args: dict = {}
        if is_pooler:
            # Disable prepared statements untuk pgbouncer compatibility
            connect_args["prepare_threshold"] = 0
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
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
