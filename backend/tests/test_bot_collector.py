"""Бот как сборщик медиа новых проектов (инфраструктура): шлюз «только новые», пул из двух клиентов,
чтение участников тем, кто собирает чат, миграция `project.collector`.

Как и в `test_tg_telethon_contract.py`, запросы и сообщения собираются из настоящих классов Telethon,
а клиент подставной: расхождения с библиотекой видны без сети. С настоящим Telegram это не проверено.
"""

import asyncio
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from telethon import types
from telethon.tl.functions import messages as fn_messages

from alembic import command
from app import db as database
from app import models
from app.auth.membership import MembershipUnavailable, RoutedMembership
from app.config import get_settings
from app.constants import Collector
from app.services import projects
from app.tg import pool as pool_module
from app.tg import runtime
from app.tg.indexer import Indexer
from app.tg.limiter import RateLimiter
from app.tg.telethon_gateway import TelethonGateway
from app.tg.types import GENERAL_TOPIC
from tests.test_tg_telethon_contract import CHAT, ForumTopic, message, photo

# --- шлюз бота ---------------------------------------------------------------------------------------


class BotClient:
    """Клиент бота: историю читать нельзя, список диалогов тоже, названия тем — как повезёт."""

    def __init__(self, *, topics_work: bool = True, titles: dict[int, str] | None = None) -> None:
        self.topics_work = topics_work
        self.titles = titles if titles is not None else {}
        self.requests: list[object] = []
        self.handler = None
        self.known = True

    async def get_input_entity(self, chat):
        if not self.known:
            raise ValueError("Could not find the input entity")
        return types.InputPeerChannel(channel_id=1234567890, access_hash=1)

    async def get_dialogs(self, *args, **kwargs):
        raise AssertionError("боту список диалогов недоступен")

    def iter_messages(self, *args, **kwargs):
        raise AssertionError("бот не читает историю")

    async def get_entity(self, peer):
        if not self.topics_work:
            raise RuntimeError("BOT_METHOD_INVALID")
        return types.Channel(
            id=1234567890, title="Команда", photo=types.ChatPhotoEmpty(),
            date=datetime(2026, 11, 1, tzinfo=UTC), forum=True, megagroup=True,
        )  # fmt: skip

    async def __call__(self, request):
        self.requests.append(request)
        if isinstance(request, fn_messages.GetForumTopicsRequest):
            return types.messages.ForumTopics(
                count=0, topics=[], messages=[], chats=[], users=[], pts=0
            )
        if isinstance(request, fn_messages.GetForumTopicsByIDRequest):
            wanted = request.topics[0]
            if wanted not in self.titles:
                raise RuntimeError("TOPIC_ID_INVALID")
            topic = ForumTopic(wanted, self.titles[wanted], 1)
            return types.messages.ForumTopics(
                count=1, topics=[topic], messages=[], chats=[], users=[], pts=0
            )
        raise AssertionError(request)

    def add_event_handler(self, handler, event):
        self.handler = handler


def bot_gateway(client: BotClient) -> TelethonGateway:
    return TelethonGateway(client, CHAT, RateLimiter(interval=0), live_only=True)


def in_topic(topic_id: int, message_id: int = 40):
    reply = types.MessageReplyHeader(
        forum_topic=True, reply_to_msg_id=topic_id, reply_to_top_id=topic_id
    )
    return message(id=message_id, media=types.MessageMediaPhoto(photo=photo()), reply_to=reply)


async def test_a_bot_gateway_has_no_history_and_never_asks_for_it():
    gateway = bot_gateway(BotClient())
    items = [item async for item in gateway.history(GENERAL_TOPIC)]
    assert items == []  # iter_messages у клиента бота роняет тест: к истории шлюз не обращался


async def test_a_bot_falls_back_to_one_general_topic_when_telegram_will_not_list_topics():
    gateway = bot_gateway(BotClient(topics_work=False))
    topics = await gateway.topics()
    assert [(t.topic_id, t.title) for t in topics] == [(GENERAL_TOPIC, "Чат")]


