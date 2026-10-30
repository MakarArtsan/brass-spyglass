import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

OWNER_TG_ID = 1001


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Чистый /data и настройки без Telegram на каждый тест."""
    for key in list(os.environ):
        if key.startswith(("TG_", "FRONTEND_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("OWNER_TG_ID", str(OWNER_TG_ID))
    monkeypatch.setenv("SEED_XLSX", "")  # автоимпорт Excel включают только тесты импорта
    from app.config import get_settings

    get_settings.cache_clear()
    yield tmp_path / "data"
    get_settings.cache_clear()


@pytest.fixture
def db(env: Path) -> Iterator[Session]:
    """Сессия на свежей БД, созданной миграциями (заодно проверяет их)."""
    from app import db as database
    from app.migrate import upgrade_to_head
    from app.services import projects

    engine = database.init_engine()
    with engine.begin() as conn:
        upgrade_to_head(conn)
    with database.session_factory()() as session:
        projects.ensure_default_project(session)
        session.commit()
        yield session
        session.rollback()
    engine.dispose()


@pytest.fixture
def client(env: Path) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "Krivoe_zerkalo_tracker.xlsx"


@pytest.fixture
def seeded_client(env: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Приложение, которое при старте загрузило реальные данные из Excel-трекера."""
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("SEED_XLSX", str(SEED_PATH))
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c


def login(client: TestClient, role: str = "owner", name: str = "Тест"):  # noqa: ANN201
    """Создаёт участника с ролью и ставит его сессию клиенту (для нескольких ролей в тесте —
    вызывать повторно)."""
    from app import db as database
    from app.auth import session
    from app.config import get_settings
    from app.constants import Role
    from tests.factories import make_user

    with database.session_factory()() as db:
        user = make_user(db, Role(role), name)
        db.commit()
    token = session._serializer(get_settings()).dumps({"uid": user.id})
    client.cookies.set(session.COOKIE_NAME, token)
    return user
