"""Изоляция проектов на уровне ORM: чужие данные недоступны, даже если забыли отфильтровать.

Один проект = один закрытый чат. Человек не должен увидеть чужой проект, поэтому защита стоит не в
каждом запросе (их десятки, и один забытый фильтр — утечка), а в одном месте:

  * при каждом запросе к моделям с `project_id` сессия добавляет условие «этот проект»
    (`with_loader_criteria`); это и `select`, и загрузка по первичному ключу, и массовые
    `update`/`delete`;
  * перед сохранением проверяется, что запись принадлежит проекту сессии (`project_id` не заполнен —
    проставляется, чужой — ошибка);
  * сессия API без выбранного проекта, обратившаяся к таким моделям, — ошибка
    (`ProjectScopeError`), а не «пустой фильтр»: тест падает, утечки не будет.

Проект выбирает `access.project_access` (после проверки членства). Фоновые задачи и обслуживание
работают в системной сессии без проекта (без метки `require_project`) и сами берут проект из записи.
"""

import contextlib
from collections.abc import Iterator

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app import models

PROJECT_ID = "project_id"
PROJECT_SLUG = "project_slug"
REQUIRE = "require_project"

# Всё, что принадлежит проекту. Участники проекта и сам проект сюда не входят: по ним решают доступ.
SCOPED: tuple[type, ...] = (
    models.Scene,
    models.Shot,
    models.Asset,
    models.SetupPayoff,
    models.SoundCue,
    models.Task,
    models.File,
    models.Comment,
    models.Activity,
    models.ExportJob,
    models.Notification,
    models.ImportRun,
    models.Collage,
)
_SCOPED = frozenset(SCOPED)


class ProjectScopeError(Exception):
    """Запрос к данным проекта без выбранного проекта или запись в чужой проект."""


def select_project(db: Session, project_id: int, slug: str) -> None:
    db.info[PROJECT_ID] = project_id
    db.info[PROJECT_SLUG] = slug


def current_project_id(db: Session) -> int:
    pid = db.info.get(PROJECT_ID)
    if pid is None:
        raise ProjectScopeError("Проект не выбран")
    return int(pid)


@contextlib.contextmanager
def project_session(project_id: int) -> Iterator[Session]:
    """Сессия фоновой задачи, привязанная к проекту задачи: всё, что она делает (в том числе
    уведомления участникам), происходит внутри этого проекта."""
    from app import db as database

    with database.session_factory()() as db:
        project = db.get(models.Project, project_id)
        if project is None:
            raise ProjectScopeError(f"Проекта {project_id} нет")
        select_project(db, project.id, project.slug)
        yield db


@contextlib.contextmanager
def unscoped(db: Session) -> Iterator[None]:
    """Системное действие внутри запроса (например, поиск проектов человека): фильтр снят."""
    saved = {k: db.info.pop(k) for k in (PROJECT_ID, PROJECT_SLUG, REQUIRE) if k in db.info}
    try:
        yield
    finally:
        db.info.update(saved)


@event.listens_for(Session, "do_orm_execute")
def _limit_to_project(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    info = state.session.info
    pid = info.get(PROJECT_ID)
    if pid is None:
        if info.get(REQUIRE) and any(m.class_ in _SCOPED for m in state.all_mappers):
            raise ProjectScopeError("Запрос к данным проекта без выбранного проекта")
        return
    statement = state.statement
    for model in SCOPED:
        statement = statement.options(
            with_loader_criteria(model, model.project_id == pid, include_aliases=True)  # type: ignore[attr-defined]
        )
    state.statement = statement


@event.listens_for(Session, "before_flush")
def _keep_inside_project(session: Session, _ctx: object, _instances: object) -> None:
    pid = session.info.get(PROJECT_ID)
    if pid is None:
        return
    for obj in (*session.new, *session.dirty):
        if type(obj) not in _SCOPED:
            continue
        if obj.project_id is None:  # type: ignore[attr-defined]
            obj.project_id = pid  # type: ignore[attr-defined]
        elif obj.project_id != pid:  # type: ignore[attr-defined]
            raise ProjectScopeError(
                f"{type(obj).__name__}: запись проекта {obj.project_id} в сессии проекта {pid}"  # type: ignore[attr-defined]
            )
