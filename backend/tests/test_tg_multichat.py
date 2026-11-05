"""Два проекта — два чата: у каждого свой шлюз и индексатор; данные, просмотр и загрузки не смешиваются."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app import db as database
from app import models, scope
from app.config import get_settings
from app.constants import Role
from app.services import members, projects
from app.tg import pool as pool_module
from app.tg import runtime
from app.tg.indexer import Indexer
from tests.fake_telegram import CHAT, png_bytes, simple_chat
from tests.test_tg_api import media_ids, tg, wait_job, wait_ready  # noqa: F401

CHAT_B = -1009990000001
B = "second-film"
PNG_B = png_bytes((200, 10, 10))  # у второго чата свои файлы: по ним видно, откуда пришёл ответ


@pytest.fixture
async def two(tg):  # noqa: F811
    """Проект фильма с чатом A (как в `tg`) и второй проект с чатом B; в обоих чатах одинаковые
    номера сообщений и тем, как это бывает в разных чатах Telegram."""
    client, gateway_a = tg
    with database.session_factory()() as db:
        second = models.Project(
            **{
                **projects.DEFAULT_PROJECT,
                "slug": B,
                "title": "Второй",
                "tg_chat_id": CHAT_B,
                "approved_at": datetime.now(UTC),
            }
        )
        db.add(second)
        db.flush()
        owner = db.scalar(select(models.User).where(models.User.name == "Артём"))
        members.ensure(db, second, owner, role=Role.OWNER)
        db.commit()
        second_id = second.id
    with scope.project_session(second_id) as db:
        scene = models.Scene(number=1, order=1, title="Сцена B", planned_sec=10)
        db.add(scene)
        db.flush()
        db.add(models.Shot(scene_id=scene.id, code="01.01", order=1, description="шот B"))
        db.commit()
    gateway_b = simple_chat(per_topic=4, chat_id=CHAT_B)  # те же id сообщений, что в чате A
    indexer_b = Indexer(gateway_b, database.session_factory(), get_settings())
    runtime.register(gateway_b, indexer_b)
    await indexer_b.run_once()
    for rows in gateway_b.messages.values():
        for message_id, _info in rows:
            gateway_b.files[message_id] = PNG_B
    return client, gateway_a, gateway_b, second_id


def b(path: str) -> str:
    return f"/api/p/{B}{path}"


def shot_b(client) -> int:
    return next(s["id"] for s in client.get(b("/shots")).json() if s["code"] == "01.01")


async def test_each_project_reads_its_own_chat(two):
    client, _, _, _ = two
    status_a = client.get("/api/tg/status").json()
    status_b = client.get(b("/tg/status")).json()
    assert (status_a["chat_id"], status_b["chat_id"]) == (CHAT, CHAT_B)
    assert status_a["connected"] and status_b["connected"]
    assert (status_a["overview"]["media"], status_b["overview"]["media"]) == (48, 8)
    assert len(media_ids(client)["items"]) == 24
    listed_b = client.get(b("/tg/media"), params={"topic_id": 5}).json()["items"]
    assert len(listed_b) == 4
    assert {i["id"] for i in listed_b}.isdisjoint({i["id"] for i in media_ids(client)["items"]})


async def test_a_project_whose_chat_has_no_gateway_is_not_connected(two):
    client, _, _, _ = two
    runtime.gateways.pop(CHAT_B)
    runtime.indexers.pop(CHAT_B)
    assert client.get(b("/tg/status")).json()["connected"] is False
    assert client.get("/api/tg/status").json()["connected"] is True  # другой проект не задет
    assert client.post(b("/tg/sync")).status_code == 503


async def test_sync_wakes_only_the_indexer_of_that_project(two):
    client, _, _, _ = two
    for chat in (CHAT, CHAT_B):
        runtime.indexer_for(chat)._wake.clear()
    assert client.post(b("/tg/sync")).status_code == 202
    assert runtime.indexer_for(CHAT_B)._wake.is_set()
    assert not runtime.indexer_for(CHAT)._wake.is_set()


async def test_import_goes_through_the_gateway_of_the_projects_chat(two):
    client, gateway_a, gateway_b, second_id = two
    item = client.get(b("/tg/media"), params={"topic_id": 5}).json()["items"][0]
    started = client.post(
        b("/tg/import"),
        json={
            "media_ids": [item["id"]],
            "entity_type": "shot",
            "entity_id": shot_b(client),
            "purpose": "reference",
        },
    )
    assert started.status_code == 202, started.text
    for _ in range(300):
        job = next(
            (j for j in client.get(b("/tg/jobs")).json() if j["id"] == started.json()["job_id"]),
            None,
        )
        if job and job["status"] in ("done", "failed"):
            break
        await asyncio.sleep(0.1)
    assert job["status"] == "done", job
    assert gateway_b.download_calls == [item["message_id"]] and gateway_a.download_calls == []
    with database.session_factory()() as db:
        (file,) = db.query(models.File).all()
        assert (file.project_id, file.tg_chat_id) == (second_id, CHAT_B)


async def test_the_same_message_number_in_two_chats_never_shares_a_cached_view(two):
    client, _, gateway_b, _ = two
    images_a = {i["message_id"]: i for i in media_ids(client, kinds="image")["items"]}
    images_b = client.get(b("/tg/media"), params={"topic_id": 5, "kinds": "image"}).json()["items"]
    # то же сообщение с тем же номером и в той же теме есть в обоих чатах (оба — картинки)
    item_b = next(i for i in images_b if i["message_id"] in images_a)
    item_a = images_a[item_b["message_id"]]
    assert item_a["id"] != item_b["id"] and item_a["topic_id"] == item_b["topic_id"]

    ready_a = await wait_ready(client, item_a["id"])
    assert client.get(ready_a["url"]).content == png_bytes()

    first_b = client.post(b(f"/tg/media/{item_b['id']}/view")).json()
    assert first_b["ready"] is False, "файл из кэша чата A не должен считаться файлом чата B"
    for _ in range(300):
        again = client.post(b(f"/tg/media/{item_b['id']}/view")).json()
        if again["ready"]:
            break
        await asyncio.sleep(0.1)
    assert again["ready"] and client.get(again["url"]).content == PNG_B
    assert gateway_b.download_calls == [item_b["message_id"]]


async def test_media_of_another_chat_is_not_reachable_through_this_project(two):
    client, _, _, _ = two
    foreign = media_ids(client)["items"][0]  # из чата A
    assert client.post(b(f"/tg/media/{foreign['id']}/view")).status_code == 404
    token_url = foreign["thumb_url"]
    assert token_url
    wrong_project = token_url.replace("/api/p/brass-spyglass/", f"/api/p/{B}/")
    assert client.get(wrong_project).status_code in (403, 404)


async def test_the_pool_starts_one_indexer_per_chat_and_shares_limits(env, monkeypatch):
    async def no_start(self) -> None:  # настоящий индексатор пошёл бы в Telegram
        return None

    monkeypatch.setattr(Indexer, "start", no_start)
    database.init_engine()
    pool = pool_module.IndexerPool(object(), database.session_factory(), get_settings())
    try:
        await pool.start([CHAT, CHAT_B])
        again = await pool.ensure(CHAT)  # повторный запуск того же чата ничего не создаёт
        gateway_a, gateway_b = runtime.gateway_for(CHAT), runtime.gateway_for(CHAT_B)
        assert again is runtime.indexer_for(CHAT) and gateway_a is not gateway_b
        assert gateway_a.limiter is gateway_b.limiter  # лимит запросов один на аккаунт
        assert gateway_a._download_lock is gateway_b._download_lock  # файлы качаются по одному
        assert runtime.gateway_for(None) is None and runtime.gateway_for(-1) is None
    finally:
        await pool.stop()
        runtime.reset()
