"""Индексатор Telegram на подставном шлюзе: полный проход, продолжение, догон, превью, FloodWait, живые."""

import asyncio

import pytest
from sqlalchemy import func, select

from app import db as database
from app import events, models
from app.config import get_settings
from app.events import EventBus
from app.services import telegram as svc
from app.tg import indexer as indexer_module
from app.tg.indexer import Indexer
from app.tg.types import GENERAL_TOPIC, TopicInfo
from tests.fake_telegram import CHAT, FakeGateway, media, simple_chat


@pytest.fixture
def make(env):
    sleeps: list[float] = []

    async def sleep(seconds):
        sleeps.append(seconds)

    def build(gateway: FakeGateway) -> Indexer:
        indexer = Indexer(gateway, database.session_factory(), get_settings(), sleep=sleep)
        gateway.on_new(indexer._on_new)
        return indexer

    build.sleeps = sleeps  # type: ignore[attr-defined]
    return build


def rows(db, topic_id=None):
    stmt = select(models.TgMedia).order_by(models.TgMedia.message_id)
    if topic_id is not None:
        stmt = stmt.where(models.TgMedia.topic_id == topic_id)
    return list(db.scalars(stmt))


async def test_first_sync_indexes_topics_and_media_and_marks_history_complete(make, db):
    gateway = simple_chat(per_topic=5)
    await make(gateway).run_once()
    db.expire_all()
    topics = {t.topic_id: t for t in db.scalars(select(models.TgTopic))}
    assert {t.title for t in topics.values()} == {"Общая", "Персонажи", "Локации"}
    assert (
        topics[5].media_count == 5
        and topics[9].media_count == 5
        and topics[GENERAL_TOPIC].media_count == 0
    )
    assert all(t.history_complete and t.last_synced_at for t in topics.values())
    assert topics[5].oldest_message_id == 101
    assert len(rows(db)) == 10


async def test_metadata_is_stored_without_downloading_files(make, db):
    gateway = simple_chat(1)
    gateway.messages[5] = [
        (101, media(101, 5, "video", caption="Дозорный", file_name="d.mp4", duration_sec=7.5))
    ]
    await make(gateway).run_once()
    row = rows(db, 5)[0]
    assert (row.kind, row.caption, row.file_name, row.duration_sec, row.author_name) == (
        "video",
        "Дозорный",
        "d.mp4",
        7.5,
        "Лена",
    )
    assert row.imported_file_id is None and gateway.download_calls == []  # файл не скачивался


async def test_text_messages_are_not_rows_but_the_cursor_moves_past_them(make, db):
    gateway = simple_chat(0)
    gateway.messages[5] = [(300, None), (301, media(301, 5)), (302, None)]
    await make(gateway).run_once()
    assert [r.message_id for r in rows(db, 5)] == [301]
    assert get_topic(db, 5).history_complete


def get_topic(db, topic_id):
    db.expire_all()
    return svc.get_topic(db, CHAT, topic_id)


async def test_interrupted_sync_resumes_from_where_it_stopped(make, db, monkeypatch):
    monkeypatch.setattr(indexer_module, "BATCH", 100)
    gateway = simple_chat(0)
    gateway.messages[5] = [(i, media(i, 5)) for i in range(1, 251)]  # 250 сообщений
    gateway.fail_history_after = 150
    indexer = make(gateway)
    await indexer.run_once()
    assert indexer.state.last_error and "обрыв" in indexer.state.last_error
    saved = len(rows(db, 5))
    assert 100 <= saved < 250, "первая пачка сохранена до обрыва"
    topic = get_topic(db, 5)
    assert not topic.history_complete and topic.oldest_message_id == min(
        r.message_id for r in rows(db, 5)
    )

    gateway.fail_history_after = None
    gateway.history_calls.clear()
    await indexer.run_once()
    resume = [c for c in gateway.history_calls if c["topic"] == 5]
    assert (
        resume[-1]["max_id"] == topic.oldest_message_id and not resume[-1]["reverse"]
    )  # с места остановки
    ids = [r.message_id for r in rows(db, 5)]
    assert ids == list(range(1, 251)) and len(ids) == len(set(ids))
    assert get_topic(db, 5).history_complete and indexer.state.last_error is None


async def test_later_syncs_only_catch_up_with_new_messages(make, db):
    gateway = simple_chat(3)
    indexer = make(gateway)
    await indexer.run_once()
    gateway.messages[5] += [(500, media(500, 5)), (501, None), (502, media(502, 5))]
    gateway.history_calls.clear()
    await indexer.run_once()
    calls = [c for c in gateway.history_calls if c["topic"] == 5]
    assert calls == [
        {"topic": 5, "min_id": 103, "max_id": 0, "reverse": True}
    ]  # только новое, без повторного обхода
    assert [r.message_id for r in rows(db, 5)][-2:] == [500, 502]


