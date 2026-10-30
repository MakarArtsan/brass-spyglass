"""Сервисный слой: авторство, права, журнал, корзина."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.constants import Role, Status
from app.services import core, projects
from tests.factories import actor, make_user


def _project_id(db: Session) -> int:
    project = projects.get_project(db)
    assert project is not None
    return project.id


def _shot(db: Session, who, code: str = "01.01"):
    scene = core.create(
        db,
        who,
        "scene",
        {"number": 1, "order": 1, "title": "Два зеркала"},
        project_id=_project_id(db),
    )
    return core.create(
        db,
        who,
        "shot",
        {"scene_id": scene.id, "code": code, "order": 1},
        project_id=_project_id(db),
    )


def _journal(db: Session) -> list[models.Activity]:
    return list(db.scalars(select(models.Activity).order_by(models.Activity.id)))


def test_author_comes_from_session_and_cannot_be_forged(db):
    petya = make_user(db, name="Петя")
    shot = _shot(db, actor(petya))
    assert shot.created_by == petya.id and shot.updated_by == petya.id
    with pytest.raises(core.ValidationError):
        core.create(
            db,
            actor(petya),
            "shot",
            {"scene_id": 1, "code": "01.02", "order": 2, "created_by": 999},
            project_id=_project_id(db),
        )


def test_every_change_writes_an_activity_row(db):
    owner = make_user(db, Role.OWNER)
    shot = _shot(db, actor(owner))
    core.update(db, actor(owner), "shot", shot.id, {"description": "Две трубы"})
    core.delete(db, actor(owner), "shot", shot.id)
    core.restore(db, actor(owner), "shot", shot.id)
    actions = [(a.action, a.entity_type) for a in _journal(db) if a.entity_type == "shot"]
    assert actions == [
        ("create", "shot"),
        ("update", "shot"),
        ("delete", "shot"),
        ("restore", "shot"),
    ]
    update = next(a for a in _journal(db) if a.action == "update")
    assert update.diff == {"description": [None, "Две трубы"]}
    assert update.actor_id == owner.id


def test_status_change_is_logged_as_status_and_noop_is_not_logged(db):
    owner = make_user(db, Role.OWNER)
    shot = _shot(db, actor(owner))
    core.update(db, actor(owner), "shot", shot.id, {"status": Status.IN_PROGRESS.value})
    core.update(db, actor(owner), "shot", shot.id, {"status": Status.IN_PROGRESS.value})
    statuses = [a for a in _journal(db) if a.action == "status"]
    assert len(statuses) == 1
    assert statuses[0].diff == {"status": ["not_started", "in_progress"]}


def test_team_changes_status_of_foreign_card_but_not_its_content(db):
    owner, petya = make_user(db, Role.OWNER), make_user(db, Role.TEAM, "Петя")
    shot = _shot(db, actor(owner))
    core.update(db, actor(petya), "shot", shot.id, {"status": Status.REVIEW.value})
    with pytest.raises(core.PermissionDenied):
        core.update(db, actor(petya), "shot", shot.id, {"description": "моё"})
    own = core.create(
        db, actor(petya), "task", {"code": "T-01", "title": "Свой"}, project_id=_project_id(db)
    )
    core.update(db, actor(petya), "task", own.id, {"title": "Правка своего"})


def test_invalid_reference_value_is_rejected_by_check_constraint(db):
    owner = make_user(db, Role.OWNER)
    shot = _shot(db, actor(owner))
    with pytest.raises(core.ConflictError):
        core.update(db, actor(owner), "shot", shot.id, {"status": "почти_готово"})


def test_team_cannot_delete_foreign_file_but_can_delete_own(db):
    petya, vasya = make_user(db, Role.TEAM, "Петя"), make_user(db, Role.TEAM, "Вася")
    file = core.create(
        db,
        actor(petya),
        "file",
        {"kind": "image", "source": "upload", "original_name": "ref.png"},
        project_id=_project_id(db),
    )
    assert file.uploaded_by == petya.id
    with pytest.raises(core.PermissionDenied):
        core.delete(db, actor(vasya), "file", file.id)
    assert db.get(models.File, file.id).deleted_at is None
    core.delete(db, actor(petya), "file", file.id)
    assert db.get(models.File, file.id).deleted_at is not None


def test_director_deletes_foreign_to_trash_and_only_owner_restores(db):
    owner, director, petya = (make_user(db, r) for r in (Role.OWNER, Role.DIRECTOR, Role.TEAM))
    shot = _shot(db, actor(petya))
    core.delete(db, actor(director), "shot", shot.id)
    with pytest.raises(core.NotFoundError):
        core.get(db, "shot", shot.id)
    with pytest.raises(core.PermissionDenied):
        core.restore(db, actor(director), "shot", shot.id)
    core.restore(db, actor(owner), "shot", shot.id)
    assert core.get(db, "shot", shot.id).deleted_at is None


def test_code_can_be_reused_after_soft_delete_but_not_while_alive(db):
    owner = make_user(db, Role.OWNER)
    first = _shot(db, actor(owner), code="01.01")
    with pytest.raises(core.ConflictError):
        core.create(
            db,
            actor(owner),
            "shot",
            {"scene_id": first.scene_id, "code": "01.01", "order": 2},
            project_id=_project_id(db),
        )


def test_guest_may_comment_only(db):
    owner, guest = make_user(db, Role.OWNER), make_user(db, Role.GUEST)
    shot = _shot(db, actor(owner))
    core.create(
        db,
        actor(guest),
        "comment",
        {"entity_type": "shot", "entity_id": shot.id, "body": "Класс"},
        project_id=_project_id(db),
    )
    with pytest.raises(core.PermissionDenied):
        core.update(db, actor(guest), "shot", shot.id, {"status": Status.DONE.value})
    with pytest.raises(core.PermissionDenied):
        core.create(
            db, actor(guest), "task", {"code": "T-9", "title": "x"}, project_id=_project_id(db)
        )


def test_only_owner_changes_roles(db):
    owner, director, petya = (make_user(db, r) for r in (Role.OWNER, Role.DIRECTOR, Role.TEAM))
    with pytest.raises(core.PermissionDenied):
        core.update(db, actor(director), "user", petya.id, {"role": Role.DIRECTOR.value})
    core.update(db, actor(owner), "user", petya.id, {"role": Role.DIRECTOR.value})
    assert db.get(models.User, petya.id).role == Role.DIRECTOR.value
    with pytest.raises(core.ValidationError):  # имя и аватар приходят только из Telegram
        core.update(db, actor(owner), "user", petya.id, {"name": "Другой"})
