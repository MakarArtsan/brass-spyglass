"""Медиатека и ссылки: фильтры, пагинация, привязка без повторной загрузки, карточки ссылок."""

from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from PIL import Image

from app import db as database
from app import linkpreview, models, worker
from tests.conftest import login
from tests.test_files import upload


def png(color: tuple[int, int, int] = (200, 150, 40)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (64, 48), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def api(seeded_client):
    login(seeded_client, "owner", "Артём")
    return seeded_client


def first_shot(client, code="01.01"):
    return next(s for s in client.get("/api/shots").json() if s["code"] == code)


def library(client, **params):
    response = client.get("/api/library", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# --- ссылки --------------------------------------------------------------------------------------


def test_link_is_created_with_the_author_from_the_session(api):
    me = api.get("/api/me").json()["user"]
    response = api.post("/api/links", json={"url": "https://example.com/film?id=7"})
    assert response.status_code == 201
    body = response.json()
    file = body["file"]
    assert body["created"] is True
    assert (file["kind"], file["source"], file["url"]) == (
        "link",
        "link",
        "https://example.com/film?id=7",
    )
    assert file["uploaded_by"]["id"] == me["id"]
    assert file["processing"] is True  # заголовок и картинка ещё подтягиваются


def test_the_same_link_is_reused_and_attached_to_one_more_card(api):
    shot_a, shot_b = first_shot(api, "01.01"), first_shot(api, "01.02")
    url = "https://example.com/ref"
    first = api.post(
        "/api/links", json={"url": url, "entity_type": "shot", "entity_id": shot_a["id"]}
    ).json()
    second = api.post(
        "/api/links", json={"url": url, "entity_type": "shot", "entity_id": shot_b["id"]}
    ).json()
    assert second["created"] is False and second["file"]["id"] == first["file"]["id"]
    assert library(api, kind="link")["total"] == 1
    assert library(api)["items"][0]["attachments_count"] == 2


def test_the_same_link_cannot_be_attached_to_one_card_twice(api):
    shot = first_shot(api)
    body = {"url": "https://example.com/x", "entity_type": "shot", "entity_id": shot["id"]}
    assert api.post("/api/links", json=body).status_code == 201
    assert api.post("/api/links", json=body).status_code == 409


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/api/me",
        "http://localhost/",
        "http://169.254.169.254/",
        "file:///etc/passwd",
        "ftp://x.org/f",
        "not a url",
    ],
)
def test_internal_and_malformed_links_are_refused_with_a_readable_reason(api, url):
    response = api.post("/api/links", json={"url": url})
    assert response.status_code == 422
    assert library(api)["total"] == 0


def test_link_needs_both_card_type_and_id_and_an_existing_card(api):
    assert (
        api.post("/api/links", json={"url": "https://e.org/", "entity_type": "shot"}).status_code
        == 422
    )
    missing = {"url": "https://e.org/", "entity_type": "shot", "entity_id": 999999}
    assert api.post("/api/links", json=missing).status_code == 404


def test_guest_cannot_add_a_link_but_sees_the_library(seeded_client):
    login(seeded_client, "owner", "Артём")
    seeded_client.post("/api/links", json={"url": "https://example.com/a"})
    login(seeded_client, "guest", "Гость")
    assert (
        seeded_client.post("/api/links", json={"url": "https://example.com/b"}).status_code == 403
    )
    assert library(seeded_client)["total"] == 1


def test_link_preview_job_fills_the_title_and_the_thumbnail(api, monkeypatch):
    monkeypatch.setattr(
        linkpreview, "fetch_card", lambda url: linkpreview.LinkCard("Кривое зеркало", png())
    )
    file = api.post("/api/links", json={"url": "https://example.com/film"}).json()["file"]
    assert worker.drain() >= 1
    done = api.get(f"/api/files/{file['id']}").json()
    assert done["link_title"] == "Кривое зеркало"
    assert done["processing"] is False and done["error"] is None
    assert "thumb" in done["urls"]


def test_a_failed_link_preview_is_visible_not_silent(api, monkeypatch):
    def boom(url):
        raise linkpreview.FetchError("Сайт ответил кодом 404")

    monkeypatch.setattr(linkpreview, "fetch_card", boom)
    file = api.post("/api/links", json={"url": "https://example.com/gone"}).json()["file"]
    worker.drain()
    done = api.get(f"/api/files/{file['id']}").json()
    assert "404" in done["error"] and done["processing"] is False


# --- медиатека -----------------------------------------------------------------------------------


@pytest.fixture
def filled(seeded_client):
    """Четыре файла от разных людей: загрузка (привязана), загрузка (без привязки), ссылка, Telegram."""
    owner = login(seeded_client, "owner", "Артём")
    shot = first_shot(seeded_client)
    attached = upload(
        seeded_client,
        png((10, 20, 30)),
        "owner-attached.png",
        entity_type="shot",
        entity_id=shot["id"],
    )
    assert attached.status_code == 201
    director = login(seeded_client, "director", "Дина")
    free = upload(seeded_client, png((30, 20, 10)), "director-free.png")
    assert free.status_code == 201
    team = login(seeded_client, "team", "Петя")
    link = seeded_client.post("/api/links", json={"url": "https://example.com/ref"})
    assert link.status_code == 201
    with database.session_factory()() as db:
        project_id = db.query(models.Project).one().id
        db.add(models.TgTopic(chat_id=-1001234567890, topic_id=5, title="Персонажи"))
        db.add(
            models.File(
                project_id=project_id,
                kind="image",
                source="telegram",
                original_name="from-chat.jpg",
                tg_chat_id=-1001234567890,
                tg_topic_id=5,
                tg_message_id=77,
                tg_author="Лена",
                uploaded_by=owner.id,
                uploaded_at=datetime.now(UTC),
            )
        )
        db.commit()
    login(seeded_client, "owner", "Артём")
    return {
        "client": seeded_client,
        "owner": owner.id,
        "director": director.id,
        "team": team.id,
        "shot": shot,
    }


