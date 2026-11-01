"""Уведомления на сайте: комментарий или файл на карточке → остальным; клик ведёт в карточку."""

from datetime import timedelta

import pytest

from app import db as database
from app import models
from app.db import utcnow
from app.services import notifications
from tests.conftest import login
from tests.test_files import upload


class Team:
    """Несколько участников в одном клиенте: переключение — подменой cookie сессии."""

    def __init__(self, client):
        self.client = client
        self.people = {}
        self.cookies = {}
        for key, role, name in (
            ("artem", "owner", "Артём"),
            ("dina", "team", "Дина"),
            ("petya", "team", "Петя"),
            ("guest", "guest", "Гость"),
        ):
            self.people[key] = login(client, role, name)
            self.cookies[key] = client.cookies.get("bs_session")

    def as_(self, key):
        self.client.cookies.set("bs_session", self.cookies[key])
        return self.client


@pytest.fixture
def team(seeded_client):
    return Team(seeded_client)


def video(n: int) -> bytes:
    return (b"notify-video-%d-" % n) * 40


def first_shot(client):
    return client.get("/api/shots").json()[0]


def inbox(client):
    return client.get("/api/notifications").json()


def comment(client, entity_type, entity_id, body):
    response = client.post(
        "/api/comments", json={"entity_type": entity_type, "entity_id": entity_id, "body": body}
    )
    assert response.status_code == 201, response.text


# --- кого уведомляем ------------------------------------------------------------------------------


def test_a_comment_notifies_everyone_except_its_author(team):
    shot = first_shot(team.as_("artem"))
    comment(team.as_("artem"), "shot", shot["id"], "давай сделаем персонажа чуть реальнее")
    assert inbox(team.as_("artem")) == {"unread": 0, "items": []}  # автору — ничего
    for key in ("dina", "petya", "guest"):
        data = inbox(team.as_(key))
        assert data["unread"] == 1
        item = data["items"][0]
        assert item["kind"] == "comment" and item["actor"]["name"] == "Артём"
        assert item["snippet"] == "давай сделаем персонажа чуть реальнее"
        assert item["read"] is False and item["label"] == f"шот {shot['code']}"


def test_a_file_added_to_a_card_notifies_the_others_and_names_the_file(team):
    shot = first_shot(team.as_("dina"))
    response = upload(
        team.as_("dina"),
        video(1),
        "take.mp4",
        entity_type="shot",
        entity_id=shot["id"],
        purpose="take",
    )
    assert response.status_code == 201
    item = inbox(team.as_("artem"))["items"][0]
    assert item["kind"] == "file" and item["snippet"] == "take.mp4"
    assert item["actor"]["name"] == "Дина" and item["entity_id"] == shot["id"]
    assert inbox(team.as_("dina"))["unread"] == 0


def test_a_new_version_notifies_but_a_rollback_does_not(team):
    shot = first_shot(team.as_("dina"))
    first = upload(team.as_("dina"), video(1), "take.mp4", entity_type="shot", entity_id=shot["id"])
    v1 = first.json()["file"]["id"]
    team.as_("petya").post("/api/notifications/read-all")

    upload(team.as_("dina"), video(2), "take_v2.mp4", version_of=v1)
    data = inbox(team.as_("petya"))
    assert data["unread"] == 1 and data["items"][0]["kind"] == "version"
    assert data["items"][0]["snippet"] == "take_v2.mp4 · v2"

    team.as_("petya").post("/api/notifications/read-all")
    assert team.as_("dina").post(f"/api/files/{v1}/rollback").status_code == 200
    assert inbox(team.as_("petya"))["unread"] == 0  # откат — не новость для команды


def test_people_who_lost_access_are_not_notified(team):
    with database.session_factory()() as db:
        db.get(models.User, team.people["petya"].id).access_revoked_at = utcnow()
        db.commit()
    shot = first_shot(team.as_("artem"))
    comment(team.as_("artem"), "shot", shot["id"], "привет")
    assert inbox(team.as_("dina"))["unread"] == 1
    with database.session_factory()() as db:
        count = db.query(models.Notification).filter_by(user_id=team.people["petya"].id).count()
    assert count == 0


# --- склейка ---------------------------------------------------------------------------------------


def test_a_burst_of_files_from_one_author_is_one_notification(team):
    shot = first_shot(team.as_("artem"))
    for n in range(3):
        upload(
            team.as_("artem"),
            video(10 + n),
            f"take{n}.mp4",
            entity_type="shot",
            entity_id=shot["id"],
        )
    data = inbox(team.as_("dina"))
    assert data["unread"] == 1 and data["items"][0]["count"] == 3
    assert data["items"][0]["snippet"] == "take2.mp4"  # последний из пачки


def test_a_read_notification_is_not_merged_into_a_new_one(team):
    shot = first_shot(team.as_("artem"))
    comment(team.as_("artem"), "shot", shot["id"], "раз")
    nid = inbox(team.as_("dina"))["items"][0]["id"]
    assert team.as_("dina").post(f"/api/notifications/{nid}/read").json() == {"unread": 0}
    comment(team.as_("artem"), "shot", shot["id"], "два")
    data = inbox(team.as_("dina"))
    assert data["unread"] == 1 and len(data["items"]) == 2 and data["items"][0]["count"] == 1