async def test_a_bot_that_does_not_know_the_chat_says_so_instead_of_scanning_dialogs():
    client = BotClient()
    client.known = False
    gateway = bot_gateway(client)
    assert [t.topic_id for t in await gateway.topics()] == [GENERAL_TOPIC]  # чат пока не виден
    with pytest.raises(LookupError, match="не состоит"):
        await gateway.thumb(1)  # get_dialogs у клиента бота роняет тест: шлюз его не зовёт


async def test_topics_seen_in_new_messages_join_the_list_with_their_real_names():
    client = BotClient(titles={5: "Персонажи"})
    gateway = bot_gateway(client)
    got = []

    async def callback(item, topic_id):
        got.append((item.message_id, topic_id, item.media.kind if item.media else None))

    gateway.on_new(callback)
    await client.handler(SimpleNamespace(message=in_topic(5)))
    assert got == [(40, 5, "image")]  # тема форума распознана, хотя список тем бот не получал
    topics = await gateway.topics()
    assert (5, "Персонажи") in [(t.topic_id, t.title) for t in topics]
    assert any(isinstance(r, fn_messages.GetForumTopicsByIDRequest) for r in client.requests)
    await client.handler(SimpleNamespace(message=in_topic(5, 41)))  # название спрашивают один раз
    assert sum(isinstance(r, fn_messages.GetForumTopicsByIDRequest) for r in client.requests) == 1


async def test_a_topic_whose_name_cannot_be_read_gets_a_neutral_name():
    client = BotClient(topics_work=False)
    gateway = bot_gateway(client)

    async def callback(item, topic_id):
        return None

    gateway.on_new(callback)
    await client.handler(SimpleNamespace(message=in_topic(9)))
    assert (9, "Тема 9") in [(t.topic_id, t.title) for t in await gateway.topics()]


async def test_the_userbot_gateway_is_unchanged():
    """Режим «только новые» включается только флагом: у юзербота история и диалоги на месте."""
    gateway = TelethonGateway(BotClient(), CHAT, RateLimiter(interval=0))
    assert gateway.live_only is False
    with pytest.raises(AssertionError, match="не читает историю"):
        [item async for item in gateway.history(GENERAL_TOPIC)]


def test_telethon_has_the_topic_lookup_the_bot_gateway_uses():
    request = fn_messages.GetForumTopicsByIDRequest(
        peer=types.InputPeerChannel(channel_id=1, access_hash=1), topics=[5]
    )
    assert bytes(request)


# --- пул из двух клиентов ------------------------------------------------------------------------------

CHAT_FILM, CHAT_NEW = -1001234567890, -1009990000007


def add_project(db, slug: str, chat_id: int, collector: str) -> None:
    db.add(
        models.Project(
            **{
                **projects.DEFAULT_PROJECT,
                "slug": slug,
                "title": slug,
                "tg_chat_id": chat_id,
                "approved_at": datetime.now(UTC),
                "collector": collector,
            }
        )
    )
    db.commit()


@pytest.fixture
def no_real_indexing(monkeypatch):
    async def no_start(self) -> None:
        return None

    monkeypatch.setattr(Indexer, "start", no_start)
    yield
    runtime.reset()


async def test_each_chat_is_collected_by_the_client_its_project_names(db, no_real_indexing):
    film = db.scalar(select(models.Project))
    film.tg_chat_id = CHAT_FILM
    add_project(db, "clip", CHAT_NEW, Collector.BOT.value)
    userbot, bot = object(), object()
    pool = pool_module.IndexerPool(userbot, database.session_factory(), get_settings(), bot=bot)
    try:
        await pool.start([CHAT_FILM, CHAT_NEW])
        old, new = runtime.gateway_for(CHAT_FILM), runtime.gateway_for(CHAT_NEW)
        assert old.client is userbot and old.live_only is False
        assert new.client is bot and new.live_only is True
        # у каждого клиента свой лимит запросов и своя очередь загрузок: фильм не держит бота
        assert old.limiter is not new.limiter and old._download_lock is not new._download_lock
        again = await pool.ensure(CHAT_NEW)
        assert again is runtime.indexer_for(CHAT_NEW)
    finally:
        await pool.stop()


