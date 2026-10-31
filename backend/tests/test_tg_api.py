"""Окно «Добавить из Telegram» end-to-end на подставном шлюзе: темы, медиа, импорт, просмотр, права."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db as database
from app import models
from app.config import get_settings
from app.tg import previews, runtime
from app.tg.indexer import Indexer
from tests.conftest import SEED_PATH, login
from tests.fake_telegram import CHAT, media, png_bytes, simple_chat


@pytest.fixture
async def tg(env, monkeypatch):
    """Приложение с данными Excel и чатом, который уже проиндексирован подставным Telegram."""
    from app.main import create_app

    monkeypatch.setenv("SEED_XLSX", str(SEED_PATH))
    monkeypatch.setenv("TG_CHAT_ID", str(CHAT))
    get_settings.cache_clear()
    gateway = simple_chat(per_topic=24)
    gateway.messages[5][3] = (
        gateway.messages[5][3][0],
        media(gateway.messages[5][3][0], 5, "link", url="https://example.com/ref", mime=None),
    )
    with TestClient(create_app()) as client:
        runtime.gateway, runtime.loop = gateway, asyncio.get_running_loop()
        indexer = Indexer(gateway, database.session_factory(), get_settings())
        await indexer.run_once()
        for rows in gateway.messages.values():
            for message_id, info in rows:
                if info and info.kind != "link":
                    gateway.files[message_id] = png_bytes()
        runtime.indexer = indexer
        login(client, "owner", "Артём")
        yield client, gateway
    runtime.reset()


def shot(client, code="01.01"):
    return next(s for s in client.get("/api/shots").json() if s["code"] == code)


def media_ids(client, topic_id=5, **params):
    page = client.get("/api/tg/media", params={"topic_id": topic_id, "limit": 200, **params})
    assert page.status_code == 200, page.text
    return page.json()


async def wait_job(client, job_id, limit_sec=30):
    deadline = asyncio.get_running_loop().time() + limit_sec
    while asyncio.get_running_loop().time() < deadline:
        job = next((j for j in client.get("/api/tg/jobs").json() if j["id"] == job_id), None)
        if job and job["status"] in ("done", "failed"):
            return job
        await asyncio.sleep(0.1)
    raise AssertionError(f"импорт {job_id} не закончился за {limit_sec} с")


async def wait_ready(client, media_id, limit_sec=30):
    """Просмотр — это задача, которой нет в списке «моих импортов»: ждём по самому эндпоинту."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit_sec
    while loop.time() < deadline:
        state = client.post(f"/api/tg/media/{media_id}/view").json()
        if state["ready"]:
            return state
        await asyncio.sleep(0.1)
    raise AssertionError("файл не стал доступен для просмотра")


