"""Переименование проекта: только владелец, адрес не меняется, правка попадает в журнал."""

import pytest

from app import models
from app.constants import Role
from app.permissions import PermissionDenied
from app.services import projects
from tests.conftest import login
from tests.factories import actor, make_user


def test_owner_renames_and_the_address_stays(db):
    owner = actor(make_user(db, Role.OWNER, "Артём"))
    project = projects.current(db)
    old_title, slug = project.title, project.slug
    projects.rename(db, owner, title="  Новое название  ", title_en="New Title")
    db.flush()
    assert (project.title, project.title_en) == ("Новое название", "New Title")  # края обрезаны
    assert project.slug == slug  # ссылки, закладки и подписанные ссылки продолжают работать
    entry = db.query(models.Activity).filter_by(entity_type="project", action="update").one()
    assert entry.diff == {
        "title": [old_title, "Новое название"],
        "title_en": ["The Brass Spyglass", "New Title"],
    }
    assert entry.entity_id == project.id and entry.project_id == project.id
    assert entry.actor_id == owner.id


def test_changing_only_one_name_touches_only_that_one(db):
    owner = actor(make_user(db, Role.OWNER, "Артём"))
    project = projects.current(db)
    english = project.title_en
    projects.rename(db, owner, title="Только русское")
    assert project.title == "Только русское" and project.title_en == english
    (entry,) = db.query(models.Activity).filter_by(entity_type="project", action="update").all()
    assert list(entry.diff) == ["title"]


def test_the_same_name_leaves_no_trace_in_the_journal(db):
    owner = actor(make_user(db, Role.OWNER, "Артём"))
    project = projects.current(db)
    projects.rename(db, owner, title=project.title, title_en=project.title_en)
    projects.rename(db, owner)  # ничего не передано
    assert db.query(models.Activity).filter_by(entity_type="project", action="update").count() == 0


@pytest.mark.parametrize("role", [Role.DIRECTOR, Role.TEAM, Role.GUEST])
def test_nobody_but_the_owner_renames(db, role):
    who = actor(make_user(db, role, "Кто-то"))
    before = projects.current(db).title
    with pytest.raises(PermissionDenied):
        projects.rename(db, who, title="Захват")
    assert projects.current(db).title == before


def test_api_rename_is_visible_everywhere_and_in_the_journal(seeded_client):
    login(seeded_client, "owner", "Артём")
    done = seeded_client.patch(
        "/api/project", json={"title": "Кривое зеркало", "title_en": "Crooked Mirror"}
    )
    assert done.status_code == 200, done.text
    assert done.json()["title"] == "Кривое зеркало" and done.json()["slug"] == "brass-spyglass"
    assert seeded_client.get("/api/project").json()["title_en"] == "Crooked Mirror"
    # переключатель проектов берёт названия из сессии
    listed = seeded_client.get("/api/projects").json()
    assert [(p["slug"], p["title"]) for p in listed] == [("brass-spyglass", "Кривое зеркало")]
    journal = seeded_client.get("/api/activity", params={"entity_type": "project"}).json()["items"]
    assert journal[0]["action"] == "update" and journal[0]["diff"]["title"][1] == "Кривое зеркало"
    assert "Кривое зеркало" in journal[0]["label"]


@pytest.mark.parametrize("role", ["director", "team", "guest"])
def test_api_refuses_everybody_but_the_owner(seeded_client, role):
    login(seeded_client, role, "Кто-то")
    before = seeded_client.get("/api/project").json()["title"]
    assert seeded_client.patch("/api/project", json={"title": "Захват"}).status_code == 403
    assert seeded_client.get("/api/project").json()["title"] == before
    assert seeded_client.get("/api/me").json()["abilities"]["edit_project"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title_en": ""},
        {"slug": "hacked"},  # адрес не меняется
        {"deadline_official": "2030-01-01T00:00:00Z"},  # меняются только названия
        {"title": 5},
    ],
)
def test_api_rejects_bad_names_and_other_fields(seeded_client, body):
    login(seeded_client, "owner", "Артём")
    before = seeded_client.get("/api/project").json()
    assert seeded_client.patch("/api/project", json=body).status_code == 422
    assert seeded_client.get("/api/project").json() == before


def test_api_refuses_a_foreign_origin(seeded_client):
    login(seeded_client, "owner", "Артём")
    bad = seeded_client.patch(
        "/api/project", json={"title": "Чужой сайт"}, headers={"Origin": "https://evil.example"}
    )
    assert bad.status_code == 403
    assert seeded_client.get("/api/project").json()["title"] != "Чужой сайт"
