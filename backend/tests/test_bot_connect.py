"""Бот подключает чат командой /connect, из такого чата создаётся проект, который собирает бот.

Telegram подставной: права в чате (`get_permissions`), сообщения бота и события — заглушки. Настоящий
Telegram это не проверялось: что бот видит чат, что команду доставляют при выключенной приватности,
что права читаются — нужно проверить на первом боевом чате (см. DECISIONS.md).
"""

import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from alembic import command
from app import approvals, models
from app import db as database
from app.auth import telegram as tg_module
from app.config import get_settings
from app.constants import Collector
from app.services import bot_chats, projects
from tests.test_approval import BOSS, FakeBot, PoolWithRemove, as_boss
from tests.test_auth import FakeMembership
from tests.test_self_service import C1, C2, C3, STRANGER, FakeClient, new_project, sign_in

BOT_NAME = "brass_bot"
BOT_ID = 7777
OTHER = 8102  # другой администратор другого чата


class ChatBot(FakeBot):
    """Бот сайта: пишет сообщения и знает, кто в чате администратор."""

    def __init__(self) -> None:
        super().__init__()
        self.admins: set[int] = set()
        self.rights_error: Exception | None = None

    async def get_me(self):
        return SimpleNamespace(id=BOT_ID, username=BOT_NAME)

    async def get_permissions(self, chat, user):
        if self.rights_error is not None:
            raise self.rights_error
        admin = user.id in self.admins
        return SimpleNamespace(is_admin=admin, is_creator=False)


@pytest.fixture
def site(bound_chat, client, monkeypatch):
    """Приложение с ботом сайта и подтверждением проектов, как в рабочей конфигурации; юзербот есть."""
    monkeypatch.setenv("SELF_SERVICE_PROJECTS", "true")
    monkeypatch.setenv("PROJECT_APPROVAL", "true")
    get_settings.cache_clear()
    state = client.app.state
    state.tg.bot = ChatBot()
    state.tg.bot_username = BOT_NAME
    state.tg.bot.admins = {BOT_ID, STRANGER}
    state.tg.userbot = FakeClient()
    state.tg.userbot_account = {"username": "brass_helper", "name": "Помощник"}
    state.tg.membership = FakeMembership(admins={C2: {STRANGER}}, titles={C2: "Клип"})
    state.tg.sync_pause_sec = 0
    state.indexer_pool = PoolWithRemove()
    return client


def connect(site, chat_id=C1, *, tg_id=STRANGER, title="Мой фильм", bot_admin=True, forum=False):
    return site.app.state.tg.connect_chat(
        chat_id=chat_id,
        title=title,
        forum=forum,
        sender_tg_id=tg_id,
        sender_admin=True,
        bot_admin=bot_admin,
    )


def rows(db) -> dict[int, models.BotChat]:
    db.expire_all()
    return {r.chat_id: r for r in db.scalars(select(models.BotChat))}


# --- команда /connect: что решает бот --------------------------------------------------------------


def test_an_admin_connects_a_chat_and_it_is_remembered_with_who_and_how(site, db):
    reply = connect(site, forum=True)
    assert reply == tg_module.MSG_CONNECTED
    row = rows(db)[C1]
    assert (row.title, row.connected_by_tg_id, row.bot_admin, row.forum) == (
        "Мой фильм",
        STRANGER,
        True,
        True,
    )


def test_a_bot_without_admin_rights_connects_but_warns_that_it_will_see_nothing(site, db):
    reply = connect(site, bot_admin=False)
    assert reply.startswith(tg_module.MSG_CONNECTED) and tg_module.MSG_BOT_NOT_ADMIN in reply
    assert rows(db)[C1].bot_admin is False


def test_an_ordinary_member_cannot_connect_a_chat(site, db):
    reply = site.app.state.tg.connect_chat(
        chat_id=C1,
        title="Чужой",
        forum=False,
        sender_tg_id=OTHER,
        sender_admin=False,
        bot_admin=True,
    )
    assert reply == tg_module.MSG_CONNECT_ONLY_ADMIN
    assert rows(db) == {}