def import_into(client, ids, entity_type="shot", entity_id=None, purpose="reference"):
    entity_id = entity_id or shot(client)["id"]
    response = client.post(
        "/api/tg/import",
        json={
            "media_ids": ids,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "purpose": purpose,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


# --- доступ ---------------------------------------------------------------------------------------------


async def test_everything_needs_login_and_is_closed_to_guests(tg):
    client, _ = tg
    paths = ["/api/tg/status", "/api/tg/topics", "/api/tg/media", "/api/tg/jobs"]
    client.cookies.clear()
    assert all(client.get(p).status_code == 401 for p in paths)
    login(client, "guest", "Гость")
    assert all(client.get(p).status_code == 403 for p in paths)
    assert (
        client.post(
            "/api/tg/import", json={"media_ids": [1], "entity_type": "shot", "entity_id": 1}
        ).status_code
        == 403
    )
    login(client, "team", "Петя")
    assert all(client.get(p).status_code == 200 for p in paths)


# --- темы и медиа --------------------------------------------------------------------------------------


async def test_topics_list_counts_and_the_latest_preview(tg):
    client, _ = tg
    topics = {t["title"]: t for t in client.get("/api/tg/topics").json()}
    assert topics["Персонажи"]["media_count"] == 24 and topics["Локации"]["media_count"] == 24
    assert topics["Общая"]["media_count"] == 0
    thumb = client.get(topics["Персонажи"]["latest_thumb_url"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    assert all(t["history_complete"] for t in topics.values())


async def test_thumbnail_links_are_signed(tg):
    client, _ = tg
    item = media_ids(client)["items"][0]
    assert client.get(item["thumb_url"]).status_code == 200
    base = item["thumb_url"].split("?")[0]
    assert client.get(base).status_code == 403
    assert client.get(base + "?t=forged").status_code == 403


async def test_media_is_newest_first_with_authors_and_a_link_to_the_message(tg):
    client, _ = tg
    page = media_ids(client)
    ids = [i["message_id"] for i in page["items"]]
    assert ids == sorted(ids, reverse=True) and len(ids) == 24
    first = page["items"][0]
    assert (first["author_name"], first["topic_id"]) == ("Лена", 5)
    assert first["open_url"] == f"https://t.me/c/1234567890/5/{first['message_id']}"


async def test_media_filters_by_kind_search_and_hide_imported(tg):
    client, gateway = tg
    assert {i["kind"] for i in media_ids(client, kinds="link")["items"]} == {"link"}
    assert len(media_ids(client, kinds="link")["items"]) == 1
    assert len(media_ids(client, kinds="image,link")["items"]) == 24
    assert media_ids(client, kinds="video")["items"] == []
    assert client.get("/api/tg/media", params={"kinds": "nonsense"}).status_code == 422

    target = media_ids(client)["items"][-1]
    with database.session_factory()() as db:
        row = db.get(models.TgMedia, target["id"])
        row.caption = "Дозорный Севера у стены"
        db.commit()
    assert [i["id"] for i in media_ids(client, q="дозорный")["items"]] == [target["id"]]
    assert media_ids(client, q="%")["items"] == []  # % — обычный символ

    import_into(client, [target["id"]])
    done = await wait_job(client, client.get("/api/tg/jobs").json()[0]["id"])
    assert done["status"] == "done"
    assert target["id"] not in [i["id"] for i in media_ids(client, hide_imported=True)["items"]]
    assert len(media_ids(client, hide_imported=True)["items"]) == 23


async def test_media_pagination_walks_the_topic_without_repeats(tg):
    client, _ = tg
    seen, cursor = [], None
    for _ in range(5):
        page = client.get(
            "/api/tg/media",
            params={"topic_id": 5, "limit": 10, **({"before_id": cursor} if cursor else {})},
        ).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_before_id"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 24


# --- импорт ------------------------------------------------------------------------------------------------


async def test_twenty_files_from_a_topic_are_imported_in_one_action(tg):
    """Критерий приёмки ТЗ: 20 файлов из темы Telegram импортируются одним действием."""
    client, gateway = tg
    card = shot(client)
    chosen = [i["id"] for i in media_ids(client, kinds="image")["items"]][:20]
    assert len(chosen) == 20
    started = import_into(client, chosen, entity_id=card["id"], purpose="reference")
    assert started["count"] == 20
    job = await wait_job(client, started["job_id"])
    assert (job["status"], job["error"]) == ("done", None) and job["progress"] == 1

    attached = client.get(f"/api/files?entity_type=shot&entity_id={card['id']}").json()
    assert len(attached) == 20 and {a["purpose"] for a in attached} == {"reference"}
    me = client.get("/api/me").json()["user"]
    file = attached[0]["file"]
    assert (file["source"], file["kind"], file["uploaded_by"]["id"]) == (
        "telegram",
        "image",
        me["id"],
    )
    assert file["tg"]["topic_title"] == "Персонажи" and file["tg"]["author"] == "Лена"
    assert file["tg"]["url"].startswith("https://t.me/c/1234567890/5/")
    assert len(gateway.download_calls) == 20
    with database.session_factory()() as db:
        imported = (
            db.query(models.TgMedia).filter(models.TgMedia.imported_file_id.is_not(None)).count()
        )
        assert imported == 20


async def test_the_same_message_is_attached_to_another_card_without_a_duplicate(tg):
    client, gateway = tg
    one = media_ids(client)["items"][-1]["id"]
    a, b = shot(client, "01.01"), shot(client, "01.02")
    await wait_job(client, import_into(client, [one], entity_id=a["id"])["job_id"])
    await wait_job(client, import_into(client, [one], entity_id=b["id"], purpose="take")["job_id"])
    assert len(gateway.download_calls) == 1  # второй раз файл не скачивался
    fa = client.get(f"/api/files?entity_type=shot&entity_id={a['id']}").json()
    fb = client.get(f"/api/files?entity_type=shot&entity_id={b['id']}").json()
    assert fa[0]["file"]["id"] == fb[0]["file"]["id"] and fb[0]["purpose"] == "take"
    library = client.get("/api/library", params={"source": "telegram"}).json()
    assert library["total"] == 1 and library["items"][0]["attachments_count"] == 2


async def test_importing_to_the_same_card_twice_is_harmless(tg):
    client, _ = tg
    one = media_ids(client)["items"][-1]["id"]
    card = shot(client)
    await wait_job(client, import_into(client, [one], entity_id=card["id"])["job_id"])
    again = await wait_job(client, import_into(client, [one], entity_id=card["id"])["job_id"])
    assert again["status"] == "done"
    assert len(client.get(f"/api/files?entity_type=shot&entity_id={card['id']}").json()) == 1


async def test_a_link_from_the_chat_becomes_a_link_card(tg):
    client, gateway = tg
    link = media_ids(client, kinds="link")["items"][0]
    card = shot(client)
    job = await wait_job(client, import_into(client, [link["id"]], entity_id=card["id"])["job_id"])
    assert job["status"] == "done" and gateway.download_calls == []
    file = client.get(f"/api/files?entity_type=shot&entity_id={card['id']}").json()[0]["file"]
    assert (file["kind"], file["source"], file["url"]) == (
        "link",
        "telegram",
        "https://example.com/ref",
    )
    assert file["tg"]["message_id"] == link["message_id"]


async def test_one_broken_message_does_not_cancel_the_rest(tg):
    client, gateway = tg
    ids = [i["id"] for i in media_ids(client, kinds="image")["items"]][:3]
    with database.session_factory()() as db:
        gone = db.get(models.TgMedia, ids[1]).message_id
    gateway.deleted.add(gone)
    card = shot(client)
    job = await wait_job(client, import_into(client, ids, entity_id=card["id"])["job_id"])
    assert job["status"] == "failed"
    assert job["error"].startswith("Загружено 2 из 3") and "удалено" in job["error"]
    assert len(client.get(f"/api/files?entity_type=shot&entity_id={card['id']}").json()) == 2


async def test_import_refuses_when_the_disk_limit_would_be_exceeded(tg):
    client, gateway = tg
    with database.session_factory()() as db:
        db.query(
            models.Project
        ).one().storage_limit_gb = 0.000001  # ~1 КБ: меньше любой базы данных
        db.commit()
    one = media_ids(client)["items"][0]["id"]
    job = await wait_job(client, import_into(client, [one])["job_id"])
    assert job["status"] == "failed" and "не хватает места" in job["error"]
    assert gateway.download_calls == []


async def test_import_without_a_connected_userbot_says_so(tg):
    client, _ = tg
    runtime.gateway = None
    one = media_ids(client)["items"][0]["id"]
    job = await wait_job(client, import_into(client, [one])["job_id"])
    assert job["status"] == "failed" and "не подключён" in job["error"]


async def test_import_request_is_validated(tg):
    client, _ = tg
    card = shot(client)["id"]
    ok = media_ids(client)["items"][0]["id"]

    def post(**body):
        payload = {"entity_type": "shot", "entity_id": card, "media_ids": [ok], **body}
        return client.post("/api/tg/import", json=payload)

    assert post(media_ids=[]).status_code == 422
    assert post(media_ids=list(range(1, 202))).status_code == 422
    assert post(media_ids=[999999]).status_code == 404
    assert post(entity_id=999999).status_code == 404
    assert post(purpose="nonsense").status_code == 422
    assert (
        post(entity_type="user", entity_id=1).status_code == 422
    )  # к участнику файлы не привязываются


async def test_the_author_of_an_import_is_the_session_user_not_the_chat_author(tg):
    client, _ = tg
    login(client, "team", "Петя")
    one = media_ids(client)["items"][0]["id"]
    card = shot(client)
    await wait_job(client, import_into(client, [one], entity_id=card["id"])["job_id"])
    file = client.get(f"/api/files?entity_type=shot&entity_id={card['id']}").json()[0]["file"]
    assert file["uploaded_by"]["name"] == "Петя" and file["tg"]["author"] == "Лена"


# --- просмотр в окне ------------------------------------------------------------------------------------------------


async def test_a_file_can_be_watched_in_the_window_before_it_is_imported(tg):
    client, gateway = tg
    item = media_ids(client)["items"][0]
    first = client.post(f"/api/tg/media/{item['id']}/view").json()
    assert first["ready"] is False and first["job_id"]
    ready = await wait_ready(client, item["id"])
    shown = client.get(ready["url"])
    assert shown.status_code == 200 and shown.content == png_bytes()
    assert client.get(ready["url"].split("?")[0]).status_code == 403
    assert len(gateway.download_calls) == 1
    with database.session_factory()() as db:
        assert db.query(models.File).count() == 0  # просмотр ничего не добавил в проект


async def test_watching_the_same_file_twice_does_not_queue_two_downloads(tg):
    client, _ = tg
    item = media_ids(client)["items"][0]
    a = client.post(f"/api/tg/media/{item['id']}/view").json()
    b = client.post(f"/api/tg/media/{item['id']}/view").json()
    assert a["job_id"] == b["job_id"] or b["ready"]


async def test_a_link_has_nothing_to_play(tg):
    client, _ = tg
    link = media_ids(client, kinds="link")["items"][0]
    assert client.post(f"/api/tg/media/{link['id']}/view").status_code == 422


async def test_the_preview_cache_drops_the_oldest_files_over_the_limit(tg, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "tg_preview_cache_mb", 1)
    folder = settings.tg_view_dir
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).timestamp()
    import os

    for n, age in enumerate((300, 200, 100)):
        path = folder / f"{n}-5.jpg"
        path.write_bytes(b"x" * 400_000)
        os.utime(path, (now - age, now - age))
    newest = folder / "2-5.jpg"
    assert previews.evict(settings, keep=newest) == 1
    assert sorted(p.name for p in folder.iterdir()) == ["1-5.jpg", "2-5.jpg"]


# --- статус и синхронизация ----------------------------------------------------------------------------------------


async def test_status_reports_the_index_and_the_connection(tg):
    client, _ = tg
    status = client.get("/api/tg/status").json()
    assert (
        status["connected"] is True and status["syncing"] is False and status["last_error"] is None
    )
    assert status["overview"]["topics"] == 3 and status["overview"]["media"] == 48
    assert status["overview"]["topics_complete"] == 3 and status["overview"]["last_synced_at"]


async def test_only_the_owner_can_start_a_sync(tg):
    client, _ = tg
    indexer = runtime.indexer
    indexer._wake.clear()
    assert client.post("/api/tg/sync").status_code == 202 and indexer._wake.is_set()
    login(client, "director", "Дина")
    assert client.post("/api/tg/sync").status_code == 403
    login(client, "owner", "Артём")
    runtime.indexer = None
    assert client.post("/api/tg/sync").status_code == 503


async def test_jobs_list_shows_only_my_recent_imports(tg):
    client, _ = tg
    one = media_ids(client)["items"][0]["id"]
    mine = import_into(client, [one])["job_id"]
    await wait_job(client, mine)
    owner_cookie = client.cookies.get(
        "bs_session"
    )  # login() заводит нового участника, а нужен тот же
    login(client, "team", "Петя")
    assert client.get("/api/tg/jobs").json() == []  # чужие импорты в моём углу экрана не нужны
    client.cookies.set("bs_session", owner_cookie)
    assert [j["id"] for j in client.get("/api/tg/jobs").json()] == [mine]
    with database.session_factory()() as db:
        job = db.get(models.Job, mine)
        job.finished_at = datetime.now(UTC) - timedelta(minutes=10)
        db.commit()
    assert client.get("/api/tg/jobs").json() == []  # давно законченные не показываем


# --- диск при обычной загрузке --------------------------------------------------------------------------------------


async def test_a_regular_upload_is_refused_when_it_does_not_fit_the_disk(tg):
    client, _ = tg
    with database.session_factory()() as db:
        db.query(models.Project).one().storage_limit_gb = 0.000001
        db.commit()
    response = client.post("/api/uploads", json={"name": "big.mp4", "size": 50_000_000})
    assert response.status_code == 507 and "не хватает места" in response.json()["detail"]


@pytest.mark.filterwarnings("ignore:coroutine .* was never awaited:RuntimeWarning")
def test_a_download_does_not_wait_for_a_loop_that_has_stopped(monkeypatch):
    """Поток воркера не должен висеть до конца часового тайм-аута, когда главный цикл остановлен."""
    import asyncio
    import time

    from app.media import MediaError
    from app.tg import importer, runtime

    stopped = asyncio.new_event_loop()  # создан, но не запущен — как цикл после выключения
    monkeypatch.setattr(runtime, "loop", stopped)
    monkeypatch.setattr(importer, "WAIT_SLICE_SEC", 0.05)

    async def never() -> None:
        await asyncio.sleep(3600)

    started = time.monotonic()
    with pytest.raises(MediaError):
        importer._await(never(), timeout=60)
    assert time.monotonic() - started < 5
    stopped.close()
