"""Подтверждение проектов: пока суперадмин не подтвердил, команда не загружает файлы."""

import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from alembic import command
from app import db as database
from app import main as main_module
from app import models, permissions
from app.config import get_settings
from app.constants import Role
from app.permissions import Actor
from app.services import projects
from tests.conftest import OWNER_TG_ID
from tests.test_auth import FakeMembership
from tests.test_self_service import C1, C2, STRANGER, FakeClient, FakePool, new_project, sign_in

BOSS = OWNER_TG_ID


class FakeBot:
    """Бот, который пишет в личные сообщения."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str, list | None]] = []
        self.blocked: set[int] = set()

    async def send_message(self, tg_id: int, text: str, buttons=None) -> None:
        if tg_id in self.blocked:
            raise RuntimeError("пользователь не нажимал Start")
        self.sent.append((tg_id, text, buttons))

    async def disconnect(self) -> None:
        return None

    def to(self, tg_id: int) -> list[str]:
        return [text for who, text, _ in self.sent if who == tg_id]


class PoolWithRemove(FakePool):
    def __init__(self) -> None:
        super().__init__()
        self.removed: list[int] = []

    async def remove(self, chat_id: int) -> None:
        self.removed.append(chat_id)


@pytest.fixture
def gate(bound_chat, client, monkeypatch):
    """Приложение с подтверждением проектов (как в рабочей конфигурации), ботом и пулом-заглушкой."""
    monkeypatch.setenv("SELF_SERVICE_PROJECTS", "true")
    monkeypatch.setenv("PROJECT_APPROVAL", "true")
    get_settings.cache_clear()
    state = client.app.state
    state.tg.userbot = FakeClient()
    state.tg.bot = FakeBot()
    state.tg.userbot_account = {"username": "brass_helper", "name": "Помощник"}
    state.tg.membership = FakeMembership(admins={C1: {STRANGER}, C2: {STRANGER, BOSS}})
    state.tg.sync_pause_sec = 0
    state.indexer_pool = PoolWithRemove()
    return client


def make_request(client, **body) -> dict:
    """Обычный человек подаёт заявку; возвращает ответ создания."""
    sign_in(client, STRANGER, "Новичок")
    done = new_project(client, **body)
    assert done.status_code == 201, done.text
    return done.json()


def as_boss(client) -> None:
    sign_in(client, BOSS, "Босс")


# --- права ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "pending", "superadmin", "allowed"),
    [
        (Role.OWNER, False, False, True),
        (Role.TEAM, False, False, True),
        (Role.GUEST, False, False, False),
        (Role.OWNER, True, False, False),  # владелец неподтверждённого проекта — тоже нельзя
        (Role.TEAM, True, False, False),
        (Role.DIRECTOR, True, False, False),
        (Role.OWNER, True, True, True),  # а владелец сайта может
        (Role.GUEST, True, True, False),  # гость остаётся гостем
    ],
)
def test_the_upload_permission_follows_role_and_confirmation(role, pending, superadmin, allowed):
    actor = Actor(1, role, project_id=1, pending=pending, superadmin=superadmin)
    assert permissions.can_upload(actor) is allowed
    if allowed:
        permissions.require_upload(actor)
    else:
        with pytest.raises(permissions.PermissionDenied):
            permissions.require_upload(actor)


def test_the_message_says_why_nothing_can_be_uploaded():
    waiting = Actor(1, Role.TEAM, pending=True)
    with pytest.raises(permissions.PermissionDenied, match="не подтверждён"):
        permissions.require_upload(waiting)
    guest = Actor(2, Role.GUEST)
    with pytest.raises(permissions.PermissionDenied, match="Гость"):
        permissions.require_upload(guest)


# --- заявка --------------------------------------------------------------------------------------------


def test_a_new_project_of_an_ordinary_person_waits_for_the_site_owner(gate):
    brief = make_request(gate)
    assert brief["pending"] is True
    slug = brief["slug"]
    assert gate.get("/api/session").json()["projects"][0]["pending"] is True
    assert gate.get(f"/api/p/{slug}/project").json()["approved"] is False
    assert gate.get(f"/api/p/{slug}/me").json()["abilities"]["upload"] is False
    assert gate.app.state.indexer_pool.ensured == []  # медиа чата пока не собираем


def test_the_site_owner_is_told_with_buttons(gate):
    brief = make_request(gate, title="Кривое зеркало")
    bot = gate.app.state.tg.bot
    (text,) = bot.to(BOSS)
    assert "Кривое зеркало" in text and "Новичок" in text and "не сможет загружать" in text
    (_, _, buttons) = next(item for item in bot.sent if item[0] == BOSS)
    data = [button.type.data for row in buttons for button in row]
    with database.session_factory()() as db:
        project_id = projects.get_by_slug(db, brief["slug"]).id
    assert data == [f"approve:{project_id}".encode(), f"reject:{project_id}".encode()]


def test_a_blocked_bot_does_not_stop_the_request(gate):
    gate.app.state.tg.bot.blocked = {BOSS}  # владелец сайта не нажимал Start
    brief = make_request(gate)
    assert brief["pending"] is True  # заявка есть, её видно на сайте
    as_boss(gate)
    assert [p["slug"] for p in gate.get("/api/projects/pending").json()] == [brief["slug"]]


def test_the_waiting_team_cannot_upload_or_import_but_can_do_everything_else(gate):
    slug = make_request(gate)["slug"]
    refused = gate.post(f"/api/p/{slug}/uploads", json={"name": "a.png", "size": 10})
    assert refused.status_code == 403 and "не подтверждён" in refused.json()["detail"]
    assert (
        gate.post(
            f"/api/p/{slug}/tg/import",
            json={"media_ids": [1], "entity_type": "shot", "entity_id": 1},
        ).status_code
        == 403
    )
    assert gate.get(f"/api/p/{slug}/tg/topics").status_code == 403
    # без файлов работа идёт: карточки, комментарии, переименование
    assert (
        gate.post(f"/api/p/{slug}/tasks", json={"code": "T-01", "title": "Первая"}).status_code
        == 201
    )
    assert gate.patch(f"/api/p/{slug}/project", json={"title": "Новое имя"}).status_code == 200


def test_the_site_owner_may_upload_into_a_waiting_project(gate):
    slug = make_request(gate)["slug"]
    as_boss(gate)
    assert (
        gate.post(f"/api/p/{slug}/uploads", json={"name": "a.png", "size": 10}).status_code == 201
    )


def test_a_superadmins_own_project_is_active_at_once(gate):
    as_boss(gate)
    done = new_project(gate, chat_id=C2)
    assert done.status_code == 201 and done.json()["pending"] is False
    assert gate.app.state.indexer_pool.ensured == [C2]
    assert gate.app.state.tg.bot.sent == []  # некому сообщать: решать нечего


def test_approval_can_be_switched_off(gate, monkeypatch):
    monkeypatch.setenv("PROJECT_APPROVAL", "false")
    get_settings.cache_clear()
    brief = make_request(gate)
    assert brief["pending"] is False
    assert (
        gate.post(f"/api/p/{brief['slug']}/uploads", json={"name": "a.png", "size": 10}).status_code
        == 201
    )


# --- решение --------------------------------------------------------------------------------------------


def test_confirmation_opens_uploads_starts_the_chat_index_and_tells_the_owner(gate):
    slug = make_request(gate)["slug"]
    as_boss(gate)
    done = gate.post(f"/api/projects/{slug}/approve")
    assert done.status_code == 200 and done.json()["status"] == "approve"
    assert gate.app.state.indexer_pool.ensured == [C1]
    assert any("подтверждён" in text for text in gate.app.state.tg.bot.to(STRANGER))
    sign_in(gate, STRANGER)
    assert gate.get(f"/api/p/{slug}/me").json()["abilities"]["upload"] is True
    assert (
        gate.post(f"/api/p/{slug}/uploads", json={"name": "a.png", "size": 10}).status_code == 201
    )
    assert gate.get("/api/session").json()["projects"][0]["pending"] is False


def test_confirmation_twice_changes_nothing_more(gate):
    slug = make_request(gate)["slug"]
    as_boss(gate)
    assert gate.post(f"/api/projects/{slug}/approve").status_code == 200
    assert gate.post(f"/api/projects/{slug}/approve").status_code == 200
    with database.session_factory()() as db:
        journal = db.scalars(select(models.Activity).where(models.Activity.action == "approve"))
        assert len(list(journal)) == 1


def test_rejection_archives_the_project_and_frees_the_chat(gate):
    slug = make_request(gate)["slug"]
    as_boss(gate)
    done = gate.post(f"/api/projects/{slug}/reject")
    assert done.status_code == 200 and done.json()["status"] == "reject"
    assert gate.app.state.indexer_pool.removed == [C1]
    assert any("отклонена" in text for text in gate.app.state.tg.bot.to(STRANGER))
    assert gate.get("/api/projects/pending").json() == []
    with database.session_factory()() as db:
        project = projects.get_by_slug(db, slug)
        assert project.archived_at is not None and project.tg_chat_id is None
    sign_in(gate, STRANGER)  # владелец заявки снова может подать её с тем же чатом
    assert new_project(gate, title="Заново").status_code == 201


def test_an_approved_project_cannot_be_rejected(gate):
    slug = make_request(gate)["slug"]
    as_boss(gate)
    gate.post(f"/api/projects/{slug}/approve")
    refused = gate.post(f"/api/projects/{slug}/reject")
    assert refused.status_code == 409 and "уже подтверждён" in refused.json()["detail"]


def test_only_the_site_owner_decides_and_sees_the_requests(gate):
    slug = make_request(gate)["slug"]
    # человек, подавший заявку, решить её сам не может
    assert gate.post(f"/api/projects/{slug}/approve").status_code == 403
    assert gate.post(f"/api/projects/{slug}/reject").status_code == 403
    assert gate.get("/api/projects/pending").status_code == 403
    gate.cookies.clear()
    assert gate.post(f"/api/projects/{slug}/approve").status_code == 401
    assert gate.get("/api/projects/pending").status_code == 401
    as_boss(gate)
    assert gate.post("/api/projects/no-such-project/approve").status_code == 404
    with database.session_factory()() as db:
        assert projects.get_by_slug(db, slug).approved_at is None  # ничего не изменилось


def test_the_site_owner_sees_the_queue_and_its_size(gate):
    first = make_request(gate, title="Первый", chat_id=C1)["slug"]
    as_boss(gate)
    pending = gate.get("/api/projects/pending").json()
    assert [(p["slug"], p["owner_name"]) for p in pending] == [(first, "Новичок")]
    assert gate.get("/api/session").json()["pending_count"] == 1
    sign_in(gate, STRANGER)
    assert (
        gate.get("/api/session").json()["pending_count"] == 0
    )  # обычным людям очередь не показываем


# --- кнопки в Telegram ----------------------------------------------------------------------------------


class FakeCallback:
    def __init__(self, data: str, sender_id: int) -> None:
        self.data = data.encode()
        self.sender_id = sender_id
        self.answers: list[tuple[str, bool]] = []
        self.edited: str | None = None

    async def answer(self, text: str = "", alert: bool = False) -> None:
        self.answers.append((text, alert))

    async def edit(self, text: str) -> None:
        self.edited = text


def project_id(slug: str) -> int:
    with database.session_factory()() as db:
        return projects.get_by_slug(db, slug).id


async def test_the_button_in_telegram_confirms_the_project(gate):
    slug = make_request(gate)["slug"]
    as_boss(gate)  # владелец сайта хотя бы раз входил на сайт
    press = FakeCallback(f"approve:{project_id(slug)}", BOSS)
    await gate.app.state.tg._on_callback(press)
    assert press.answers == [("Готово", False)] and "подтверждён" in press.edited
    assert gate.app.state.indexer_pool.ensured == [C1]
    with database.session_factory()() as db:
        assert projects.get_by_slug(db, slug).approved_at is not None


async def test_the_button_rejects_too_and_a_second_press_says_so(gate):
    slug = make_request(gate)["slug"]
    as_boss(gate)
    await gate.app.state.tg._on_callback(FakeCallback(f"reject:{project_id(slug)}", BOSS))
    again = FakeCallback(f"approve:{project_id(slug)}", BOSS)
    await gate.app.state.tg._on_callback(again)  # проект уже отклонён и в архиве
    with database.session_factory()() as db:
        assert projects.get_by_slug(db, slug).archived_at is not None
    assert again.edited is None or "отклонена" not in again.edited


async def test_a_stranger_cannot_press_the_button_even_if_he_got_the_message(gate):
    slug = make_request(gate)["slug"]
    press = FakeCallback(f"approve:{project_id(slug)}", STRANGER)
    await gate.app.state.tg._on_callback(press)
    assert press.answers == [("Решает только владелец сайта.", True)] and press.edited is None
    with database.session_factory()() as db:
        assert projects.get_by_slug(db, slug).approved_at is None


async def test_odd_button_data_is_ignored_and_an_unknown_site_user_is_asked_to_log_in(gate):
    for data in ("approve:xyz", "launch:1", "approve", ""):
        press = FakeCallback(data, BOSS)
        await gate.app.state.tg._on_callback(press)
        assert press.answers == [] and press.edited is None
    never_logged_in = FakeCallback("approve:1", BOSS)  # на сайт владелец ещё не входил
    await gate.app.state.tg._on_callback(never_logged_in)
    assert (
        never_logged_in.answers[0][1] is True and "войдите на сайт" in never_logged_in.answers[0][0]
    )


# --- запуск индексаторов --------------------------------------------------------------------------------


async def test_only_confirmed_live_projects_get_an_indexer_at_start(bound_chat, db, monkeypatch):
    now = datetime.now(UTC)
    base = projects.DEFAULT_PROJECT
    db.add_all(
        [
            models.Project(**{**base, "slug": "waiting", "tg_chat_id": -1003, "approved_at": None}),
            models.Project(
                **{
                    **base,
                    "slug": "old",
                    "tg_chat_id": -1004,
                    "approved_at": now,
                    "archived_at": now,
                }
            ),
        ]
    )
    db.commit()
    started: list[list[int]] = []

    class Recorder:
        def __init__(self, *_args, **_kwargs) -> None: ...

        async def start(self, chats: list[int]) -> None:
            started.append(sorted(chats))

    monkeypatch.setattr(main_module, "IndexerPool", Recorder)
    app = SimpleNamespace(state=SimpleNamespace(tg=SimpleNamespace(userbot=object(), bot=None)))
    await main_module._start_indexers(app, get_settings())
    assert started == [[bound_chat]]  # только живой подтверждённый проект фильма


# --- данные --------------------------------------------------------------------------------------------


def test_the_film_project_created_by_the_system_is_confirmed(db):
    film = projects.get_by_slug(db, "brass-spyglass")
    assert film.approved_at is not None and film.approved is True


def test_migration_0009_confirms_every_existing_project(env):
    from tests.test_migrations import _cfg, _populated_0006  # noqa: PLC2701

    path = _populated_0006(env)
    command.upgrade(_cfg(), "0008")
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute(
        "insert into project(id,title,title_en,contest,deadline_official,deadline_internal,fps,width,"
        "height,target_min_sec,target_max_sec,storage_limit_gb,created_at,updated_at,slug)"
        " values (2,'Второй','Second','c','2026-12-01 00:00:00','2026-11-29 00:00:00',24,1,1,1,2,5,"
        "'2026-10-31 00:00:00','2026-10-31 00:00:00','second')"
    )
    db.commit()
    db.close()

    command.upgrade(_cfg(), "head")

    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    rows = db.execute(
        "select id, approved_at is not null, approved_at = created_at from project order by id"
    ).fetchall()
    assert rows == [(1, 1, 1), (2, 1, 1)]  # проекты, жившие до подтверждения, остаются рабочими
    assert db.execute("pragma foreign_key_check").fetchall() == []
    assert any(r[3] == "approved_by" for r in db.execute("pragma foreign_key_list(project)"))
    db.execute("select approved_by from project")  # столбец есть и пуст
    db.close()


def test_a_repeated_get_of_the_session_does_not_change_the_queue(gate):
    make_request(gate)
    as_boss(gate)
    first = gate.get("/api/session").json()["pending_count"]
    assert first == gate.get("/api/session").json()["pending_count"] == 1


async def test_the_pool_forgets_a_chat_that_was_rejected(db, monkeypatch):
    from app.tg import pool as pool_module
    from app.tg import runtime
    from app.tg.indexer import Indexer

    stopped: list[int] = []

    async def no_start(self) -> None:
        return None

    async def stop(self) -> None:
        stopped.append(self.gateway.chat_id)

    monkeypatch.setattr(Indexer, "start", no_start)
    monkeypatch.setattr(Indexer, "stop", stop)
    pool = pool_module.IndexerPool(object(), database.session_factory(), get_settings())
    try:
        await pool.start([C1, C2])
        await pool.remove(C1)
        await pool.remove(C1)  # повторно — без последствий
        assert stopped == [C1]
        assert runtime.gateway_for(C1) is None and runtime.gateway_for(C2) is not None
    finally:
        await pool.stop()
        runtime.reset()