def test_a_second_admin_takes_the_chat_over_and_the_title_follows_the_chat(site, db):
    connect(site, tg_id=STRANGER, title="Старое имя")
    connect(site, tg_id=OTHER, title="Новое имя", bot_admin=False)
    row = rows(db)[C1]
    assert (row.connected_by_tg_id, row.title, row.bot_admin) == (OTHER, "Новое имя", False)
    assert len(rows(db)) == 1


def test_a_chat_that_already_has_a_project_is_not_connected_again(site, db):
    reply = connect(site, chat_id=tg_module_film_chat(db))
    assert "Битва" in reply or "уже подключён к проекту" in reply
    assert rows(db) == {}


def tg_module_film_chat(db) -> int:
    from tests.conftest import BOUND_CHAT

    return BOUND_CHAT


# --- команда /connect: событие Telegram -----------------------------------------------------------------


class Event:
    def __init__(self, text: str, *, chat_id=C1, sender=STRANGER, private=False, forum=False):
        self.raw_text, self.chat_id, self.is_private = text, chat_id, private
        self._sender, self._forum = sender, forum
        self.replies: list[str] = []

    async def get_chat(self):
        return SimpleNamespace(id=self.chat_id, title="Мой фильм", forum=self._forum)

    async def get_sender(self):
        return SimpleNamespace(id=self._sender)

    async def respond(self, text: str):
        self.replies.append(text)


async def test_the_command_from_an_admin_in_a_group_connects_the_chat(site, db):
    event = Event("/connect")
    await site.app.state.tg._on_connect(event)
    assert event.replies == [tg_module.MSG_CONNECTED]
    assert rows(db)[C1].connected_by_tg_id == STRANGER and rows(db)[C1].bot_admin is True


@pytest.mark.parametrize("text", ["/connect", "/connect@brass_bot", "/CONNECT@Brass_Bot"])
async def test_the_command_addressed_to_this_bot_is_accepted(site, db, text):
    event = Event(text)
    await site.app.state.tg._on_connect(event)
    assert event.replies and C1 in rows(db)


async def test_the_command_addressed_to_another_bot_is_ignored(site, db):
    event = Event("/connect@someone_else_bot")
    await site.app.state.tg._on_connect(event)
    assert event.replies == [] and rows(db) == {}


async def test_a_member_who_is_not_an_admin_is_refused_by_what_telegram_says(site, db):
    event = Event("/connect", sender=OTHER)  # OTHER администратором не числится
    await site.app.state.tg._on_connect(event)
    assert event.replies == [tg_module.MSG_CONNECT_ONLY_ADMIN] and rows(db) == {}


async def test_when_rights_cannot_be_read_the_bot_says_what_to_do_and_records_nothing(site, db):
    site.app.state.tg.bot.rights_error = RuntimeError("CHAT_ADMIN_REQUIRED")
    event = Event("/connect")
    await site.app.state.tg._on_connect(event)
    assert event.replies == [tg_module.MSG_CONNECT_UNKNOWN_ADMIN] and rows(db) == {}


async def test_a_bot_that_is_not_an_admin_is_told_so_in_the_reply(site, db):
    site.app.state.tg.bot.admins = {STRANGER}  # самого бота среди администраторов нет
    event = Event("/connect")
    await site.app.state.tg._on_connect(event)
    assert tg_module.MSG_BOT_NOT_ADMIN in event.replies[0]
    assert rows(db)[C1].bot_admin is False


async def test_in_a_private_chat_the_bot_explains_where_to_send_the_command(site, db):
    event = Event("/connect", private=True)
    await site.app.state.tg._on_message(event)
    assert event.replies == [tg_module.MSG_CONNECT_HOW] and rows(db) == {}
    await site.app.state.tg._on_connect(
        Event("/connect", private=True)
    )  # в личке _on_connect молчит
    assert rows(db) == {}


def test_other_messages_do_not_trigger_the_command():
    for text in ("/connected", "connect", "/connect now", "/start", ""):
        assert tg_module.CONNECT_RE.match(text) is None


# --- список чатов -------------------------------------------------------------------------------------------


def chats(site, **params):
    return site.get("/api/projects/available-chats", params=params).json()


