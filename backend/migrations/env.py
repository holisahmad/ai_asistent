"""Alembic environment — URL & metadata dari app."""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# Pastikan package `app` dapat diimport saat alembic dijalankan dari backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_asistent_core.config import get_settings  # noqa: E402
from ai_asistent_core.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """URL DB dari settings (env APP_DATABASE_URL) — tanpa secret di repo."""
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Mode offline: generate SQL tanpa koneksi."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Mode online: jalankan migrasi dengan koneksi sungguhan."""
    connectable = create_engine(_database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
