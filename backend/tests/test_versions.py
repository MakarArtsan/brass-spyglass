"""Версии файлов (v1, v2, v3, откат) и финальный файл сцены и шота."""

import pytest

from tests.conftest import login
from tests.test_files import upload


@pytest.fixture
def api(seeded_client):
    login(seeded_client, "owner", "Артём")
    return seeded_client


def video(n: int) -> bytes:
    return (b"not-a-real-video-%d-" % n) * 50


def first_shot(client) -> int:
    return client.get("/api/shots").json()[0]["id"]


def put_video(client, shot_id: int, n: int = 1, name: str = "take.mp4") -> int:
    response = upload(client, video(n), name, entity_type="shot", entity_id=shot_id, purpose="take")
    assert response.status_code == 201, response.text
    return response.json()["file"]["id"]


def card_files(client, shot_id: int) -> list[dict]:
    rows = client.get("/api/files", params={"entity_type": "shot", "entity_id": shot_id}).json()
    return [r["file"] for r in rows]


# --- версии ----------------------------------------------------------------------------------------


def test_a_new_version_keeps_the_old_one_and_takes_its_place_on_the_card(api):
    shot = first_shot(api)
    v1 = put_video(api, shot)
    response = upload(api, video(2), "take_v2.mp4", version_of=v1)
    assert response.status_code == 201, response.text
    v2 = response.json()["file"]
    assert (v2["version_no"], v2["is_current"], v2["versions_count"]) == (2, True, 2)

    shown = card_files(api, shot)
    assert [f["id"] for f in shown] == [v2["id"]]  # на карточке одна запись — текущая версия
    history = api.get(f"/api/files/{v1}/versions").json()
    assert [(f["version_no"], f["is_current"]) for f in history] == [(2, True), (1, False)]
    assert all(f["uploaded_by"]["name"] == "Артём" for f in history)  # у каждой версии автор
    # оригинал v1 не тронут и отдаётся
    old = api.get(f"/api/files/{v1}").json()
    assert api.get(old["urls"]["original"]).status_code == 200


def test_versions_are_counted_once_on_the_shot_and_in_the_library(api):
    shot = first_shot(api)
    v1 = put_video(api, shot)
    upload(api, video(2), "take_v2.mp4", version_of=v1)
    upload(api, video(3), "take_v3.mp4", version_of=v1)  # можно ссылаться на любую версию группы

    listed = next(s for s in api.get("/api/shots").json() if s["id"] == shot)
    assert listed["files_count"] == 1
    assert api.get("/api/shots").json()[0]["takes_count"] in (0, 1)
    library = api.get("/api/library").json()
    assert library["total"] == 1 and library["items"][0]["version_no"] == 3


def test_rollback_makes_an_older_version_current_and_is_journaled(api):
    shot = first_shot(api)
    v1 = put_video(api, shot)
    v2 = upload(api, video(2), "take_v2.mp4", version_of=v1).json()["file"]["id"]

    back = api.post(f"/api/files/{v1}/rollback")
    assert back.status_code == 200 and back.json()["is_current"] is True
    assert [f["id"] for f in card_files(api, shot)] == [v1]
    assert api.get(f"/api/files/{v2}").json()["is_current"] is False

    actions = [(a["action"], a["entity_type"]) for a in api.get("/api/activity").json()["items"]]
    assert ("rollback", "file") in actions and ("rollback", "shot") in actions
    # откат обратим
    assert api.post(f"/api/files/{v2}/rollback").status_code == 200
    assert [f["id"] for f in card_files(api, shot)] == [v2]


def test_rolling_back_to_the_current_version_or_a_single_file_is_refused(api):
    shot = first_shot(api)
    single = put_video(api, shot)
    assert api.post(f"/api/files/{single}/rollback").status_code == 422
    v2 = upload(api, video(2), "take_v2.mp4", version_of=single).json()["file"]["id"]
    assert api.post(f"/api/files/{v2}/rollback").status_code == 422


def test_a_new_version_must_be_the_same_kind_and_not_a_copy_of_an_existing_one(api):
    shot = first_shot(api)
    v1 = put_video(api, shot)
    wrong = upload(api, b"just words", "notes.txt", version_of=v1)
    assert wrong.status_code == 422
    same = upload(api, video(1), "take_again.mp4", version_of=v1)
    assert same.status_code == 409


def test_a_new_version_cannot_be_combined_with_a_card(api):
    shot = first_shot(api)
    v1 = put_video(api, shot)
    response = upload(api, video(2), "v2.mp4", version_of=v1, entity_type="shot", entity_id=shot)
    assert response.status_code == 422


