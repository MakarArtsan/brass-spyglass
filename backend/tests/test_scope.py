"""Изоляция проектов на уровне ORM: чужое не читается, не меняется и не пишется."""

import pytest
from sqlalchemy import delete, func, select, update

from app import models, scope
from app.services import projects


@pytest.fixture
def two(db):
    """Два проекта со сценой и шотом в каждом."""
    first = projects.ensure_default_project(db)
    db.info.pop(
        scope.PROJECT_ID, None
    )  # фикстура `db` уже внутри проекта фильма; здесь нужна «система»
    second = models.Project(**{**projects.DEFAULT_PROJECT, "slug": "second", "title": "Второй"})
    db.add(second)
    db.flush()
    out = {}
    for project in (first, second):
        scene = models.Scene(project_id=project.id, number=1, order=1, title="S", planned_sec=10)
        db.add(scene)
        db.flush()
        shot = models.Shot(project_id=project.id, scene_id=scene.id, code="01.01", order=1)
        db.add(shot)
        db.flush()
        out[project.slug] = (project.id, scene.id, shot.id)
    db.commit()
    return out


def open_as(db, slug, two):
    db.expire_all()
    db.info.pop(scope.PROJECT_ID, None)
    scope.select_project(db, two[slug][0], slug)


def test_selects_see_only_the_selected_project(db, two):
    open_as(db, "brass-spyglass", two)
    assert [s.project_id for s in db.scalars(select(models.Shot))] == [two["brass-spyglass"][0]]
    assert db.scalar(select(func.count()).select_from(models.Scene)) == 1
    open_as(db, "second", two)
    assert [s.project_id for s in db.scalars(select(models.Shot))] == [two["second"][0]]


def test_loading_by_id_does_not_cross_projects(db, two):
    open_as(db, "brass-spyglass", two)
    foreign_shot, foreign_scene = two["second"][2], two["second"][1]
    assert db.get(models.Shot, foreign_shot) is None
    assert db.get(models.Scene, foreign_scene) is None
    assert db.get(models.Shot, two["brass-spyglass"][2]) is not None


def test_bulk_update_and_delete_touch_only_the_selected_project(db, two):
    open_as(db, "brass-spyglass", two)
    db.execute(update(models.Shot).values(comment="X"))
    db.execute(delete(models.Scene).where(models.Scene.number == 99))
    db.commit()
    with scope.unscoped(db):
        rows = {s.project_id: s.comment for s in db.scalars(select(models.Shot))}
    assert rows == {two["brass-spyglass"][0]: "X", two["second"][0]: None}


def test_a_new_record_gets_the_project_of_the_session_and_a_foreign_one_is_refused(db, two):
    open_as(db, "second", two)
    task = models.Task(code="T-1", block="editing", title="t")  # проект не указан
    db.add(task)
    db.flush()
    assert task.project_id == two["second"][0]
    db.add(models.Task(project_id=two["brass-spyglass"][0], code="T-2", block="editing", title="x"))
    with pytest.raises(scope.ProjectScopeError):
        db.flush()
    db.rollback()


def test_moving_a_record_to_another_project_is_refused(db, two):
    open_as(db, "brass-spyglass", two)
    shot = db.get(models.Shot, two["brass-spyglass"][2])
    shot.project_id = two["second"][0]
    with pytest.raises(scope.ProjectScopeError):
        db.flush()
    db.rollback()


def test_an_api_session_without_a_project_cannot_read_project_data(db):
    projects.ensure_default_project(db)
    db.info.pop(scope.PROJECT_ID, None)
    db.info[scope.REQUIRE] = True
    with pytest.raises(scope.ProjectScopeError):
        db.scalars(select(models.Shot)).all()
    # данные не проектов (проект, участники, пользователи) доступны: по ним определяют доступ
    assert db.scalar(select(func.count()).select_from(models.Project)) == 1
    assert db.scalar(select(func.count()).select_from(models.ProjectMember)) == 0


def test_a_system_session_without_the_flag_is_not_limited(db, two):
    db.info.pop(scope.PROJECT_ID, None)
    # воркер и обслуживание: сессия без проекта и без метки видит всё и сама берёт проект из записи
    assert db.scalar(select(func.count()).select_from(models.Shot)) == 2


def test_unscoped_lifts_the_filter_inside_a_scoped_session_and_restores_it(db, two):
    open_as(db, "brass-spyglass", two)
    db.info[scope.REQUIRE] = True
    with scope.unscoped(db):
        assert db.scalar(select(func.count()).select_from(models.Shot)) == 2
    assert db.scalar(select(func.count()).select_from(models.Shot)) == 1
    assert db.info[scope.PROJECT_ID] == two["brass-spyglass"][0]


def test_joined_queries_are_filtered_on_every_scoped_table(db, two):
    open_as(db, "second", two)
    rows = db.execute(
        select(models.Shot.code, models.Scene.title).join(
            models.Scene, models.Scene.id == models.Shot.scene_id
        )
    ).all()
    assert len(rows) == 1
    # чужая сцена не подтянется и через соединение с условием, которое могло бы её совпасть
    foreign = two["brass-spyglass"][1]
    assert db.execute(select(models.Shot).where(models.Shot.scene_id == foreign)).all() == []
