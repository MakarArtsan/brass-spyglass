"""Проекты и их участники: адрес, чат, роль на паре «человек + проект»."""

import pytest

from app import models
from app.config import Settings, get_settings
from app.constants import Role
from app.services import members, projects, users


def settings(**env) -> Settings:
    return Settings(**{"session_secret": "x", **env})


def test_the_default_project_gets_a_slug_and_the_configured_chat(db, monkeypatch):
    monkeypatch.setenv("TG_CHAT_ID", "-1001234567890")
    get_settings.cache_clear()
    project = projects.ensure_default_project(db)
    assert project.slug == "brass-spyglass" and project.tg_chat_id == -1001234567890
    assert projects.get_by_slug(db, "brass-spyglass").id == project.id
    assert projects.get_by_chat(db, -1001234567890).id == project.id


def test_the_chat_is_not_taken_from_another_project_or_overwritten(db, monkeypatch):
    project = projects.ensure_default_project(db)
    other = models.Project(**{**projects.DEFAULT_PROJECT, "slug": "second", "tg_chat_id": -100777})
    db.add(other)
    db.flush()
    monkeypatch.setenv("TG_CHAT_ID", "-100777")  # чат уже занят вторым проектом
    get_settings.cache_clear()
    projects.ensure_default_project(db)
    assert project.tg_chat_id is None  # Один чат нельзя привязать к двум проектам
    project.tg_chat_id = -100111
    monkeypatch.setenv("TG_CHAT_ID", "-100222")
    get_settings.cache_clear()
    projects.ensure_default_project(db)
    assert project.tg_chat_id == -100111  # уже заданный чат не подменяется


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("The Brass Spyglass", "the-brass-spyglass"),
        ("  Hello, World!  ", "hello-world"),
        ("Битва при кривом зеркале", "project"),  # нет латиницы — запасное имя
        ("", "project"),
    ],
)
def test_slugify(title, slug):
    assert projects.slugify(title) == slug


def test_unique_slug_adds_a_number_when_taken(db):
    projects.ensure_default_project(db)
    assert projects.unique_slug(db, "brass-spyglass") == "brass-spyglass-2"
    assert projects.unique_slug(db, "free") == "free"


def test_a_new_member_is_team_and_a_superadmin_is_owner(db):
    project = projects.ensure_default_project(db)
    plain = users.upsert_from_telegram(
        db, tg_id=501, username=None, name="Лена", avatar_path=None, owner_tg_id=None
    )
    boss = users.upsert_from_telegram(
        db, tg_id=502, username=None, name="Босс", avatar_path=None, owner_tg_id=None
    )
    assert members.get(db, project.id, plain.id).role == Role.TEAM.value
    # суперадмин из списка в переменной окружения становится владельцем проекта при вступлении
    got = members.ensure(db, project, boss, settings=settings(superadmin_tg_ids="502, 999"))
    assert got.role == Role.TEAM.value  # запись уже есть: роль не перезаписывается молча
    other = models.Project(**{**projects.DEFAULT_PROJECT, "slug": "second"})
    db.add(other)
    db.flush()
    assert (
        members.ensure(db, other, boss, settings=settings(superadmin_tg_ids="502")).role
        == Role.OWNER.value
    )


def test_login_creates_a_member_of_the_project_with_the_users_color(db):
    project = projects.ensure_default_project(db)
    user = users.upsert_from_telegram(
        db, tg_id=601, username="u", name="Игорь", avatar_path=None, owner_tg_id=None
    )
    member = members.get(db, project.id, user.id)
    assert member is not None and member.active and member.color == user.color
    again = users.upsert_from_telegram(
        db, tg_id=601, username="u", name="Игорь", avatar_path=None, owner_tg_id=None
    )
    assert again.id == user.id
    count = db.query(models.ProjectMember).filter_by(user_id=user.id).count()
    assert count == 1  # повторный вход не плодит записи


def test_leaving_keeps_the_record_and_rejoining_restores_the_role(db):
    project = projects.ensure_default_project(db)
    user = users.upsert_from_telegram(
        db, tg_id=701, username=None, name="Мария", avatar_path=None, owner_tg_id=None
    )
    member = members.ensure(db, project, user, role=Role.DIRECTOR)
    members.leave(db, member)
    assert member.active is False and member.left_at is not None
    assert members.active_project_ids(db, user.id) == []
    back = members.ensure(db, project, user)  # вступила снова, роль не просили
    assert back.id == member.id and back.active and back.role == Role.DIRECTOR.value
    assert members.active_project_ids(db, user.id) == [project.id]


def test_superadmin_list_comes_from_the_environment():
    s = settings(owner_tg_id=1, superadmin_tg_ids="2; 3,,x,-4")
    assert s.superadmins == {1, 2, 3, -4}
    assert s.is_superadmin(2) and not s.is_superadmin(5) and not s.is_superadmin(None)