def names(page):
    return {i["original_name"] or i["url"] for i in page["items"]}


def test_library_lists_everything_newest_first_with_a_total(filled):
    page = library(filled["client"])
    assert page["total"] == 4 and len(page["items"]) == 4
    ids = [i["id"] for i in page["items"]]
    assert ids == sorted(ids, reverse=True)


def test_filter_by_kind_and_source(filled):
    api = filled["client"]
    assert names(library(api, kind="link")) == {"https://example.com/ref"}
    assert names(library(api, kind="image")) == {
        "owner-attached.png",
        "director-free.png",
        "from-chat.jpg",
    }
    assert names(library(api, source="telegram")) == {"from-chat.jpg"}
    assert names(library(api, source="upload")) == {"owner-attached.png", "director-free.png"}
    assert names(library(api, source="link")) == {"https://example.com/ref"}
    assert library(api, kind="audio")["total"] == 0


def test_filter_by_author(filled):
    api = filled["client"]
    assert names(library(api, author=filled["director"])) == {"director-free.png"}
    assert names(library(api, author=filled["team"])) == {"https://example.com/ref"}
    assert library(api, author=999999)["total"] == 0


def test_unattached_filter_finds_files_without_a_card(filled):
    api = filled["client"]
    assert names(library(api, unattached=True)) == {
        "director-free.png",
        "https://example.com/ref",
        "from-chat.jpg",
    }


def test_search_by_name_link_and_telegram_author_treats_wildcards_literally(filled):
    api = filled["client"]
    assert names(library(api, q="director")) == {"director-free.png"}
    assert names(library(api, q="EXAMPLE.com")) == {"https://example.com/ref"}
    assert names(library(api, q="Лена")) == {"from-chat.jpg"}
    assert library(api, q="%")["total"] == 0  # % — обычный символ, а не «любая строка»
    assert library(api, q="_")["total"] == 0


def test_filter_by_date_uses_moscow_days(filled):
    api = filled["client"]
    today = datetime.now(UTC).astimezone(timezone_msk()).date()
    assert library(api, since=today.isoformat(), until=today.isoformat())["total"] == 4
    yesterday = (today - timedelta(days=1)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    assert library(api, until=yesterday)["total"] == 0
    assert library(api, since=tomorrow)["total"] == 0


def timezone_msk():
    from app.metrics import TEAM_TZ

    return TEAM_TZ


def test_pagination_walks_the_whole_list_without_repeats(filled):
    api = filled["client"]
    seen: list[int] = []
    cursor = None
    pages = 0
    while True:
        page = library(api, limit=2, **({"before_id": cursor} if cursor else {}))
        seen += [i["id"] for i in page["items"]]
        pages += 1
        assert page["total"] == 4
        cursor = page["next_before_id"]
        if cursor is None:
            break
    assert pages == 2 and len(seen) == len(set(seen)) == 4


def test_items_say_where_the_file_is_used(filled):
    api = filled["client"]
    item = next(i for i in library(api)["items"] if i["original_name"] == "owner-attached.png")
    assert item["attachments_count"] == 1
    assert item["attachments"][0]["label"] == f"шот {filled['shot']['code']}"
    free = next(i for i in library(api)["items"] if i["original_name"] == "director-free.png")
    assert free["attachments_count"] == 0 and free["attachments"] == []


def test_telegram_file_carries_topic_author_and_the_open_in_telegram_link(filled):
    item = next(i for i in library(filled["client"], source="telegram")["items"])
    assert item["tg"] == {
        "topic_id": 5,
        "topic_title": "Персонажи",
        "message_id": 77,
        "author": "Лена",
        "url": "https://t.me/c/1234567890/5/77",
    }
    plain = next(i for i in library(filled["client"], source="upload")["items"])
    assert plain["tg"] is None


def test_bad_filter_values_are_422_not_500(filled):
    api = filled["client"]
    for params in (
        {"kind": "nonsense"},
        {"source": "x"},
        {"since": "вчера"},
        {"limit": 0},
        {"limit": 1000},
    ):
        assert api.get("/api/library", params=params).status_code == 422


def test_library_requires_login(client):
    assert client.get("/api/library").status_code == 401


def test_a_library_file_attaches_to_a_card_without_reupload(filled):
    api = filled["client"]
    free = next(i for i in library(api)["items"] if i["original_name"] == "director-free.png")
    shot = first_shot(api, "01.02")
    response = api.post(
        "/api/attachments",
        json={
            "file_id": free["id"],
            "entity_type": "shot",
            "entity_id": shot["id"],
            "purpose": "reference",
        },
    )
    assert response.status_code == 201, response.text
    assert (
        library(api, unattached=True)["total"] == 2
    )  # файл больше не «без привязки», заново не грузился
    assert library(api)["total"] == 4