def test_different_authors_are_separate_notifications(team):
    shot = first_shot(team.as_("artem"))
    comment(team.as_("artem"), "shot", shot["id"], "от Артёма")
    comment(team.as_("petya"), "shot", shot["id"], "от Пети")
    data = inbox(team.as_("dina"))
    assert data["unread"] == 2 and {i["actor"]["name"] for i in data["items"]} == {"Артём", "Петя"}


# --- куда ведёт клик --------------------------------------------------------------------------------


def test_the_click_leads_to_the_card(team):
    client = team.as_("artem")
    shot, scene = first_shot(client), client.get("/api/scenes").json()[0]
    asset = client.get("/api/assets").json()[0]
    comment(client, "shot", shot["id"], "шот")
    comment(client, "scene", scene["id"], "сцена")
    comment(client, "asset", asset["id"], "ассет")
    urls = {i["entity_type"]: i["url"] for i in inbox(team.as_("dina"))["items"]}
    assert urls["shot"] == f"/shots?shot={shot['id']}"
    assert urls["scene"] == f"/scenes/{scene['id']}"
    assert urls["asset"] == f"/assets?asset={asset['id']}"


def test_a_comment_on_an_asset_state_leads_to_its_asset(team):
    client = team.as_("artem")
    detail = next(
        a for a in client.get("/api/assets").json() if a["code"] == "CH-04"
    )  # овца: 4 состояния
    asset = client.get(f"/api/assets/{detail['id']}").json()
    state = asset["states"][0]
    comment(client, "asset_state", state["id"], "про состояние")
    item = inbox(team.as_("dina"))["items"][0]
    assert item["entity_type"] == "asset" and item["url"] == f"/assets?asset={detail['id']}"


def test_a_comment_on_a_file_leads_to_the_card_where_it_lies(team):
    client = team.as_("artem")
    shot = first_shot(client)
    file_id = upload(client, video(5), "x.mp4", entity_type="shot", entity_id=shot["id"]).json()[
        "file"
    ]["id"]
    team.as_("dina").post("/api/notifications/read-all")
    comment(client, "file", file_id, "про сам файл")
    item = inbox(team.as_("dina"))["items"][0]
    assert item["entity_type"] == "shot" and item["url"] == f"/shots?shot={shot['id']}"


# --- отметки и права -------------------------------------------------------------------------------


def test_read_marks_only_my_copy(team):
    shot = first_shot(team.as_("artem"))
    comment(team.as_("artem"), "shot", shot["id"], "всем")
    mine = inbox(team.as_("dina"))["items"][0]["id"]
    assert team.as_("dina").post(f"/api/notifications/{mine}/read").status_code == 200
    assert inbox(team.as_("dina"))["unread"] == 0
    assert inbox(team.as_("petya"))["unread"] == 1  # у других осталось


def test_a_foreign_notification_cannot_be_marked_read(team):
    shot = first_shot(team.as_("artem"))
    comment(team.as_("artem"), "shot", shot["id"], "всем")
    foreign = inbox(team.as_("petya"))["items"][0]["id"]
    assert team.as_("dina").post(f"/api/notifications/{foreign}/read").status_code == 404
    assert inbox(team.as_("petya"))["unread"] == 1


def test_read_all_clears_the_counter(team):
    shot = first_shot(team.as_("artem"))
    for text in ("a", "b"):
        comment(team.as_("artem"), "shot", shot["id"], text)
        comment(team.as_("petya"), "shot", shot["id"], text)
    assert inbox(team.as_("dina"))["unread"] == 2
    assert team.as_("dina").post("/api/notifications/read-all").json() == {"unread": 0}
    data = inbox(team.as_("dina"))
    assert data["unread"] == 0 and len(data["items"]) == 2 and all(i["read"] for i in data["items"])


def test_the_inbox_needs_a_session(seeded_client):
    seeded_client.cookies.clear()
    assert seeded_client.get("/api/notifications").status_code == 401


def test_foreign_origin_cannot_mark_read(team):
    response = team.as_("dina").post(
        "/api/notifications/read-all", headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


def test_a_failed_action_leaves_no_notification(team):
    response = team.as_("artem").post(
        "/api/comments", json={"entity_type": "shot", "entity_id": 999999, "body": "в никуда"}
    )
    assert response.status_code == 404
    assert inbox(team.as_("dina"))["unread"] == 0


def test_old_notifications_are_pruned(team):
    shot = first_shot(team.as_("artem"))
    comment(team.as_("artem"), "shot", shot["id"], "старое")
    with database.session_factory()() as db:
        for row in db.query(models.Notification).all():
            row.created_at = utcnow() - timedelta(days=notifications.KEEP_DAYS + 1)
        assert notifications.prune(db) == 3
        db.commit()
    assert inbox(team.as_("dina"))["items"] == []
