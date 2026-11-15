"""Database engine and per-request sessions."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  (import registers the tables on SQLModel.metadata)


def normalize_database_url(database_url: str) -> str:
    """Use the psycopg 3 driver for Postgres URLs.

    Hosts like Render hand out ``postgres://`` or ``postgresql://`` URLs,
    which SQLAlchemy would map to the old psycopg2 driver (not installed).
    """
    for prefix in ("postgres://", "postgresql://"):
        if database_url.startswith(prefix):
            return "postgresql+psycopg://" + database_url[len(prefix):]
    return database_url


def make_engine(database_url: str) -> Engine:
    """Create the engine and make sure every table exists.

    For a hackathon, ``create_all`` is enough; switch to Alembic migrations
    if the schema starts changing on a live database.
    """
    database_url = normalize_database_url(database_url)
    connect_args = {}
    if database_url.startswith("sqlite"):
        # FastAPI runs sync endpoints in a thread pool, so SQLite must allow
        # a connection to be used from a different thread than created it.
        connect_args["check_same_thread"] = False
    # pool_pre_ping replaces connections a hosted database dropped while idle.
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)

    if database_url.startswith("sqlite"):
        # SQLite ignores foreign keys unless asked; turn them on per connection.
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fks(dbapi_conn, _record):  # pragma: no cover - trivial
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    SQLModel.metadata.create_all(engine)
    if database_url.startswith("sqlite"):
        add_missing_columns(engine)
    return engine


def add_missing_columns(engine: Engine) -> None:
    """Add columns that the models define but an existing database lacks.

    ``create_all`` only creates missing *tables*, so a tro.db made by an
    older version would crash on new columns. This hackathon-sized helper
    adds them (SQLite ALTER TABLE ADD COLUMN) with their default, so old
    rows stay valid. It never drops or changes anything.
    """
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(engine.dialect)}'
                default = column.default.arg if column.default is not None and column.default.is_scalar else None
                if isinstance(default, bool):
                    ddl += f" NOT NULL DEFAULT {int(default)}"
                elif isinstance(default, (int, float)):
                    ddl += f" NOT NULL DEFAULT {default}"
                elif isinstance(default, str):
                    ddl += " NOT NULL DEFAULT '" + default.replace("'", "''") + "'"
                conn.execute(text(ddl))


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    with Session(request.app.state.engine) as session:
        yield session
