from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, event, DateTime
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator
from .config import get_settings


def utcnow():
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """A timezone-aware value in the application, UTC without a zone in the column.

    SQLite has no timezone type, so the column stores naive UTC and the offset is
    attached on the way out. PostgreSQL keeps the same physical type
    (``timestamp without time zone``); if a column ever comes back zone-aware --
    a ``timestamptz`` added by hand, or a session defaulting to something else --
    it is converted to UTC rather than relabelled, so the value cannot drift.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("A timezone-aware timestamp is required")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


def is_postgres(url: str) -> bool:
    return url.startswith("postgresql")


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def make_engine(url, *, pool_size: int = 5) -> Engine:
    """Build the engine for the configured database, or for a test database.

    SQLite keeps the pragmas that make a single-file database behave: enforced
    foreign keys, WAL and a long busy timeout. PostgreSQL gets a small, checked
    pool: the free hosted plans cap concurrent connections and drop idle ones, so
    a pooled connection is tested before use and recycled regularly.
    """
    if is_sqlite(url) and ":memory:" not in url:
        Path(url.replace("sqlite:///", "", 1)).resolve().parent.mkdir(parents=True, exist_ok=True)
    if is_postgres(url):
        return create_engine(
            url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=pool_size,
            pool_recycle=300,
            pool_timeout=30,
            future=True,
        )
    engine = create_engine(
        url, connect_args={"check_same_thread": False, "timeout": 30} if is_sqlite(url) else {}
    )
    if is_sqlite(url):

        @event.listens_for(engine, "connect")
        def pragmas(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")

    return engine


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise
