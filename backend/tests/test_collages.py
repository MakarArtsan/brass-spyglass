"""Коллажи через API: сборка из загруженных фото, название, скачивание картинки и исходников, права."""

import io
import zipfile
from datetime import UTC, datetime
from urllib.parse import quote

import pytest
from PIL import Image
from sqlalchemy import func, select

from app import collage as engine
from app import db as database
from app import models, scope, storage
from app.constants import Role
from app.permissions import Actor, PermissionDenied
from app.services import collages, projects
from tests.conftest import login
from tests.test_files import upload, wait_for
from tests.test_isolation import act_as, person

RED, GREEN, BLUE = (220, 30, 30), (30, 200, 60), (40, 70, 230)


def jpeg(size=(1200, 800), color=RED) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG", quality=92)
    return buffer.getvalue()


def photo(client, name="a.jpg", size=(1200, 800), color=RED, **complete) -> int:
    done = upload(client, jpeg(size, color), name, no_compress=True, **complete)
    assert done.status_code == 201, done.text
    return done.json()["file"]["id"]


def three(client) -> list[int]:
    return [
        photo(client, "север-1.jpg", (1200, 800), RED),
        photo(client, "север-2.jpg", (700, 1000), GREEN),
        photo(client, "север-3.jpg", (1600, 900), BLUE),
    ]


def make(client, title="Одежда северян", ids=None, **extra):
    return client.post("/api/collages", json={"title": title, "file_ids": ids, **extra})


@pytest.fixture
def api(client):
    login(client, "owner", "Артём")
    return client


# --- сборка и скачивание ------------------------------------------------------------------------------------


def test_a_collage_is_made_from_uploaded_photos_and_can_be_downloaded(api):
    ids = three(api)
    me = api.get("/api/me").json()["user"]
    done = make(api, "Одежда северян", ids)
    assert done.status_code == 201, done.text
    item = done.json()
    assert (item["title"], item["photos"], item["width"]) == ("Одежда северян", 3, 3840)
    assert item["created_by"]["id"] == me["id"] and item["size_bytes"] > 0

    image = api.get(item["download_url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert (
        f"filename*=UTF-8''{quote('Одежда северян.jpg', safe='')}"
        in image.headers["content-disposition"]
    )
    with Image.open(io.BytesIO(image.content)) as out:
        assert out.size == (item["width"], item["height"]) and out.format == "JPEG"
        assert out.getpixel((out.width // 8, out.height // 5))[:3] != (14, 20, 32)  # фото, а не фон


def test_the_photos_of_a_collage_come_back_as_a_zip_in_the_order_of_the_layout(api):
    ids = three(api)
    originals = [api.get(f"/api/files/{i}").json() for i in ids]
    item = make(api, "Здания юга", ids).json()
    archive = api.get(item["zip_url"])
    assert archive.status_code == 200 and archive.headers["content-type"] == "application/zip"
    assert "zip" in archive.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        assert zf.namelist() == [
            f"{n:02d}_{o['original_name']}" for n, o in enumerate(originals, 1)
        ]
        first = Image.open(io.BytesIO(zf.read(zf.namelist()[1])))
        assert first.size == (700, 1000)  # оригинал, а не уменьшенная копия


def test_the_detail_lists_photos_in_order_with_their_previews(api):
    ids = three(api)
    item = make(api, "Порядок", [ids[2], ids[0], ids[1]]).json()
    detail = api.get(f"/api/collages/{item['id']}").json()
    assert [p["id"] for p in detail["photo_list"]] == [ids[2], ids[0], ids[1]]
    assert detail["photo_list"][0]["original_name"] == "север-3.jpg"
    assert all("original" in p["urls"] for p in detail["photo_list"])


def test_the_list_shows_newest_first_and_is_light(api):
    ids = three(api)
    old = make(api, "Первый", ids).json()
    new = make(api, "Второй", ids[:2]).json()
    listed = api.get("/api/collages").json()
    assert [c["id"] for c in listed] == [new["id"], old["id"]]
    assert "photo_list" not in listed[0] and listed[0]["photos"] == 2


def test_the_collage_picture_is_a_project_file_with_a_preview_and_counted_space(api):
    from app.config import get_settings

    ids = three(api)
    with database.session_factory()() as db:
        project = projects.current(_scoped(db))
        before = storage.project_used_bytes(get_settings(), db, project.id, fresh=True)
    item = make(api, "Файл проекта", ids).json()
    with database.session_factory()() as db:
        row = db.get(models.Collage, item["id"])
        image = db.get(models.File, row.file_id)
        assert (image.kind, image.mime, image.original_name) == (
            "image",
            "image/jpeg",
            "Файл проекта.jpg",
        )
        assert image.no_compress is True  # собранный JPEG повторно не сжимается
        used = storage.project_used_bytes(get_settings(), db, row.project_id, fresh=True)
    assert used - before >= item["size_bytes"]
    ready = wait_for(api, image.id, ready=lambda f: not f["processing"] and f["width"])
    assert ready["width"] == 3840
    assert "thumb" in api.get("/api/collages").json()[0]["urls"]


def _scoped(db):
    project = db.scalar(select(models.Project))
    scope.select_project(db, project.id, project.slug)
    return db


def test_the_same_photos_in_the_same_order_reuse_the_same_picture(api):
    ids = three(api)
    one = make(api, "Одно", ids).json()
    two = make(api, "Другое имя", ids).json()
    same_file = one["urls"]["original"].split("?")[0] == two["urls"]["original"].split("?")[0]
    assert one["id"] != two["id"] and same_file  # у ссылок разная подпись, а файл один
    assert api.delete(f"/api/collages/{one['id']}").status_code == 204
    assert api.get(two["download_url"]).status_code == 200  # картинка осталась у второго


# --- название и число фото ----------------------------------------------------------------------------------


def test_the_title_is_required_trimmed_and_limited(api):
    ids = three(api)
    assert make(api, "   ", ids).status_code == 422
    assert "Назовите" in make(api, "   ", ids).json()["detail"]
    long = make(api, "я" * (collages.MAX_TITLE + 1), ids)
    assert long.status_code == 422 and str(collages.MAX_TITLE) in long.json()["detail"]
    neat = make(api, "  Одежда    северян \n", ids).json()
    assert neat["title"] == "Одежда северян"


def test_a_title_with_forbidden_characters_still_gives_a_clean_file_name(api):
    item = make(api, 'Север / «юг»: *?"<>|', three(api)).json()
    disposition = api.get(item["download_url"]).headers["content-disposition"]
    assert not any(ch in disposition.split("''", 1)[1] for ch in '/\\:*?"<>|')
    assert collages.file_name("///") == "collage.jpg"
    assert (
        collages.file_name("а" * 300).endswith(".jpg") and len(collages.file_name("а" * 300)) <= 84
    )


@pytest.mark.parametrize("count", [engine.MIN_PHOTOS, engine.MAX_PHOTOS])
def test_two_and_ten_photos_are_both_fine(api, count):
    ids = [
        photo(api, f"p{i}.jpg", (800 + i * 40, 600), (20 * i, 100, 200 - 10 * i))
        for i in range(count)
    ]
    done = make(api, f"{count} фото", ids)
    assert done.status_code == 201 and done.json()["photos"] == count


def test_one_photo_and_eleven_photos_are_refused_with_a_clear_message(api):
    ids = [photo(api, f"p{i}.jpg", (800, 600), (20 * i, 100, 200)) for i in range(11)]
    assert "от 2 до 10" in make(api, "Мало", ids[:1]).json()["detail"]
    assert (
        "от 2 до 10" in make(api, "Мало", [999_999]).json()["detail"]
    )  # число проверено раньше файлов
    too_many = make(api, "Много", ids)
    assert too_many.status_code == 422 and "от 2 до 10" in too_many.json()["detail"]
    assert api.get("/api/collages").json() == []  # ничего не создано


def test_the_same_photo_twice_is_refused(api):
    a = photo(api, "a.jpg")
    assert "дважды" in make(api, "Двойник", [a, a]).json()["detail"]


# --- что считается фото ----------------------------------------------------------------------------------------


def test_only_images_of_this_project_that_are_alive_can_be_used(api):
    a = photo(api, "a.jpg", color=RED)
    b = photo(api, "b.jpg", color=GREEN)
    note = upload(api, b"just text", "note.txt", no_compress=True).json()["file"]["id"]
    text = make(api, "Текст", [a, note])
    assert (
        text.status_code == 422 and "нет в проекте" in text.json()["detail"]
    )  # не «битая картинка»
    assert make(api, "Нет такого", [a, 999_999]).status_code == 422
    assert api.delete(f"/api/files/{b}").status_code == 204
    gone = make(api, "Удалённое", [a, b])
    assert gone.status_code == 422 and "нет в проекте" in gone.json()["detail"]
    assert api.get("/api/collages").json() == []


def test_a_broken_photo_is_named_and_leaves_nothing_behind(api):
    from app.config import get_settings

    good = photo(api, "good.jpg")
    bad = upload(api, "это не картинка".encode(), "bad.jpg", no_compress=True).json()["file"]["id"]
    with database.session_factory()() as db:
        files_before = db.scalar(select(func.count()).select_from(models.File))
    refused = make(api, "Битое", [good, bad])
    assert refused.status_code == 422 and "bad.jpg" in refused.json()["detail"]
    with database.session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(models.File)) == files_before
        assert db.scalar(select(func.count()).select_from(models.Collage)) == 0
    tmp = get_settings().cache_dir / "tmp"
    assert not tmp.exists() or list(tmp.glob("*.jpg")) == []  # временная картинка убрана


def test_when_the_disk_is_full_nothing_is_made(api, monkeypatch):
    ids = three(api)

    def full(*_args, **_kwargs):
        raise storage.NoRoom("На диске не хватает места")

    monkeypatch.setattr(storage, "ensure_room", full)
    refused = make(api, "Некуда", ids)
    assert refused.status_code == 507 and "не хватает места" in refused.json()["detail"]
    assert api.get("/api/collages").json() == []


# --- права ---------------------------------------------------------------------------------------------------------


def test_a_guest_cannot_make_a_collage_but_can_look_and_download(api):
    item = make(api, "Для всех", three(api)).json()
    login(api, "guest", "Гость")
    assert make(api, "Нельзя", [1, 2]).status_code == 403
    assert [c["id"] for c in api.get("/api/collages").json()] == [item["id"]]
    assert api.get(item["download_url"]).status_code == 200
    assert api.get(item["zip_url"]).status_code == 200


def test_the_team_deletes_only_its_own_collage_and_director_and_owner_delete_any(api):
    ids = three(api)
    login(api, "team", "Петя")
    mine = make(api, "Моё", ids)
    assert mine.status_code == 201
    mine_id = mine.json()["id"]
    login(api, "owner", "Артём")
    theirs = make(api, "Чужое", ids[:2]).json()["id"]
    login(api, "team", "Лена")
    assert api.delete(f"/api/collages/{theirs}").status_code == 403
    assert api.get(f"/api/collages/{theirs}").status_code == 200
    login(api, "director", "Дина")
    assert api.delete(f"/api/collages/{mine_id}").status_code == 204
    login(api, "owner", "Артём")
    assert api.delete(f"/api/collages/{theirs}").status_code == 204


def test_a_deleted_collage_disappears_but_its_photos_stay_in_the_project(api):
    ids = three(api)
    item = make(api, "Уйдёт", ids).json()
    assert api.delete(f"/api/collages/{item['id']}").status_code == 204
    assert api.get("/api/collages").json() == []
    assert api.get(f"/api/collages/{item['id']}").status_code == 404
    assert api.get(item["download_url"]).status_code == 404
    assert api.delete(f"/api/collages/{item['id']}").status_code == 404
    assert all(api.get(f"/api/files/{i}").status_code == 200 for i in ids)


def test_a_waiting_project_cannot_make_collages(db):
    waiting = Actor(1, Role.OWNER, project_id=1, pending=True)
    with pytest.raises(PermissionDenied, match="Гость|не подтверждён"):
        collages.create(
            db, waiting, projects.current(db), title="Ждёт", file_ids=[1, 2], settings=_settings()
        )
    guest = Actor(2, Role.GUEST, project_id=1)
    with pytest.raises(PermissionDenied):
        collages.create(
            db, guest, projects.current(db), title="Гость", file_ids=[1, 2], settings=_settings()
        )


def _settings():
    from app.config import get_settings

    return get_settings()


def test_requests_come_only_from_our_own_pages(api):
    ids = three(api)
    bad = api.post(
        "/api/collages",
        json={"title": "Чужой сайт", "file_ids": ids},
        headers={"Origin": "https://evil.example"},
    )
    assert bad.status_code == 403 and api.get("/api/collages").json() == []


# --- проекты не видят друг друга ---------------------------------------------------------------------------------------


def test_another_project_sees_nothing_and_cannot_use_foreign_photos(api):
    ids = three(api)
    item = make(api, "Только наше", ids).json()
    with database.session_factory()() as db:
        db.add(
            models.Project(
                **{
                    **projects.DEFAULT_PROJECT,
                    "slug": "second",
                    "title": "Второй",
                    "approved_at": datetime.now(UTC),
                }
            )
        )
        db.commit()
    other = person("Режиссёр", {"second": Role.DIRECTOR})
    act_as(api, other)
    assert api.get("/api/p/second/collages").json() == []
    assert api.get(f"/api/p/second/collages/{item['id']}").status_code == 404
    assert api.get(f"/api/p/second/collages/{item['id']}/download").status_code == 404
    assert api.get(f"/api/p/second/collages/{item['id']}/photos.zip").status_code == 404
    assert api.delete(f"/api/p/second/collages/{item['id']}").status_code == 404
    foreign = api.post("/api/p/second/collages", json={"title": "Воровство", "file_ids": ids})
    assert foreign.status_code == 422 and "нет в проекте" in foreign.json()["detail"]


def test_the_journal_records_who_made_and_who_deleted_a_collage(api):
    item = make(api, "В журнале", three(api)).json()
    api.delete(f"/api/collages/{item['id']}")
    rows = api.get("/api/activity").json()
    entries = (
        [r for r in rows["items"] if r["entity_type"] == "collage"]
        if isinstance(rows, dict)
        else [r for r in rows if r["entity_type"] == "collage"]
    )
    assert {e["action"] for e in entries} == {"create", "delete"}
    assert all("В журнале" in (e.get("entity_label") or e.get("label") or "") for e in entries)


# --- правка готового коллажа ---------------------------------------------------------------------------------------


def edit(client, collage_id, **body):
    return client.patch(f"/api/collages/{collage_id}", json=body)


def state(collage_id: int) -> dict:
    """Что записано в базе: название, картинка, фото по порядку, число файлов проекта."""
    with database.session_factory()() as db:
        row = db.get(models.Collage, collage_id)
        image = db.get(models.File, row.file_id)
        photos = list(
            db.scalars(
                select(models.CollagePhoto.file_id)
                .where(models.CollagePhoto.collage_id == collage_id)
                .order_by(models.CollagePhoto.position)
            )
        )
        return {
            "title": row.title,
            "file_id": row.file_id,
            "image_name": image.original_name,
            "image_deleted": image.deleted_at is not None,
            "photos": photos,
            "files": db.scalar(select(func.count()).select_from(models.File)),
        }


def test_renaming_changes_the_title_but_not_the_picture_and_nothing_is_rebuilt(api):
    ids = three(api)
    item = make(api, "Старое имя", ids).json()
    before = state(item["id"])
    done = edit(api, item["id"], title="  Одежда   северян ")
    assert done.status_code == 200, done.text
    assert done.json()["title"] == "Одежда северян"
    after = state(item["id"])
    assert (
        after["file_id"] == before["file_id"] and after["files"] == before["files"]
    )  # картинку не собирали
    assert after["photos"] == before["photos"] and after["image_name"] == "Одежда северян.jpg"
    assert [c["title"] for c in api.get("/api/collages").json()] == ["Одежда северян"]
    disposition = api.get(item["download_url"]).headers["content-disposition"]
    assert quote("Одежда северян.jpg", safe="") in disposition


def test_the_picture_file_keeps_its_name_when_another_collage_shares_it(api):
    ids = three(api)
    one = make(api, "Общая картинка", ids).json()
    two = make(api, "Тот же набор", ids).json()  # та же картинка у двух коллажей
    edit(api, one["id"], title="Переименован")
    assert state(one["id"])["image_name"] == "Общая картинка.jpg"
    assert state(two["id"])["title"] == "Тот же набор"


def test_a_bad_title_is_refused_and_nothing_changes(api):
    item = make(api, "Как было", three(api)).json()
    for title in ("   ", "я" * (collages.MAX_TITLE + 1)):
        assert edit(api, item["id"], title=title).status_code == 422
    assert state(item["id"])["title"] == "Как было"


def test_changing_the_order_rebuilds_the_picture_and_the_zip_follows_the_new_order(api):
    ids = three(api)
    item = make(api, "Порядок", ids).json()
    before = state(item["id"])
    done = edit(api, item["id"], file_ids=[ids[2], ids[1], ids[0]])
    assert done.status_code == 200, done.text
    after = state(item["id"])
    assert after["photos"] == [ids[2], ids[1], ids[0]] and after["file_id"] != before["file_id"]
    assert after["image_deleted"] is False
    with (
        database.session_factory()() as db
    ):  # прежняя картинка больше никому не нужна: ушла в удалённые
        assert db.get(models.File, before["file_id"]).deleted_at is not None
    names = [p["original_name"] for p in done.json()["photo_list"]]
    assert names == ["север-3.jpg", "север-2.jpg", "север-1.jpg"]
    with zipfile.ZipFile(io.BytesIO(api.get(item["zip_url"]).content)) as zf:
        assert zf.namelist() == [f"{n:02d}_{name}" for n, name in enumerate(names, 1)]
    with Image.open(io.BytesIO(api.get(item["download_url"]).content)) as out:
        assert out.size == (done.json()["width"], done.json()["height"])


def test_photos_can_be_removed_and_added_in_a_finished_collage(api):
    ids = three(api)
    item = make(api, "Состав", ids).json()
    fewer = edit(api, item["id"], file_ids=[ids[0], ids[2]])
    assert fewer.status_code == 200 and fewer.json()["photos"] == 2
    extra = photo(api, "новое.jpg", (900, 900), (200, 200, 30))
    more = edit(api, item["id"], file_ids=[extra, ids[0], ids[2]])
    assert more.status_code == 200 and more.json()["photos"] == 3
    assert state(item["id"])["photos"] == [extra, ids[0], ids[2]]
    assert all(
        api.get(f"/api/files/{i}").status_code == 200 for i in ids
    )  # убранное осталось файлом проекта


def test_the_same_list_is_not_rebuilt(api):
    ids = three(api)
    item = make(api, "Без изменений", ids).json()
    before = state(item["id"])
    assert edit(api, item["id"], file_ids=ids).status_code == 200
    assert state(item["id"]) == before


def test_title_and_photos_can_change_together_and_the_new_picture_gets_the_new_name(api):
    ids = three(api)
    item = make(api, "Было", ids).json()
    done = edit(api, item["id"], title="Стало", file_ids=ids[:2])
    assert done.status_code == 200
    after = state(item["id"])
    assert (after["title"], after["image_name"], len(after["photos"])) == ("Стало", "Стало.jpg", 2)


def test_a_picture_that_another_collage_still_uses_is_kept(api):
    ids = three(api)
    one = make(api, "Первый", ids).json()
    two = make(api, "Второй", ids).json()  # общая картинка
    shared = state(one["id"])["file_id"]
    edit(api, one["id"], file_ids=ids[:2])
    assert state(two["id"])["file_id"] == shared and state(two["id"])["image_deleted"] is False
    assert api.get(two["download_url"]).status_code == 200


@pytest.mark.parametrize(
    "mutate",
    [
        lambda ids, extra: ids[:1],  # одно фото
        lambda ids, extra: [ids[0], ids[0]],  # дважды
        lambda ids, extra: [ids[0], 999_999],  # нет такого
        lambda ids, extra: [ids[0], extra["text"]],  # не картинка
        lambda ids, extra: [ids[0], extra["bad"]],  # битая
    ],
    ids=["одно", "дважды", "нет", "не-картинка", "битая"],
)
def test_a_wrong_new_set_is_refused_and_the_collage_is_untouched(api, mutate):
    ids = three(api)
    extra = {
        "text": upload(api, b"just text", "note.txt", no_compress=True).json()["file"]["id"],
        "bad": upload(api, "не картинка".encode(), "bad.jpg", no_compress=True).json()["file"][
            "id"
        ],
    }
    item = make(api, "Целый", ids).json()
    before = state(item["id"])
    assert edit(api, item["id"], file_ids=mutate(ids, extra)).status_code == 422
    assert state(item["id"]) == before


def test_eleven_photos_are_too_many_when_editing_too(api):
    ids = three(api)
    item = make(api, "Мало", ids).json()
    many = [photo(api, f"q{i}.jpg", (800, 600), (15 * i, 90, 200)) for i in range(11)]
    refused = edit(api, item["id"], file_ids=many)
    assert refused.status_code == 422 and "от 2 до 10" in refused.json()["detail"]
    assert len(state(item["id"])["photos"]) == 3


def test_a_deleted_photo_cannot_be_put_into_a_new_arrangement(api):
    ids = three(api)
    item = make(api, "Фото ушло", ids).json()
    api.delete(f"/api/files/{ids[1]}")
    refused = edit(
        api, item["id"], file_ids=[ids[2], ids[1], ids[0]]
    )  # другой порядок, удалённое фото в нём
    assert refused.status_code == 422 and "нет в проекте" in refused.json()["detail"]
    assert edit(api, item["id"], file_ids=[ids[0], ids[2]]).status_code == 200  # а без него можно
    assert (
        edit(api, item["id"], title="Переименовано").status_code == 200
    )  # и название меняется свободно


def test_an_empty_or_unknown_request_is_refused(api):
    item = make(api, "Пусто", three(api)).json()
    assert edit(api, item["id"]).status_code == 422
    assert "Нечего менять" in edit(api, item["id"]).json()["detail"]
    assert edit(api, item["id"], color="red").status_code == 422
    assert edit(api, item["id"], file_ids=[]).status_code == 422


def test_the_team_edits_its_own_collage_only_and_director_and_owner_edit_any(api):
    ids = three(api)
    login(api, "team", "Петя")
    mine = make(api, "Моё", ids).json()
    assert edit(api, mine["id"], title="Моё, исправлено").status_code == 200
    login(api, "owner", "Артём")
    theirs = make(api, "Чужое", ids[:2]).json()
    login(api, "team", "Лена")
    assert edit(api, theirs["id"], title="Захват").status_code == 403
    assert edit(api, theirs["id"], file_ids=ids).status_code == 403
    assert state(theirs["id"])["title"] == "Чужое"
    login(api, "director", "Дина")
    assert edit(api, mine["id"], title="Режиссёр").status_code == 200
    login(api, "owner", "Артём")
    assert edit(api, mine["id"], file_ids=ids[:2]).status_code == 200


def test_a_guest_cannot_edit(api):
    item = make(api, "Не гостю", three(api)).json()
    login(api, "guest", "Гость")
    assert edit(api, item["id"], title="Гость").status_code == 403


def test_in_a_waiting_project_the_title_can_change_but_the_photos_cannot(api):
    ids = three(api)
    item = make(api, "Ждёт", ids).json()
    with database.session_factory()() as db:
        db.scalar(select(models.Project)).approved_at = None
        db.commit()
    assert edit(api, item["id"], title="Ждёт подтверждения").status_code == 200
    refused = edit(api, item["id"], file_ids=ids[:2])
    assert refused.status_code == 403 and "не подтверждён" in refused.json()["detail"]
    assert len(state(item["id"])["photos"]) == 3


def test_when_the_disk_is_full_the_photos_stay_but_the_title_can_still_change(api, monkeypatch):
    ids = three(api)
    item = make(api, "Тесно", ids).json()
    before = state(item["id"])

    def full(*_args, **_kwargs):
        raise storage.NoRoom("На диске не хватает места")

    monkeypatch.setattr(storage, "ensure_room", full)
    refused = edit(api, item["id"], file_ids=ids[:2])
    assert refused.status_code == 507 and state(item["id"]) == before
    assert edit(api, item["id"], title="Всё ещё можно").status_code == 200


def test_a_deleted_collage_cannot_be_edited(api):
    item = make(api, "Был", three(api)).json()
    api.delete(f"/api/collages/{item['id']}")
    assert edit(api, item["id"], title="Воскрес").status_code == 404


def test_another_project_cannot_edit_a_collage(api):
    ids = three(api)
    item = make(api, "Своё", ids).json()
    with database.session_factory()() as db:
        db.add(
            models.Project(
                **{
                    **projects.DEFAULT_PROJECT,
                    "slug": "second",
                    "title": "Второй",
                    "approved_at": datetime.now(UTC),
                }
            )
        )
        db.commit()
    act_as(api, person("Режиссёр", {"second": Role.DIRECTOR}))
    assert (
        api.patch(f"/api/p/second/collages/{item['id']}", json={"title": "Чужой"}).status_code
        == 404
    )
    assert state(item["id"])["title"] == "Своё"


def test_the_journal_records_what_was_changed(api):
    ids = three(api)
    item = make(api, "Для журнала", ids).json()
    edit(api, item["id"], title="Новое имя", file_ids=ids[:2])
    with database.session_factory()() as db:
        entry = db.scalar(
            select(models.Activity).where(
                models.Activity.entity_type == "collage", models.Activity.action == "update"
            )
        )
        assert entry.entity_id == item["id"]
        assert entry.diff["title"] == {"было": "Для журнала", "стало": "Новое имя"}
        assert entry.diff["photos"] == {"было": 3, "стало": 2}


@pytest.fixture
def renders(monkeypatch):
    """Сколько раз сервер собирал картинку: лишней сборки быть не должно."""
    calls: list[int] = []
    real = engine.render

    def counting(photos, dest, **kwargs):
        calls.append(len(photos))
        return real(photos, dest, **kwargs)

    monkeypatch.setattr(collages.engine, "render", counting)
    return calls


def test_the_picture_is_built_only_when_the_photos_really_change(api, renders):
    ids = three(api)
    item = make(api, "Считаем", ids).json()
    assert renders == [3]
    edit(api, item["id"], title="Другое имя")
    edit(api, item["id"], file_ids=ids)  # тот же список
    edit(api, item["id"], title="И ещё имя", file_ids=ids)
    assert renders == [3]  # переименование и тот же набор картинку не пересобирают
    edit(api, item["id"], file_ids=[ids[1], ids[0], ids[2]])
    assert renders == [3, 3]


def test_a_waiting_project_is_refused_before_any_picture_is_built(api, renders):
    ids = three(api)
    item = make(api, "Ждёт", ids).json()
    with database.session_factory()() as db:
        db.scalar(select(models.Project)).approved_at = None
        db.commit()
    assert edit(api, item["id"], file_ids=ids[:2]).status_code == 403
    assert renders == [3]  # только первая сборка, при создании