def test_a_guest_cannot_add_versions_or_roll_back(api):
    shot = first_shot(api)
    v1 = put_video(api, shot)
    v2 = upload(api, video(2), "take_v2.mp4", version_of=v1).json()["file"]["id"]
    login(api, "guest", "Гость")
    init = api.post("/api/uploads", json={"name": "v3.mp4", "size": 10})
    assert init.status_code == 403  # гость не начинает загрузку, а значит и новую версию
    assert api.post(f"/api/files/{v1}/rollback").status_code == 403
    assert api.get(f"/api/files/{v2}/versions").status_code == 200  # смотреть можно


def test_the_author_of_a_version_is_the_session_user_not_the_uploader_of_v1(api):
    shot = first_shot(api)
    v1 = put_video(api, shot)
    login(api, "team", "Дина")
    v2 = upload(api, video(2), "take_v2.mp4", version_of=v1).json()["file"]
    assert v2["uploaded_by"]["name"] == "Дина"
    authors = {
        f["version_no"]: f["uploaded_by"]["name"]
        for f in api.get(f"/api/files/{v1}/versions").json()
    }
    assert authors == {1: "Артём", 2: "Дина"}


# --- финальный файл ------------------------------------------------------------------------------


def test_the_final_file_follows_the_current_version(api):
    shot = first_shot(api)
    v1 = put_video(api, shot)
    chosen = api.put(f"/api/shots/{shot}/final", json={"file_id": v1})
    assert chosen.status_code == 200 and chosen.json()["final"]["id"] == v1

    v2 = upload(api, video(2), "take_v2.mp4", version_of=v1).json()["file"]["id"]
    listed = next(s for s in api.get("/api/shots").json() if s["id"] == shot)
    assert listed["final"]["id"] == v2 and listed["final"]["version_no"] == 2
    api.post(f"/api/files/{v1}/rollback")
    listed = next(s for s in api.get("/api/shots").json() if s["id"] == shot)
    assert listed["final"]["id"] == v1


def test_the_final_file_of_a_scene(api):
    scene = api.get("/api/scenes").json()[0]["id"]
    file_id = upload(api, video(1), "scene.mp4", entity_type="scene", entity_id=scene).json()[
        "file"
    ]["id"]
    assert api.put(f"/api/scenes/{scene}/final", json={"file_id": file_id}).status_code == 200
    assert api.get("/api/scenes").json()[0]["final"]["id"] == file_id
    assert api.put(f"/api/scenes/{scene}/final", json={"file_id": None}).json()["final"] is None
    assert api.get("/api/scenes").json()[0]["final_file_id"] is None


def test_only_a_video_attached_to_that_card_can_be_final(api):
    shot, other = api.get("/api/shots").json()[:2]
    mine = put_video(api, shot["id"])
    foreign = put_video(api, other["id"], 2, "other.mp4")
    assert api.put(f"/api/shots/{shot['id']}/final", json={"file_id": foreign}).status_code == 422
    still = upload(
        api, b"\x89PNG-not-really", "frame.png", entity_type="shot", entity_id=shot["id"]
    )
    assert (
        api.put(
            f"/api/shots/{shot['id']}/final", json={"file_id": still.json()["file"]["id"]}
        ).status_code
        == 422
    )
    assert api.put(f"/api/shots/{shot['id']}/final", json={"file_id": mine}).status_code == 200


def test_the_final_file_cannot_be_forced_through_the_generic_update(api):
    shot = first_shot(api)
    file_id = put_video(api, shot)
    assert api.patch(f"/api/shots/{shot}", json={"final_file_id": file_id}).status_code == 422


def test_final_choice_follows_the_role_matrix(api):
    shot = first_shot(api)  # карточку создал импорт, не «Дина»
    file_id = put_video(api, shot)
    login(api, "team", "Дина")
    assert api.put(f"/api/shots/{shot}/final", json={"file_id": file_id}).status_code == 403
    login(api, "guest", "Гость")
    assert api.put(f"/api/shots/{shot}/final", json={"file_id": file_id}).status_code == 403
    login(api, "director", "Режиссёр")
    assert api.put(f"/api/shots/{shot}/final", json={"file_id": file_id}).status_code == 200


def test_a_deleted_final_file_does_not_stay_on_the_timeline(api):
    shot = first_shot(api)
    file_id = put_video(api, shot)
    api.put(f"/api/shots/{shot}/final", json={"file_id": file_id})
    assert api.delete(f"/api/files/{file_id}").status_code == 204
    listed = next(s for s in api.get("/api/shots").json() if s["id"] == shot)
    assert listed["final"] is None