async def test_thumbnails_are_cut_to_400px_newest_first_and_missing_ones_not_retried(make, db):
    gateway = simple_chat(3)
    gateway.no_thumb = {102}
    indexer = make(gateway)
    await indexer.run_once()
    db.expire_all()
    by_message = {r.message_id: r for r in rows(db)}
    assert (
        by_message[102].thumb_path == ""
    )  # у файла нет миниатюры — запомнили, чтобы не просить снова
    good = by_message[101]
    path = get_settings().tg_thumbs_dir / good.thumb_path
    assert path.is_file()
    from PIL import Image

    with Image.open(path) as image:
        assert max(image.size) == 400
    gateway.thumb_calls.clear()
    await indexer.make_thumbs()
    assert gateway.thumb_calls == []


async def test_only_images_and_videos_get_thumbnail_requests(make, db):
    gateway = simple_chat(0)
    gateway.messages[5] = [
        (1, media(1, 5, "audio")),
        (2, media(2, 5, "document", mime="application/pdf")),
        (3, media(3, 5, "link", url="https://e.org")),
        (4, media(4, 5, "video")),
    ]
    await make(gateway).run_once()
    assert gateway.thumb_calls == [4]


async def test_flood_wait_is_waited_out_and_the_sync_still_finishes(make, db):
    gateway = simple_chat(2)
    gateway.flood_once = 30
    await make(gateway).run_once()
    assert 31 in make.sleeps
    assert len(rows(db)) == 4


async def test_a_flood_wait_that_never_ends_stops_the_sync_with_a_readable_error(make, db):
    gateway = simple_chat(2)

    async def always(*_a, **_k):
        raise FloodWaitError(5)
        yield  # pragma: no cover

    from tests.fake_telegram import FloodWaitError

    gateway.history = always  # type: ignore[method-assign]
    indexer = make(gateway)
    await indexer.run_once()
    assert indexer.state.last_error and "flood" in indexer.state.last_error
    assert indexer.state.running is False


async def test_a_chat_without_topics_is_a_single_general_topic(make, db):
    gateway = FakeGateway(
        [TopicInfo(GENERAL_TOPIC, "Закрытый чат")],
        {GENERAL_TOPIC: [(1, media(1, GENERAL_TOPIC)), (2, media(2, GENERAL_TOPIC))]},
    )
    await make(gateway).run_once()
    assert [t.title for t in db.scalars(select(models.TgTopic))] == ["Закрытый чат"]
    assert len(rows(db)) == 2


async def test_album_messages_keep_the_group_id(make, db):
    gateway = simple_chat(0)
    gateway.messages[5] = [(i, media(i, 5, grouped_id=777)) for i in (10, 11, 12)] + [
        (13, media(13, 5))
    ]
    await make(gateway).run_once()
    assert [r.grouped_id for r in rows(db, 5)] == [777, 777, 777, None]


async def test_a_resync_updates_an_edited_caption_without_duplicating(make, db):
    gateway = simple_chat(1)
    indexer = make(gateway)
    await indexer.run_once()
    gateway.messages[5] = [(101, media(101, 5, caption="после правки"))]
    gateway.messages[5].append(
        (900, media(900, 5))
    )  # новое сообщение, чтобы догон захватил и 101 не нужен
    await indexer.run_once()
    count = db.scalar(
        select(func.count()).select_from(models.TgMedia).where(models.TgMedia.topic_id == 5)
    )
    assert count == 2


# --- живые сообщения ---------------------------------------------------------------------------------------


@pytest.fixture
async def bus(monkeypatch):
    fresh = EventBus()
    fresh.bind(asyncio.get_running_loop())
    monkeypatch.setattr(events, "bus", fresh)
    return fresh


async def test_a_new_chat_message_is_indexed_at_once_with_a_thumbnail_and_an_sse_event(
    make, db, bus
):
    gateway = simple_chat(1)
    indexer = make(gateway)
    await indexer.run_once()
    with bus.subscribe() as queue:
        await gateway.emit(media(700, 5), 5)
        event = await asyncio.wait_for(queue.get(), 1)
    assert event == {"type": "tg", "topic_id": 5}
    row = next(r for r in rows(db, 5) if r.message_id == 700)
    assert (
        row.thumb_path == f"{CHAT}/{row.id}.jpg"
        and (get_settings().tg_thumbs_dir / row.thumb_path).is_file()
    )
    assert get_topic(db, 5).media_count == 2


async def test_a_text_only_message_changes_nothing(make, db):
    gateway = simple_chat(1)
    await make(gateway).run_once()
    before = len(rows(db))
    await gateway.emit(None, 5, message_id=801)
    assert len(rows(db)) == before


async def test_a_message_in_a_topic_we_do_not_know_yet_asks_for_a_sync(make, db):
    gateway = simple_chat(1)
    indexer = make(gateway)
    await indexer.run_once()
    indexer._wake.clear()
    await gateway.emit(media(900, 77), 77)  # тема 77 ещё не в индексе
    assert indexer._wake.is_set()
    assert all(r.message_id != 900 for r in rows(db))
