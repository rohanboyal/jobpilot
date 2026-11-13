"""SQLite via SQLAlchemy 2.0. One file database under data/."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            f"sqlite:///{settings.db_path}",
            connect_args={"check_same_thread": False, "timeout": 60},
            future=True,
        )

        @event.listens_for(_engine, "connect")
        def _set_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=60000")
            cur.close()

        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


# Columns added after the first release. create_all() never alters existing tables, so add them here.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "jobs": {"profile_ids": "JSON", "exp_min": "FLOAT", "exp_max": "FLOAT", "work_mode": "VARCHAR(10)",
             "job_type": "VARCHAR(12)", "salary_currency": "VARCHAR(3)", "salary_min": "FLOAT", "salary_max": "FLOAT",
             "expired_from": "VARCHAR(20)"},
    "applications": {"outcome": "VARCHAR(20)", "outcome_at": "DATETIME", "outcome_notes": "TEXT", "follow_up_at": "DATETIME",
                     "drafted_at": "DATETIME", "worker_pid": "INTEGER", "resume_id": "INTEGER"},
    "runs": {"worker_pid": "INTEGER"},
    "profile": {"name": "VARCHAR(120)"},
    "search_profiles": {"resume_id": "INTEGER", "resume_changed_at": "DATETIME"},
}


def init_db() -> None:
    from sqlalchemy import inspect, text

    from . import models  # noqa: F401  (register tables)

    engine = get_engine()
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for scripts and background jobs."""
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