async def test_two_bot_chats_share_the_bots_limits(db, no_real_indexing):
    add_project(db, "a", -1001, Collector.BOT.value)
    add_project(db, "b", -1002, Collector.BOT.value)
    pool = pool_module.IndexerPool(None, database.session_factory(), get_settings(), bot=object())
    try:
        await pool.start([-1001, -1002])
        a, b = runtime.gateway_for(-1001), runtime.gateway_for(-1002)
        assert a.limiter is b.limiter and a._download_lock is b._download_lock
    finally:
        await pool.stop()


async def test_a_chat_without_its_client_is_skipped_and_the_others_still_start(
    db, no_real_indexing
):
    film = db.scalar(select(models.Project))
    film.tg_chat_id = CHAT_FILM
    add_project(db, "clip", CHAT_NEW, Collector.BOT.value)
    pool = pool_module.IndexerPool(object(), database.session_factory(), get_settings())  # бота нет
    try:
        await pool.start([CHAT_NEW, CHAT_FILM])
        assert runtime.gateway_for(CHAT_NEW) is None and runtime.gateway_for(CHAT_FILM) is not None
        with pytest.raises(RuntimeError, match="Бот не подключён"):
            await pool.ensure(CHAT_NEW)
    finally:
        await pool.stop()


async def test_the_collector_can_be_named_explicitly(db, no_real_indexing):
    userbot, bot = object(), object()
    pool = pool_module.IndexerPool(userbot, database.session_factory(), get_settings(), bot=bot)
    try:
        await pool.ensure(-1003, Collector.BOT)  # чата в проектах нет: решает вызывающий
        assert runtime.gateway_for(-1003).client is bot
    finally:
        await pool.stop()


async def test_the_app_starts_the_pool_for_a_bot_alone(db, monkeypatch):
    from app import main as main_module

    started: list[tuple[object, object]] = []

    class Recorder:
        def __init__(self, userbot, _sessions, _settings, *, bot=None) -> None:
            started.append((userbot, bot))

        async def start(self, chats: list[int]) -> None:
            return None

    monkeypatch.setattr(main_module, "IndexerPool", Recorder)
    bot = object()
    app = SimpleNamespace(state=SimpleNamespace(tg=SimpleNamespace(userbot=None, bot=bot)))
    assert await main_module._start_indexers(app, get_settings()) is not None
    assert started == [(None, bot)]
    app.state.tg = SimpleNamespace(userbot=None, bot=None)
    assert await main_module._start_indexers(app, get_settings()) is None  # собирать нечем


# --- кто читает участников ----------------------------------------------------------------------------


class Checker:
    def __init__(self, name: str, members: dict[int, set[int]] | None = None, down: bool = False):
        self.name, self.members, self.down = name, members or {}, down
        self.asked: list[tuple[str, object]] = []

    async def chats_of(self, tg_id, chat_ids):
        self.asked.append(("chats_of", list(chat_ids)))
        if self.down:
            raise MembershipUnavailable(self.name)
        return {c: tg_id in self.members.get(c, set()) for c in chat_ids}

    async def participants(self, chat_id):
        self.asked.append(("participants", chat_id))
        if self.down:
            raise MembershipUnavailable(self.name)
        return set(self.members[chat_id])

    def forget(self, chat_id):
        self.asked.append(("forget", chat_id))

    async def manageable_chats(self, tg_id, exclude):
        self.asked.append(("manageable", tg_id))
        return []

    async def chat_for(self, tg_id, chat_id, *, require_admin=True):
        self.asked.append(("chat_for", chat_id))
        return None


KINDS = {CHAT_FILM: "userbot", CHAT_NEW: "bot"}


def routed(userbot: Checker, bot: Checker) -> RoutedMembership:
    return RoutedMembership(userbot, bot, lambda ids: {c: KINDS[c] for c in ids if c in KINDS})


