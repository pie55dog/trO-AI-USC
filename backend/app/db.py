"""Database engine and per-request sessions."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  (import registers the tables on SQLModel.metadata)


def make_engine(database_url: str) -> Engine:
    """Create the engine and make sure every table exists.

    For a hackathon, ``create_all`` is enough; switch to Alembic migrations
    if the schema starts changing on a live database.
    """
    connect_args = {}
    if database_url.startswith("sqlite"):
        # FastAPI runs sync endpoints in a thread pool, so SQLite must allow
        # a connection to be used from a different thread than created it.
        connect_args["check_same_thread"] = False
    engine = create_engine(database_url, connect_args=connect_args)

    if database_url.startswith("sqlite"):
        # SQLite ignores foreign keys unless asked; turn them on per connection.
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fks(dbapi_conn, _record):  # pragma: no cover - trivial
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    SQLModel.metadata.create_all(engine)
    return engine


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    with Session(request.app.state.engine) as session:
        yield session
