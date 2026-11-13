"""Отметка «был на сайте» не должна держать блокировку записи на время запроса.

В логе боевого сайта было `database is locked` на `UPDATE user SET last_seen_at …`: отметка попадала в
транзакцию запроса и брала блокировку записи в самом начале, а запрос потом принимал кусок файла,
считал sha256 четырёх гигабайт или отдавал файл медленному клиенту — всё это время писать в базу не
мог больше никто. Теперь отметка — отдельная короткая транзакция, не больше раза в минуту.
"""

import sqlite3
import time
from datetime import timedelta

from sqlalchemy import func, select

from app import db as database
from app import models
from app.auth import session
from app.config import get_settings
from app.constants import Role
from app.db import utcnow
from app.services import users
from tests.conftest import login
from tests.factories import make_user


def _cookie(user_id: int) -> str:
    return session._serializer(get_settings()).dumps({"uid": user_id})


def _stale_user(db, minutes: float = 5) -> int:  # noqa: ANN001
    user = make_user(db, Role.TEAM, "Сева")
    user.last_seen_at = utcnow() - timedelta(minutes=minutes)
    db.commit()
    return user.id


def _stored_seen(user_id: int):  # noqa: ANN202
    with database.session_factory()() as fresh:
        return fresh.get(models.User, user_id).last_seen_at


def _request_step(request_db, user_id: int) -> models.User:  # noqa: ANN001
    """То, что делает начало запроса: вход, потом первый запрос к данным (он выталкивает правки сессии)."""
    user = session.current_user(request_db, _cookie(user_id))
    request_db.scalar(select(func.count()).select_from(models.Project))
    return user


def test_the_mark_is_written_but_the_request_holds_no_write_lock(db):  # noqa: ANN001
    user_id = _stale_user(db)
    before = _stored_seen(user_id)
    with database.session_factory()() as request_db:  # как сессия запроса (get_db)
        _request_step(request_db, user_id)
        # Запрос ещё идёт (принимает кусок файла, хэширует, отдаёт файл): другие пишут свободно.
        other = sqlite3.connect(get_settings().db_path, timeout=0)
        try:
            other.execute("BEGIN IMMEDIATE")
        finally:
            other.rollback()
            other.close()
    assert _stored_seen(user_id) > before


def test_the_mark_is_visible_on_the_loaded_user_without_a_second_write(db):  # noqa: ANN001
    user_id = _stale_user(db)
    with database.session_factory()() as request_db:
        user = _request_step(request_db, user_id)
        assert user.last_seen_at > utcnow() - timedelta(seconds=30)
        assert not request_db.dirty  # правка не ушла бы второй раз при коммите запроса
        request_db.commit()


def test_a_busy_database_neither_fails_nor_stalls_the_request(db):  # noqa: ANN001
    user_id = _stale_user(db)
    before = _stored_seen(user_id)
    blocker = sqlite3.connect(get_settings().db_path, timeout=0)
    blocker.execute("BEGIN IMMEDIATE")  # кто-то долго пишет
    try:
        started = time.monotonic()
        with database.session_factory()() as request_db:
            user = _request_step(request_db, user_id)
            request_db.commit()
        waited = time.monotonic() - started
        assert user.id == user_id  # запрос идёт дальше
        assert waited < 2  # необязательная отметка не ждёт обычные пять секунд
    finally:
        blocker.rollback()
        blocker.close()
    assert _stored_seen(user_id) == before  # не записалось — не страшно
    with database.session_factory()() as request_db:  # освободилось: следующий запрос отметит
        _request_step(request_db, user_id)
    assert _stored_seen(user_id) > before


def test_the_usual_wait_for_a_busy_database_is_back_after_the_mark(db):  # noqa: ANN001
    user_id = _stale_user(db)
    blocker = sqlite3.connect(get_settings().db_path, timeout=0)
    blocker.execute("BEGIN IMMEDIATE")
    try:  # и после неудачной отметки, и после удачной соединение вернулось в пул с прежним ожиданием
        with database.session_factory()() as request_db:
            _request_step(request_db, user_id)
    finally:
        blocker.rollback()
        blocker.close()
    users.touch_seen(db, db.get(models.User, user_id))
    engine = database.get_engine()
    pooled = [engine.raw_connection() for _ in range(engine.pool.checkedin())]
    try:
        waits = {c.driver_connection.execute("PRAGMA busy_timeout").fetchone()[0] for c in pooled}
    finally:
        for c in pooled:
            c.close()
    assert waits == {database.BUSY_TIMEOUT_MS}


def test_a_recent_mark_is_not_rewritten(db):  # noqa: ANN001
    user_id = _stale_user(db, minutes=0.2)
    before = _stored_seen(user_id)
    with database.session_factory()() as request_db:
        _request_step(request_db, user_id)
    assert _stored_seen(user_id) == before


def test_a_request_through_the_api_records_the_visit(client):  # noqa: ANN001
    user = login(client, "team")
    assert client.get("/api/shots").status_code == 200
    assert _stored_seen(user.id) is not None