def test_a_person_sees_the_chats_they_connected_and_not_other_peoples(site, db):
    connect(site, C1, tg_id=STRANGER, title="Мой фильм")
    connect(site, C3, tg_id=OTHER, title="Чужой чат")
    sign_in(site, STRANGER)
    body = chats(site, userbot=False)
    assert [(c["id"], c["title"], c["via"]) for c in body["chats"]] == [(C1, "Мой фильм", "bot")]
    assert body["ready"] is True and body["bot"] == {"username": BOT_NAME}
    assert body["chats"][0]["bot_admin"] is True


def test_the_site_owner_sees_every_connected_chat(site, db):
    connect(site, C1, tg_id=STRANGER)
    connect(site, C3, tg_id=OTHER, title="Чужой чат")
    as_boss(site)
    assert {c["id"] for c in chats(site, userbot=False)["chats"]} == {C1, C3}


def test_a_chat_with_a_project_is_not_offered_again(site, db):
    connect(site, C1)
    sign_in(site, STRANGER)
    assert new_project(site, chat_id=C1).status_code == 201
    assert chats(site, userbot=False)["chats"] == []


def test_both_sources_are_merged_and_a_chat_in_both_is_shown_once_as_the_bots(site, db):
    site.app.state.tg.membership = FakeMembership(
        admins={C1: {STRANGER}, C2: {STRANGER}}, titles={C1: "Мой фильм", C2: "Клип"}
    )
    connect(site, C1)
    sign_in(site, STRANGER)
    body = chats(site)
    assert [(c["id"], c["via"]) for c in body["chats"]] == [(C1, "bot"), (C2, "userbot")]


def test_the_slow_userbot_scan_can_be_left_out(site, db):
    class Counting(FakeMembership):
        scans = 0

        async def manageable_chats(self, tg_id, exclude):
            Counting.scans += 1
            return await super().manageable_chats(tg_id, exclude)

    site.app.state.tg.membership = Counting(admins={C2: {STRANGER}})
    sign_in(site, STRANGER)
    chats(site, userbot=False)
    assert Counting.scans == 0
    assert [c["id"] for c in chats(site)["chats"]] == [C2] and Counting.scans == 1


def test_without_a_userbot_the_bots_chats_are_still_offered(site, db):
    site.app.state.tg.userbot = None
    connect(site, C1)
    sign_in(site, STRANGER)
    body = chats(site)
    assert body["ready"] is True and [c["id"] for c in body["chats"]] == [C1]


def test_when_the_userbot_scan_fails_the_bots_chats_still_show_with_a_note(site, db):
    site.app.state.tg.membership = FakeMembership(down=True)
    connect(site, C1)
    sign_in(site, STRANGER)
    body = chats(site)
    assert body["ready"] is True and [c["id"] for c in body["chats"]] == [C1]
    assert "юзербота" in body["message"]


def test_when_the_scan_fails_and_the_bot_has_nothing_the_list_is_not_ready(site, db):
    site.app.state.tg.membership = FakeMembership(down=True)
    sign_in(site, STRANGER)
    body = chats(site)
    assert body["ready"] is False and body["chats"] == [] and "не ответил" in body["message"]


def test_with_no_telegram_at_all_the_list_says_so(site, db):
    site.app.state.tg.bot, site.app.state.tg.userbot = None, None
    sign_in(site, STRANGER)
    body = chats(site)
    assert body["ready"] is False and "недоступно" in body["message"]


# --- создание проекта ----------------------------------------------------------------------------------------


def collector_of(db, slug: str) -> str:
    db.expire_all()
    return projects.get_by_slug(db, slug).collector


def test_a_project_from_a_bot_chat_is_collected_by_the_bot_and_waits_for_the_site_owner(site, db):
    connect(site, C1)
    sign_in(site, STRANGER)
    done = new_project(site, chat_id=C1)
    assert done.status_code == 201, done.text
    slug = done.json()["slug"]
    assert done.json()["pending"] is True and collector_of(db, slug) == "bot"
    assert site.app.state.indexer_pool.ensured == []  # до подтверждения бот ничего не сохраняет
    (text,) = site.app.state.tg.bot.to(C1)  # зато в чате объяснено, что происходит
    assert text == tg_module.MSG_PROJECT_WAITING.format(title="Мой фильм")
    assert C1 in site.app.state.tg.membership.reads  # участников прочитали сразу