async def test_each_chat_is_read_by_the_one_who_collects_it():
    userbot = Checker("userbot", {CHAT_FILM: {1, 2}})
    bot = Checker("bot", {CHAT_NEW: {2, 3}})
    members = routed(userbot, bot)
    assert await members.participants(CHAT_FILM) == {1, 2}
    assert await members.participants(CHAT_NEW) == {2, 3}
    assert [a for a in userbot.asked if a[0] == "participants"] == [("participants", CHAT_FILM)]
    assert [a for a in bot.asked if a[0] == "participants"] == [("participants", CHAT_NEW)]
    assert await members.chats_of(2, [CHAT_FILM, CHAT_NEW]) == {CHAT_FILM: True, CHAT_NEW: True}
    assert await members.chats_of(3, [CHAT_FILM, CHAT_NEW]) == {CHAT_FILM: False, CHAT_NEW: True}


async def test_a_chat_of_an_unknown_project_goes_to_the_userbot():
    userbot, bot = Checker("userbot", {-5: {1}}), Checker("bot")
    assert await routed(userbot, bot).participants(-5) == {1}
    assert bot.asked == []


async def test_when_one_reader_is_down_its_chats_are_unknown_but_the_others_are_answered():
    members = routed(Checker("userbot", down=True), Checker("bot", {CHAT_NEW: {3}}))
    assert await members.chats_of(3, [CHAT_FILM, CHAT_NEW]) == {CHAT_FILM: None, CHAT_NEW: True}


async def test_when_every_reader_is_down_the_answer_is_unavailable():
    members = routed(Checker("userbot", down=True), Checker("bot", down=True))
    with pytest.raises(MembershipUnavailable):
        await members.chats_of(3, [CHAT_FILM, CHAT_NEW])
    with pytest.raises(MembershipUnavailable):
        await members.participants(CHAT_NEW)


async def test_forgetting_a_chat_reaches_both_readers_and_search_stays_with_the_userbot():
    userbot, bot = Checker("userbot"), Checker("bot")
    members = routed(userbot, bot)
    members.forget(CHAT_NEW)
    assert ("forget", CHAT_NEW) in userbot.asked and ("forget", CHAT_NEW) in bot.asked
    await members.manageable_chats(7, [])
    await members.chat_for(7, -77)
    assert ("manageable", 7) in userbot.asked and ("chat_for", -77) in userbot.asked
    assert not any(a[0] in ("manageable", "chat_for") for a in bot.asked)


# --- проект и миграция ---------------------------------------------------------------------------------


def test_a_project_is_collected_by_the_userbot_unless_said_otherwise(db):
    film = db.scalar(select(models.Project))
    assert film.collector == "userbot"
    db.add(
        models.Project(
            **{**projects.DEFAULT_PROJECT, "slug": "x", "title": "x", "collector": "bot"}
        )
    )
    db.commit()
    with pytest.raises(Exception, match="collector|CHECK"):
        db.add(
            models.Project(
                **{**projects.DEFAULT_PROJECT, "slug": "y", "title": "y", "collector": "robot"}
            )
        )
        db.commit()
    db.rollback()


def test_migration_0011_keeps_every_project_on_the_userbot_and_every_table_intact(env):
    from tests.test_migrations import _cfg, _populated_0006  # noqa: PLC2701

    path = _populated_0006(env)
    command.upgrade(_cfg(), "0010")
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    before = {
        t: db.execute(f"select count(*) from {t}").fetchone()[0]
        for t in ("project", "project_member", "user", "scene", "shot", "file", "task")
    }
    assert before["project"] >= 1 and before["project_member"] >= 1
    db.close()

    command.upgrade(_cfg(), "head")

    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    assert db.execute("select version_num from alembic_version").fetchone() == ("0011",)
    assert db.execute("select distinct collector from project").fetchall() == [("userbot",)]
    after = {t: db.execute(f"select count(*) from {t}").fetchone()[0] for t in before}
    assert after == before  # пересоздание таблицы project ничего не унесло
    assert db.execute("pragma foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("update project set collector='robot'")
    db.close()


async def test_the_pool_helper_does_not_wait_for_the_event_loop_blindly(db):
    """Выбор клиента читает базу в потоке: цикл событий остаётся свободным."""
    pool = pool_module.IndexerPool(object(), database.session_factory(), get_settings())
    assert await asyncio.to_thread(pool._collector_of, -42) is Collector.USERBOT
