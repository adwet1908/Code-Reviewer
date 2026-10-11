"""SQLAlchemy engine and session. Tables are created on app startup."""

import logging
import os
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import DATABASE_URL

logger = logging.getLogger(__name__)
_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))

# In-memory SQLite is only for tests. StaticPool keeps one shared DB.
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"connect_timeout": _CONNECT_TIMEOUT},
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _pgvector_help(version: str = "") -> str:
    port_hint = (
        " Your DATABASE_URL is reaching a Windows Postgres on port 5432 (no pgvector). "
        "Use Docker on port 5433 instead: postgresql+psycopg://postgres:postgres@localhost:5433/code_reviewer"
        if "windows" in version.lower()
        else " Set DATABASE_URL to postgresql+psycopg://postgres:postgres@localhost:5433/code_reviewer"
    )
    return (
        "Phase 2 needs Postgres with the pgvector extension. "
        "From the repo root run: docker compose up -d "
        f"(pgvector on host port 5433).{port_hint}"
    )


def _preflight_postgres() -> None:
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version()")).scalar()
        available = connection.execute(
            text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        ).first()
        if not available:
            raise RuntimeError(_pgvector_help(version or ""))


def init_db() -> None:
    """SQLite tests: create tables. Postgres: run Alembic migrations."""
    from app import models  # noqa: F401

    if os.getenv("SKIP_DB_MIGRATE", "").lower() in {"1", "true", "yes"}:
        logger.warning("SKIP_DB_MIGRATE is set; Alembic migrations were not run.")
        return

    if DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
        return

    logger.info("Checking Postgres and pgvector…")
    _preflight_postgres()

    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    logger.info("Running Alembic migrations…")
    # URL is read in alembic/env.py from app.config (avoids ConfigParser % issues).
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        command.upgrade(alembic_cfg, "head")
    except Exception as exc:
        message = str(exc).lower()
        if "vector" in message:
            raise RuntimeError(_pgvector_help()) from exc
        raise
    logger.info("Database migrations complete.")