def test_the_site_owners_project_from_a_bot_chat_starts_collecting_at_once(site, db):
    connect(site, C1, tg_id=BOSS)
    as_boss(site)
    done = new_project(site, chat_id=C1)
    assert done.status_code == 201 and done.json()["pending"] is False
    assert collector_of(db, done.json()["slug"]) == "bot"
    assert site.app.state.indexer_pool.ensured == [C1]
    assert site.app.state.tg.bot.to(C1) == [
        tg_module.MSG_PROJECT_COLLECTING.format(title="Мой фильм")
    ]


def test_the_site_owner_may_create_a_project_from_a_chat_someone_else_connected(site, db):
    connect(site, C1, tg_id=STRANGER)
    as_boss(site)
    assert new_project(site, chat_id=C1).status_code == 201


def test_a_chat_connected_by_someone_else_cannot_be_taken_by_a_stranger(site, db):
    connect(site, C1, tg_id=OTHER)
    sign_in(site, STRANGER)
    refused = new_project(site, chat_id=C1)  # юзербот этого чата тоже не знает
    assert refused.status_code == 403
    with database.session_factory()() as session:
        assert session.scalar(select(models.Project).where(models.Project.tg_chat_id == C1)) is None


def test_a_chat_known_only_to_the_userbot_is_still_collected_by_the_userbot(site, db):
    sign_in(site, STRANGER)
    done = new_project(site, chat_id=C2)
    assert done.status_code == 201
    assert collector_of(db, done.json()["slug"]) == "userbot"
    assert site.app.state.tg.bot.to(C2) == []  # бота в таком чате может не быть: он там молчит


def test_without_a_userbot_an_unconnected_chat_tells_how_to_connect_it(site, db):
    site.app.state.tg.userbot = None
    sign_in(site, STRANGER)
    refused = new_project(site, chat_id=C1)
    assert refused.status_code == 403 and "/connect" in refused.json()["detail"]


def test_without_any_telegram_a_chat_cannot_be_checked(site, db):
    site.app.state.tg.bot, site.app.state.tg.userbot = None, None
    sign_in(site, STRANGER)
    assert new_project(site, chat_id=C1).status_code == 503


def test_the_same_chat_cannot_become_two_projects(site, db):
    connect(site, C1)
    sign_in(site, STRANGER)
    assert new_project(site, chat_id=C1).status_code == 201
    assert new_project(site, chat_id=C1, title="Второй").status_code in (403, 409)


# --- решение владельца сайта: что бот пишет в чат -------------------------------------------------------


def test_the_confirmation_is_announced_in_the_chat_of_a_bot_project(site, db):
    connect(site, C1)
    sign_in(site, STRANGER)
    slug = new_project(site, chat_id=C1).json()["slug"]
    as_boss(site)
    assert site.post(f"/api/projects/{slug}/approve").status_code == 200
    assert site.app.state.indexer_pool.ensured == [C1]  # теперь собирать можно
    assert site.app.state.tg.bot.to(C1)[-1] == tg_module.MSG_PROJECT_COLLECTING.format(
        title="Мой фильм"
    )


def test_the_rejection_is_announced_in_the_chat_and_the_chat_can_be_connected_again(site, db):
    connect(site, C1)
    sign_in(site, STRANGER)
    slug = new_project(site, chat_id=C1).json()["slug"]
    as_boss(site)
    assert site.post(f"/api/projects/{slug}/reject").status_code == 200
    assert site.app.state.tg.bot.to(C1)[-1] == tg_module.MSG_PROJECT_REJECTED.format(
        title="Мой фильм"
    )
    sign_in(site, STRANGER)
    assert [c["id"] for c in chats(site, userbot=False)["chats"]] == [C1]


def test_a_userbot_project_gets_no_message_in_its_chat_on_decisions(site, db):
    sign_in(site, STRANGER)
    slug = new_project(site, chat_id=C2).json()["slug"]
    as_boss(site)
    site.post(f"/api/projects/{slug}/approve")
    assert site.app.state.tg.bot.to(C2) == []


