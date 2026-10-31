"""SQLite в режиме WAL, один движок на процесс."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, DateTime, Engine, create_engine, event, func
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import InstrumentedAttribute, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import Settings, get_settings


class UTCDateTime(TypeDecorator[datetime]):
    """Хранит время в UTC без tzinfo, отдаёт с tzinfo=UTC. Наивные значения запрещены."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime без часового пояса")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _fold(value: object) -> object:
    return value.casefold() if isinstance(value, str) else value


def ci_contains(
    column: ColumnElement[str] | InstrumentedAttribute[str | None], text: str
) -> ColumnElement[bool]:
    """Подстрока без учёта регистра, и для кириллицы тоже; `%` и `_` в тексте — обычные символы."""
    escaped = text.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return func.unicode_fold(column).like(f"%{escaped}%", escape="\\")


def _configure_sqlite(dbapi_conn: sqlite3.Connection, _record: object) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()
    # lower() и LIKE в SQLite знают регистр только латиницы: «дозорный» не находил «Дозорный».
    dbapi_conn.create_function("unicode_fold", 1, _fold, deterministic=True)


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _configure_sqlite)
    return engine


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def db_url(settings: Settings) -> str:
    return f"sqlite:///{settings.db_path}"


def init_engine(url: str | None = None) -> Engine:
    """Создаёт движок и фабрику сессий. `url` нужен только тестам."""
    global _engine, _session_factory
    settings = get_settings()
    if url is None:
        settings.ensure_dirs()
        url = db_url(settings)
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(url)
    _session_factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("БД не инициализирована")
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        raise RuntimeError("БД не инициализирована")
    return _session_factory


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: одна транзакция на запрос."""
    with session_factory()() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
