"""Свои проекты: вход для любого пользователя Telegram, поиск чатов и создание проекта."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import db as database
from app import models
from app.auth import flow
from app.auth import membership as membership_module
from app.auth.membership import ChatInfo, MembershipUnavailable, TelethonMembership
from app.auth.tokens import LoginTokenStore
from app.config import get_settings
from app.constants import Role
from app.permissions import PermissionDenied
from app.services import core, members, projects, users
from tests.conftest import BOUND_CHAT, OWNER_TG_ID
from tests.test_auth import FakeMembership

FILM = BOUND_CHAT  # чат проекта фильма (он уже занят)
C1, C2, C3 = -1001110000001, -1001110000002, -1001110000003
STRANGER = 8101  # человек из «другого чата», на сайт раньше не входил


class FakeClient:
    """Юзербот для приложения: его останавливает `TelegramService.stop()`."""

    async def disconnect(self) -> None:
        return None


class FakePool:
    def __init__(self) -> None:
        self.ensured: list[int] = []

    async def ensure(self, chat_id: int) -> None:
        self.ensured.append(chat_id)


@pytest.fixture
def tg(bound_chat, client, monkeypatch):
    """Приложение с подключённым (подставным) юзерботом. `bound_chat` закрывает самообслуживание
    для старых тестов, здесь оно нужно включённым, как в рабочей конфигурации."""
    monkeypatch.setenv("SELF_SERVICE_PROJECTS", "true")
    monkeypatch.setenv("PROJECT_APPROVAL", "false")  # подтверждение проверяют тесты шлюза
    get_settings.cache_clear()
    state = client.app.state
    state.tg.userbot = FakeClient()
    state.tg.userbot_account = {"username": "brass_helper", "name": "Помощник"}
    state.tg.membership = FakeMembership(
        admins={FILM: {STRANGER}, C1: {STRANGER}, C2: {STRANGER, 8102}, C3: {8102}},
        titles={C1: "Мой фильм", C2: "Клип"},
    )
    state.tg.sync_pause_sec = 0
    state.indexer_pool = FakePool()
    return client


def sign_in(client, tg_id: int, name: str = "Человек") -> int:
    """Входит как человек из Telegram без единого проекта (как после первого входа через бота)."""
    from app.auth import session

    with database.session_factory()() as db:
        user = users.upsert_from_telegram(
            db, tg_id=tg_id, username=None, name=name, avatar_path=None, owner_tg_id=None
        )
        db.commit()
        user_id = user.id
    token = session._serializer(get_settings()).dumps({"uid": user_id})
    client.cookies.clear()
    client.cookies.set(session.COOKIE_NAME, token)
    return user_id


def new_project(client, **body):
    payload = {"title": "Мой фильм", "chat_id": C1, **body}
    return client.post("/api/projects", json=payload)


# --- открытый вход -------------------------------------------------------------------------------


async def login(tg_id: int, fake: FakeMembership) -> flow.LoginResult:
    return await flow.authenticate(flow.TgProfile(tg_id, None, f"U{tg_id}"), fake, get_settings())


async def test_anyone_with_telegram_logs_in_and_has_no_projects(bound_chat, db, monkeypatch):
    monkeypatch.setenv("SELF_SERVICE_PROJECTS", "true")
    get_settings.cache_clear()
    result = await login(STRANGER, FakeMembership(chats={FILM: {1}}))
    assert result.outcome is flow.LoginOutcome.OK
    user = db.get(models.User, result.user_id)
    assert db.query(models.ProjectMember).filter_by(user_id=user.id).count() == 0


async def test_a_telegram_outage_does_not_stop_a_newcomer_either(bound_chat, db, monkeypatch):
    monkeypatch.setenv("SELF_SERVICE_PROJECTS", "true")
    get_settings.cache_clear()
    result = await login(STRANGER, FakeMembership(down=True))
    assert result.outcome is flow.LoginOutcome.OK  # проектов у него нет, защищать нечего


async def test_the_old_rule_returns_with_the_switch_off(bound_chat, db):
    # bound_chat выключает самообслуживание: входят только участники чатов проектов
    result = await login(STRANGER, FakeMembership(chats={FILM: {1}}))
    assert result.outcome is flow.LoginOutcome.NOT_MEMBER


async def test_a_person_without_projects_is_not_closed_out_by_the_sync(bound_chat, db, monkeypatch):
    from app.auth.telegram import TelegramService

    monkeypatch.setenv("SELF_SERVICE_PROJECTS", "true")
    get_settings.cache_clear()
    fake = FakeMembership(chats={FILM: {1}})
    await login(STRANGER, fake)
    service = TelegramService(get_settings(), LoginTokenStore())
    service.membership, service.sync_pause_sec = fake, 0
    await service.sync_members()
    db.expire_all()
    user = db.scalar(select(models.User).where(models.User.tg_id == STRANGER))
    assert user.access_revoked_at is None  # доступ закрывается только в закрытом режиме


# --- кто может создавать --------------------------------------------------------------------------


def test_the_session_says_who_may_create_projects(tg):
    sign_in(tg, STRANGER)
    body = tg.get("/api/session").json()
    assert body["projects"] == [] and body["can_create_projects"] is True


def test_the_limit_counts_projects_where_the_person_is_owner(tg):
    sign_in(tg, STRANGER)
    for n in range(3):
        assert new_project(tg, title=f"Проект {n}", chat_id=C1 if n == 0 else C2).status_code in (
            201,
            409,
        )
    # 4-й и дальше: владелец уже в трёх (или упёрся в занятый чат) — проверяем лимит отдельно ниже
    with database.session_factory()() as db:
        user = db.scalar(select(models.User).where(models.User.tg_id == STRANGER))
        assert projects.owned_count(db, user) == 2  # C1 и C2 созданы, третий — тот же занятый чат


def test_a_superadmin_creates_without_limit_and_a_switch_off_stops_the_rest(tg, monkeypatch):
    with database.session_factory()() as db:
        owner = users.upsert_from_telegram(
            db, tg_id=OWNER_TG_ID, username=None, name="Босс", avatar_path=None,
            owner_tg_id=OWNER_TG_ID,
        )  # fmt: skip
        stranger = users.upsert_from_telegram(
            db, tg_id=STRANGER, username=None, name="Гость", avatar_path=None, owner_tg_id=None
        )
        db.commit()
        assert projects.can_create(db, owner) and projects.can_create(db, stranger)
        monkeypatch.setenv("SELF_SERVICE_PROJECTS", "false")
        get_settings.cache_clear()
        assert projects.can_create(db, owner) is True
        assert projects.can_create(db, stranger) is False
        monkeypatch.setenv("SELF_SERVICE_PROJECTS", "true")
        monkeypatch.setenv("MAX_PROJECTS_PER_USER", "0")
        get_settings.cache_clear()
        assert projects.can_create(db, stranger) is False
        assert projects.can_create(db, owner) is True


# --- чаты, которыми можно распоряжаться ------------------------------------------------------------


def test_available_chats_are_those_where_the_person_is_admin_and_which_are_free(tg):
    sign_in(tg, STRANGER)
    body = tg.get("/api/projects/available-chats").json()
    assert body["ready"] is True
    assert body["userbot"] == {"username": "brass_helper", "name": "Помощник"}
    assert [(c["id"], c["title"]) for c in body["chats"]] == [(C1, "Мой фильм"), (C2, "Клип")]
    assert FILM not in {c["id"] for c in body["chats"]}  # чат фильма уже занят проектом
    assert C3 not in {c["id"] for c in body["chats"]}  # там администратор другой человек


def test_available_chats_say_why_there_is_no_list(tg):
    sign_in(tg, STRANGER)
    tg.app.state.tg.userbot = None
    body = tg.get("/api/projects/available-chats").json()
    assert body["ready"] is False and body["chats"] == [] and "Telegram" in body["message"]
    tg.app.state.tg.userbot = FakeClient()
    tg.app.state.tg.membership = FakeMembership(down=True)
    body = tg.get("/api/projects/available-chats").json()
    assert body["ready"] is False and "не ответил" in body["message"]


def test_available_chats_need_a_login_and_the_right_to_create(tg, monkeypatch):
    tg.cookies.clear()
    assert tg.get("/api/projects/available-chats").status_code == 401
    sign_in(tg, STRANGER)
    monkeypatch.setenv("SELF_SERVICE_PROJECTS", "false")
    get_settings.cache_clear()
    assert tg.get("/api/projects/available-chats").status_code == 403


# --- создание --------------------------------------------------------------------------------------


def test_a_newcomer_creates_a_project_in_their_chat_and_owns_it(tg):
    sign_in(tg, STRANGER, "Новичок")
    with database.session_factory()() as db:  # в чате C1 уже есть другой человек с сайта
        other = users.upsert_from_telegram(
            db, tg_id=8103, username=None, name="Коллега", avatar_path=None, owner_tg_id=None
        )
        db.commit()
        other_id = other.id
    tg.app.state.tg.membership.chats[C1] = {STRANGER, 8103}

    done = new_project(tg, title="Кривое зеркало", title_en="Crooked Mirror")
    assert done.status_code == 201, done.text
    assert done.json() == {
        "slug": "crooked-mirror",
        "title": "Кривое зеркало",
        "title_en": "Crooked Mirror",
        "role": "owner",
        "archived": False,
        "pending": False,
    }
    assert tg.app.state.indexer_pool.ensured == [C1]  # индексатор чата запущен сразу

    session = tg.get("/api/session").json()
    assert [p["slug"] for p in session["projects"]] == ["crooked-mirror"]
    me = tg.get("/api/p/crooked-mirror/me").json()
    assert me["user"]["role"] == "owner" and me["abilities"]["manage_users"] is True
    project = tg.get("/api/p/crooked-mirror/project").json()
    assert (project["storage_limit_gb"], project["contest"]) == (1.0, "—")
    with database.session_factory()() as db:  # чат привязан, знакомый по чату стал участником
        row = projects.get_by_slug(db, "crooked-mirror")
        assert row.tg_chat_id == C1
        colleague = members.get(db, row.id, other_id)
        assert colleague is not None and colleague.active and colleague.role == Role.TEAM.value


def test_the_deadline_defaults_to_sixty_days_and_the_internal_one_is_two_days_earlier(tg):
    sign_in(tg, STRANGER)
    body = new_project(tg).json()
    project = tg.get(f"/api/p/{body['slug']}/project").json()
    official = datetime.fromisoformat(project["deadline_official"])
    internal = datetime.fromisoformat(project["deadline_internal"])
    assert official - internal == timedelta(days=2)
    days = (official - datetime.now(UTC)).days
    assert 59 <= days <= 61


def test_a_chosen_deadline_is_kept_and_a_past_one_is_refused(tg):
    sign_in(tg, STRANGER)
    assert new_project(tg, deadline="2020-01-01").status_code == 422
    tomorrow = (datetime.now(UTC) + timedelta(days=30)).date().isoformat()
    done = new_project(tg, deadline=tomorrow)
    assert done.status_code == 201
    project = tg.get(f"/api/p/{done.json()['slug']}/project").json()
    assert datetime.fromisoformat(project["deadline_official"]).date().isoformat() >= tomorrow


@pytest.mark.parametrize(
    "body",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "Ок", "title_en": ""},
        {"title": "Ок", "slug": "hacked"},  # адрес строится из названия, а не задаётся
        {"title": "Ок", "storage_limit_gb": 100},  # лимит места клиент не назначает
        {"title": "Ок", "role": "owner"},
        {"title": 5},
    ],
)
def test_bad_bodies_are_refused_and_nothing_is_created(tg, body):
    sign_in(tg, STRANGER)
    assert tg.post("/api/projects", json={"chat_id": C1, **body}).status_code == 422
    assert tg.get("/api/session").json()["projects"] == []


def test_an_ordinary_person_cannot_create_a_project_without_a_chat(tg):
    sign_in(tg, STRANGER)
    response = tg.post("/api/projects", json={"title": "Без чата"})
    assert response.status_code == 422 and "чат" in response.json()["detail"]
    assert tg.get("/api/session").json()["projects"] == []


def test_a_superadmin_may_create_a_project_without_a_chat(tg):
    sign_in(tg, OWNER_TG_ID, "Босс")
    done = tg.post("/api/projects", json={"title": "Черновик"})
    assert done.status_code == 201, done.text
    with database.session_factory()() as db:
        assert projects.get_by_slug(db, done.json()["slug"]).tg_chat_id is None
    assert tg.app.state.indexer_pool.ensured == []


def test_the_chat_is_checked_on_the_server_so_a_foreign_chat_cannot_be_taken(tg):
    sign_in(tg, STRANGER)
    assert new_project(tg, chat_id=C3).status_code == 403  # там администратор другой человек
    assert new_project(tg, chat_id=-1009999999999).status_code == 403  # юзербота там нет
    assert tg.get("/api/session").json()["projects"] == []
    assert tg.app.state.indexer_pool.ensured == []


def test_an_ordinary_member_of_a_chat_cannot_claim_it_but_an_admin_can(tg):
    """Простому участнику чат не отдаём: иначе он стал бы владельцем чужой команды."""
    tg.app.state.tg.membership.chats[C2] = {STRANGER, 8104}
    sign_in(tg, 8104)
    assert new_project(tg, chat_id=C2).status_code == 403  # он в чате C2, но не администратор
    sign_in(tg, STRANGER)
    assert new_project(tg, chat_id=C2).status_code == 201


def test_a_chat_that_already_belongs_to_a_project_is_refused(tg):
    sign_in(tg, STRANGER)
    assert new_project(tg, chat_id=FILM).status_code == 409  # чат фильма
    assert new_project(tg, chat_id=C1).status_code == 201
    again = new_project(tg, title="Второй", chat_id=C1)
    assert again.status_code == 409 and "уже привязан" in again.json()["detail"]
    with database.session_factory()() as db:
        assert db.query(models.Project).filter_by(tg_chat_id=C1).count() == 1


def test_without_telegram_a_project_with_a_chat_is_not_created(tg):
    sign_in(tg, STRANGER)
    tg.app.state.tg.userbot = None
    assert new_project(tg).status_code == 503  # непроверенный чат не принимаем
    tg.app.state.tg.userbot = FakeClient()
    tg.app.state.tg.membership = FakeMembership(down=True)
    assert new_project(tg).status_code == 503
    assert tg.get("/api/session").json()["projects"] == []


def test_one_person_cannot_own_more_than_the_limit(tg, monkeypatch):
    monkeypatch.setenv("MAX_PROJECTS_PER_USER", "2")
    get_settings.cache_clear()
    tg.app.state.tg.membership.admins[C3].add(STRANGER)
    sign_in(tg, STRANGER)
    assert new_project(tg, title="Раз", chat_id=C1).status_code == 201
    assert new_project(tg, title="Два", chat_id=C2).status_code == 201
    third = new_project(tg, title="Три", chat_id=C3)
    assert third.status_code == 403
    assert tg.get("/api/session").json()["can_create_projects"] is False
    assert tg.get("/api/projects/available-chats").status_code == 403


def test_the_same_title_gets_a_different_address(tg):
    tg.app.state.tg.membership.admins[C3].add(STRANGER)
    sign_in(tg, STRANGER)
    first = new_project(tg, title="Кино", title_en="Movie", chat_id=C1).json()["slug"]
    second = new_project(tg, title="Кино", title_en="Movie", chat_id=C2).json()["slug"]
    assert (first, second) == ("movie", "movie-2")


def test_a_new_project_is_isolated_from_the_film_and_from_other_people(tg):
    sign_in(tg, STRANGER)
    slug = new_project(tg).json()["slug"]
    assert tg.get(f"/api/p/{slug}/shots").json() == []  # пустой проект, фильма в нём нет
    assert tg.get("/api/p/brass-spyglass/shots").status_code == 404  # к фильму доступа нет
    sign_in(tg, 8105, "Посторонний")
    assert tg.get(f"/api/p/{slug}/shots").status_code == 404
    assert tg.get("/api/session").json()["projects"] == []


def test_the_owner_of_a_new_project_manages_it_like_any_owner(tg):
    sign_in(tg, STRANGER)
    slug = new_project(tg).json()["slug"]
    renamed = tg.patch(f"/api/p/{slug}/project", json={"title": "Переименован"})
    assert renamed.status_code == 200 and renamed.json()["slug"] == slug
    made = tg.post(f"/api/p/{slug}/tasks", json={"code": "T-01", "title": "Первая задача"})
    assert made.status_code == 201, made.text
    assert [t["code"] for t in tg.get(f"/api/p/{slug}/tasks").json()] == ["T-01"]


def test_creating_a_project_needs_a_login_and_the_right_origin(tg):
    tg.cookies.clear()
    assert tg.post("/api/projects", json={"title": "Ок", "chat_id": C1}).status_code == 401
    sign_in(tg, STRANGER)
    bad = tg.post(
        "/api/projects",
        json={"title": "Ок", "chat_id": C1},
        headers={"Origin": "https://evil.example"},
    )
    assert bad.status_code == 403
    assert tg.get("/api/session").json()["projects"] == []


# --- сервис ---------------------------------------------------------------------------------------


def test_the_service_refuses_what_the_api_refuses(bound_chat, db, monkeypatch):
    monkeypatch.setenv("SELF_SERVICE_PROJECTS", "true")
    get_settings.cache_clear()
    with database.session_factory()() as other:
        stranger = users.upsert_from_telegram(
            other, tg_id=STRANGER, username=None, name="X", avatar_path=None, owner_tg_id=None
        )
        other.commit()
        stranger_id = stranger.id
    user = db.get(models.User, stranger_id)
    with pytest.raises(core.ValidationError):
        projects.create(db, user, title="  ", chat_id=C1)
    with pytest.raises(core.ValidationError):
        projects.create(db, user, title="Ок", chat_id=None)
    with pytest.raises(core.ConflictError):
        projects.create(db, user, title="Ок", chat_id=BOUND_CHAT)
    with pytest.raises(core.ValidationError):
        projects.create(db, user, title="Ок", chat_id=C1, deadline=datetime(2001, 1, 1).date())


def test_a_close_deadline_leaves_no_internal_deadline_in_the_past(db):
    with database.session_factory()() as other:
        user = users.upsert_from_telegram(
            other, tg_id=STRANGER, username=None, name="X", avatar_path=None, owner_tg_id=None
        )
        other.commit()
        user_id = user.id
    now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    user = db.get(models.User, user_id)
    project = projects.create(db, user, title="Скоро", chat_id=C1, deadline=now.date(), now=now)
    assert project.deadline_internal == project.deadline_official  # «за два дня» уже не получится


def test_creation_is_forbidden_to_a_person_over_the_limit(db, monkeypatch):
    monkeypatch.setenv("MAX_PROJECTS_PER_USER", "0")
    get_settings.cache_clear()
    with database.session_factory()() as other:
        user = users.upsert_from_telegram(
            other, tg_id=STRANGER, username=None, name="X", avatar_path=None, owner_tg_id=None
        )
        other.commit()
        user_id = user.id
    with pytest.raises(PermissionDenied):
        projects.create(db, db.get(models.User, user_id), title="Ок", chat_id=C1)


# --- чтение чатов юзерботом -------------------------------------------------------------------------


class FakeDialog:
    def __init__(self, chat_id: int, title: str, *, group: bool = True, size: int | None = 5):
        self.id, self.title, self.is_group = chat_id, title, group
        self.entity = SimpleNamespace(participants_count=size, id=chat_id)


class FakeUserbot:
    """Юзербот с диалогами. `admins[chat]` — администраторы, `members[chat]` — все участники."""

    def __init__(self) -> None:
        self.dialogs: list[FakeDialog] = []
        self.members: dict[int, set[int]] = {}
        self.admins: dict[int, set[int]] = {}
        self.broken: set[int] = set()
        self.dialogs_down = False
        self.scans = 0

    async def iter_dialogs(self, limit=None):
        self.scans += 1
        if self.dialogs_down:
            raise ConnectionError("обрыв")
        for dialog in self.dialogs:
            yield dialog

    async def iter_participants(self, chat):
        chat_id = chat.id if hasattr(chat, "id") else chat
        if chat_id in self.broken:
            raise ConnectionError("нет доступа")
        for tg_id in self.members.get(chat_id, set()):
            yield SimpleNamespace(id=tg_id, chat=chat_id)

    async def get_permissions(self, chat, participant):
        chat_id = participant.chat
        yes = participant.id in self.admins.get(chat_id, set())
        return SimpleNamespace(is_admin=yes, is_creator=False)

    async def get_input_entity(self, chat_id):
        if chat_id not in {d.id for d in self.dialogs}:
            raise ValueError("нет такого чата")
        return SimpleNamespace(id=chat_id)

    async def get_dialogs(self):
        return None

    async def get_entity(self, chat):
        title = next(d.title for d in self.dialogs if d.id == chat.id)
        return SimpleNamespace(title=title)


@pytest.fixture
def userbot():
    bot = FakeUserbot()
    bot.dialogs = [
        FakeDialog(C1, "Мой фильм"),
        FakeDialog(C2, "Клип"),
        FakeDialog(C3, "Чужой чат"),
        FakeDialog(-1001, "Личная переписка", group=False),
        FakeDialog(-1002, "Огромный публичный чат", size=5000),
    ]
    bot.members = {C1: {7, 8}, C2: {7, 8}, C3: {8}, -1002: {7}}
    bot.admins = {C1: {7}, C2: {8}, C3: {8}, -1002: {7}}
    return bot


async def test_only_groups_where_the_person_is_an_admin_are_offered(userbot):
    reader = TelethonMembership(userbot)
    assert await reader.manageable_chats(7, []) == [ChatInfo(C1, "Мой фильм")]
    assert await reader.manageable_chats(8, []) == [ChatInfo(C2, "Клип"), ChatInfo(C3, "Чужой чат")]
    assert await reader.manageable_chats(9, []) == []  # человека нет ни в одном чате


async def test_taken_chats_are_not_offered_and_huge_chats_are_skipped(userbot):
    reader = TelethonMembership(userbot)
    assert await reader.manageable_chats(8, [C3]) == [ChatInfo(C2, "Клип")]
    ids = {c.id for c in await reader.manageable_chats(7, [])}
    assert -1002 not in ids and -1001 not in ids  # крупный чат и личная переписка не командные


async def test_one_broken_chat_does_not_hide_the_others_and_a_dead_account_raises(userbot):
    userbot.broken = {C1}
    reader = TelethonMembership(userbot)
    assert await reader.manageable_chats(8, []) == [ChatInfo(C2, "Клип"), ChatInfo(C3, "Чужой чат")]
    userbot.dialogs_down = True
    with pytest.raises(MembershipUnavailable):
        await TelethonMembership(userbot).manageable_chats(8, [])


async def test_the_chat_scan_is_cached_for_a_few_seconds(userbot, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(membership_module.time, "monotonic", lambda: now[0])
    reader = TelethonMembership(userbot)
    await reader.manageable_chats(7, [])
    await reader.manageable_chats(7, [C1])
    assert userbot.scans == 1  # повторный «Обновить» не гоняет весь Telegram заново
    now[0] += 30
    await reader.manageable_chats(7, [])
    assert userbot.scans == 2


async def test_a_chat_is_checked_by_id_for_admin_rights(userbot):
    reader = TelethonMembership(userbot)
    assert await reader.chat_for(7, C1) == ChatInfo(C1, "Мой фильм")
    assert await reader.chat_for(8, C1) is None  # в чате, но не администратор
    assert await reader.chat_for(9, C1) is None  # не в чате
    assert await reader.chat_for(7, -1009999) is None  # юзербота в чате нет
    assert await reader.chat_for(8, C1, require_admin=False) == ChatInfo(C1, "Мой фильм")
    userbot.broken = {C2}
    with pytest.raises(MembershipUnavailable):
        await reader.chat_for(8, C2)