async def test_a_message_that_cannot_be_delivered_does_not_break_the_decision(site, db):
    connect(site, C1)
    sign_in(site, STRANGER)
    slug = new_project(site, chat_id=C1).json()["slug"]

    async def refuse(*_a, **_k):
        raise RuntimeError("бота убрали из чата")

    site.app.state.tg.bot.send_message = refuse
    as_boss(site)
    with database.session_factory()() as session:
        project_id = projects.get_by_slug(session, slug).id
        boss_id = session.scalar(select(models.User.id).where(models.User.tg_id == BOSS))
    outcome = await approvals.decide(site.app, "approve", project_id, boss_id)
    assert outcome.action == "approve"
    db.expire_all()
    assert projects.get_by_slug(db, slug).approved_at is not None


# --- сервис и таблица -------------------------------------------------------------------------------------------


def test_the_service_keeps_one_row_per_chat_and_cuts_a_long_title(db):
    bot_chats.connect(db, chat_id=-5, title="Д" * 500, tg_id=1, bot_admin=True, forum=False)
    bot_chats.connect(db, chat_id=-5, title="Новое", tg_id=2, bot_admin=False, forum=True)
    assert db.query(models.BotChat).count() == 1
    row = bot_chats.get(db, -5)
    assert (row.title, row.connected_by_tg_id, row.forum) == ("Новое", 2, True)
    bot_chats.connect(db, chat_id=-6, title="Д" * 500, tg_id=1, bot_admin=True, forum=False)
    assert len(bot_chats.get(db, -6).title) == bot_chats.MAX_TITLE


def test_a_chat_cannot_be_connected_without_a_name(db):
    from app.services.core import ValidationError

    with pytest.raises(ValidationError):
        bot_chats.connect(db, chat_id=-7, title="   ", tg_id=1, bot_admin=True, forum=False)


def test_available_and_usable_follow_who_connected_and_who_is_the_site_owner(db):
    bot_chats.connect(db, chat_id=-10, title="А", tg_id=1, bot_admin=True, forum=False)
    bot_chats.connect(db, chat_id=-11, title="Б", tg_id=2, bot_admin=True, forum=False)
    assert [c.chat_id for c in bot_chats.available(db, 1, superadmin=False)] == [-10]
    assert {c.chat_id for c in bot_chats.available(db, 99, superadmin=True)} == {-10, -11}
    assert [c.chat_id for c in bot_chats.available(db, 1, superadmin=False, exclude={-10})] == []
    assert bot_chats.usable_by(db, 1, -10, superadmin=False) is not None
    assert bot_chats.usable_by(db, 1, -11, superadmin=False) is None
    assert bot_chats.usable_by(db, 99, -11, superadmin=True) is not None
    assert bot_chats.usable_by(db, 1, -999, superadmin=False) is None


def test_projects_created_in_code_default_to_the_userbot(db):
    from app.models import User

    with database.session_factory()() as session:  # сессия `db` привязана к проекту фильма
        user = User(tg_id=BOSS, name="Я", color="#000000", role="owner")  # владелец сайта
        session.add(user)
        session.flush()
        created = projects.create(
            session, user, title="Тест", chat_id=None, settings=get_settings()
        )
        assert created.collector == Collector.USERBOT.value
        other = projects.create(
            session,
            user,
            title="Бот",
            chat_id=-12,
            collector=Collector.BOT,
            settings=get_settings(),
        )
        assert other.collector == "bot"


def test_migration_0012_creates_the_table_with_one_row_per_chat(env):
    from tests.test_migrations import _cfg, _head, _populated_0006  # noqa: PLC2701

    path = _populated_0006(env)
    command.upgrade(_cfg(), "head")
    db = sqlite3.connect(path)
    assert db.execute("select version_num from alembic_version").fetchone() == (_head(),)
    insert = (
        "insert into bot_chat(chat_id,title,connected_by_tg_id,bot_admin,forum,connected_at)"
        " values (?, 'Чат', 1, 1, 0, '2026-11-06 00:00:00')"
    )
    db.execute(insert, (-100,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(insert, (-100,))
    db.close()
