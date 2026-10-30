"""Сцены, шоты, ассеты, сетапы, звук, задачи, комментарии и журнал.

Все записи идут через app/services (права и журнал — там). Здесь — разбор запросов,
сборка ответов и никакой логики доступа.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, create_model
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    func,
    select,
)
from sqlalchemy.orm import Session

from app import constants as c
from app import models, permissions
from app.api import serialize
from app.auth import session
from app.db import get_db
from app.permissions import Actor
from app.services import core, links, ordering, projects

router = APIRouter(dependencies=[Depends(session.same_origin)])

DbDep = Annotated[Session, Depends(get_db)]
ActorDep = Annotated[Actor, Depends(session.actor_of)]
UserDep = Annotated[models.User, Depends(session.current_user)]

ET = c.EntityType

# --- входные модели из белых списков сервисного слоя ----------------------------------------------

WORK_ENUMS = {"status": c.Status, "priority": c.Priority}
FIELD_ENUMS: dict[tuple[str, str], type] = {
    (ET.SCENE, "side"): c.Side,
    (ET.SHOT, "size"): c.ShotSize,
    (ET.SHOT, "tool"): c.Tool,
    (ET.SHOT, "stage"): c.Stage,
    (ET.SHOT, "side"): c.Side,
    (ET.ASSET, "type"): c.AssetType,
    (ET.ASSET, "side"): c.Side,
    (ET.SOUND_CUE, "type"): c.SoundType,
    (ET.TASK, "block"): c.TaskBlock,
    (ET.USER, "role"): c.Role,
}
COMMENTABLE = (
    ET.SCENE,
    ET.SHOT,
    ET.ASSET,
    ET.ASSET_STATE,
    ET.SETUP_PAYOFF,
    ET.SOUND_CUE,
    ET.TASK,
    ET.FILE,
)
REQUIRED_ON_CREATE = {
    ET.SCENE: ("number", "title"),
    ET.SHOT: ("scene_id", "code"),
    ET.ASSET: ("code", "name", "type"),
    ET.ASSET_STATE: ("asset_id", "name"),
    ET.SETUP_PAYOFF: ("motif",),
    ET.SOUND_CUE: ("code", "type"),
    ET.TASK: ("code", "title"),
    ET.COMMENT: ("entity_type", "entity_id", "body"),
}


def _python_type(entity_type: str, name: str, column: Any) -> tuple[Any, dict[str, Any]]:
    extra: dict[str, Any] = {}
    enum_cls = FIELD_ENUMS.get((entity_type, name)) or WORK_ENUMS.get(name)
    if entity_type == ET.COMMENT and name == "entity_type":
        return Literal[COMMENTABLE], extra  # type: ignore[return-value]
    if enum_cls is not None:
        return Literal[c.values(enum_cls)], extra  # type: ignore[valid-type]
    kind = column.type
    if name == "drum_level":
        extra.update(ge=c.DRUM_LEVEL_RANGE[0], le=c.DRUM_LEVEL_RANGE[1])
        return int, extra
    if isinstance(kind, JSON):
        return list[int], extra
    if isinstance(kind, Boolean):
        return bool, extra
    if isinstance(kind, Integer | BigInteger):
        return int, extra
    if isinstance(kind, Float):
        extra.update(ge=0) if name in {"planned_sec", "duration_sec"} else None
        return float, extra
    if isinstance(kind, Date):
        return date, extra
    if isinstance(kind, DateTime):
        return datetime, extra
    if isinstance(kind, String) and kind.length:
        extra["max_length"] = kind.length
    return str, extra


def input_model(entity_type: str, *, create: bool) -> type[BaseModel]:
    spec = core.ENTITIES[entity_type]
    names = spec.fields | (spec.create_only if create else frozenset())
    fields: dict[str, Any] = {}
    for name in sorted(names):
        column = spec.model.__table__.columns[name]  # type: ignore[attr-defined]
        py, extra = _python_type(entity_type, name, column)
        fields[name] = (py | None, Field(default=None, **extra))
    return create_model(
        f"{entity_type}_{'create' if create else 'update'}",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def _body(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_unset=True)


def _require(entity_type: str, data: dict[str, Any]) -> None:
    missing = [f for f in REQUIRED_ON_CREATE.get(entity_type, ()) if data.get(f) is None]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Не заполнено: {', '.join(missing)}"
        )


def _project_id(db: Session) -> int:
    project = projects.get_project(db)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не создан")
    return project.id


def _next_order(db: Session, entity_type: str, data: dict[str, Any], project_id: int) -> int:
    if entity_type == ET.SCENE:
        stmt = select(func.max(models.Scene.order)).where(models.Scene.project_id == project_id)
    elif entity_type == ET.SHOT:
        stmt = select(func.max(models.Shot.order)).where(models.Shot.scene_id == data["scene_id"])
    else:
        stmt = select(func.max(models.AssetState.order)).where(
            models.AssetState.asset_id == data["asset_id"]
        )
    return (db.scalar(stmt) or 0) + 1


# --- справочники ---------------------------------------------------------------------------------


@router.get("/meta")
def meta(_: UserDep) -> dict[str, list[str]]:
    """Допустимые значения справочников (слаги). Тексты — в ru.ts."""
    return {
        "status": list(c.values(c.Status)),
        "priority": list(c.values(c.Priority)),
        "stage": list(c.values(c.Stage)),
        "size": list(c.values(c.ShotSize)),
        "tool": list(c.values(c.Tool)),
        "asset_type": list(c.values(c.AssetType)),
        "sound_type": list(c.values(c.SoundType)),
        "task_block": list(c.values(c.TaskBlock)),
        "purpose": list(c.values(c.Purpose)),
        "side": list(c.values(c.Side)),
        "role": list(c.values(c.Role)),
    }


# --- сцены ---------------------------------------------------------------------------------------

SceneCreate = input_model(ET.SCENE, create=True)
SceneUpdate = input_model(ET.SCENE, create=False)


def _alive(model: Any, project_id: int) -> Any:
    return select(model).where(model.project_id == project_id, model.deleted_at.is_(None))


@router.get("/scenes")
def list_scenes(db: DbDep, _: UserDep) -> list[dict[str, Any]]:
    pid = _project_id(db)
    rows = db.scalars(_alive(models.Scene, pid).order_by(models.Scene.order, models.Scene.id)).all()
    return serialize.scenes_out(db, pid, list(rows))


def _scene_one(db: Session, scene: models.Scene) -> dict[str, Any]:
    return serialize.scenes_out(db, scene.project_id, [scene])[0]


@router.post("/scenes", status_code=status.HTTP_201_CREATED)
def create_scene(body: SceneCreate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    data = _body(body)
    _require(ET.SCENE, data)
    pid = _project_id(db)
    data.setdefault("order", _next_order(db, ET.SCENE, data, pid))
    scene = core.create(db, actor, ET.SCENE, data, project_id=pid)
    return _scene_one(db, scene)


@router.patch("/scenes/{scene_id}")
def update_scene(scene_id: int, body: SceneUpdate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    scene = core.update(db, actor, ET.SCENE, scene_id, _body(body))
    return _scene_one(db, scene)


@router.delete("/scenes/{scene_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scene(scene_id: int, db: DbDep, actor: ActorDep) -> None:
    core.delete(db, actor, ET.SCENE, scene_id)


# --- шоты ----------------------------------------------------------------------------------------

ShotCreate = input_model(ET.SHOT, create=True)
ShotUpdate = input_model(ET.SHOT, create=False)


@router.get("/shots")
def list_shots(db: DbDep, _: UserDep, scene_id: int | None = None) -> list[dict[str, Any]]:
    pid = _project_id(db)
    stmt = (
        select(models.Shot)
        .join(models.Scene, models.Scene.id == models.Shot.scene_id)
        .where(
            models.Shot.project_id == pid,
            models.Shot.deleted_at.is_(None),
            models.Scene.deleted_at.is_(None),
        )
        .order_by(models.Scene.order, models.Scene.id, models.Shot.order, models.Shot.id)
    )
    if scene_id is not None:
        stmt = stmt.where(models.Shot.scene_id == scene_id)
    return serialize.shots_out(db, list(db.scalars(stmt)))


@router.get("/shots/{shot_id}")
def get_shot(shot_id: int, db: DbDep, _: UserDep) -> dict[str, Any]:
    shot = core.get(db, ET.SHOT, shot_id)
    item = serialize.shots_out(db, [shot])[0]  # type: ignore[list-item]
    scene = db.get(models.Scene, shot.scene_id)  # type: ignore[attr-defined]
    item["scene"] = (
        {"id": scene.id, "number": scene.number, "title": scene.title} if scene else None
    )
    cues = db.scalars(
        select(models.SoundCue)
        .where(models.SoundCue.shot_id == shot_id, models.SoundCue.deleted_at.is_(None))
        .order_by(models.SoundCue.code)
    )
    item["sound"] = serialize.sounds_out(db, list(cues))
    item["setups"] = [
        {"id": s.id, "number": s.number, "motif": s.motif, "role": role}
        for s in db.scalars(
            select(models.SetupPayoff)
            .where(models.SetupPayoff.deleted_at.is_(None))
            .order_by(models.SetupPayoff.number)
        )
        for role, ids in (("setup", s.setup_shot_ids), ("payoff", s.payoff_shot_ids))
        if shot_id in ids
    ]
    return item


@router.post("/shots", status_code=status.HTTP_201_CREATED)
def create_shot(body: ShotCreate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    data = _body(body)
    _require(ET.SHOT, data)
    pid = _project_id(db)
    data.setdefault("order", _next_order(db, ET.SHOT, data, pid))
    shot = core.create(db, actor, ET.SHOT, data, project_id=pid)
    return serialize.shots_out(db, [shot])[0]  # type: ignore[list-item]


@router.patch("/shots/{shot_id}")
def update_shot(shot_id: int, body: ShotUpdate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    shot = core.update(db, actor, ET.SHOT, shot_id, _body(body))
    return serialize.shots_out(db, [shot])[0]


@router.delete("/shots/{shot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shot(shot_id: int, db: DbDep, actor: ActorDep) -> None:
    core.delete(db, actor, ET.SHOT, shot_id)


class AssetLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_state_id: int | None = None


@router.put("/shots/{shot_id}/assets/{asset_id}")
def put_shot_asset(
    shot_id: int, asset_id: int, body: AssetLink, db: DbDep, actor: ActorDep
) -> dict[str, Any]:
    """Ассет в кадре шота и его состояние (континьюити)."""
    links.set_shot_asset(db, actor, shot_id, asset_id, body.asset_state_id)
    return serialize.shots_out(db, [core.get(db, ET.SHOT, shot_id)])[0]  # type: ignore[list-item]


@router.delete("/shots/{shot_id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shot_asset(shot_id: int, asset_id: int, db: DbDep, actor: ActorDep) -> None:
    links.remove_shot_asset(db, actor, shot_id, asset_id)


# --- ассеты и их состояния -----------------------------------------------------------------------

AssetCreate = input_model(ET.ASSET, create=True)
AssetUpdate = input_model(ET.ASSET, create=False)
StateCreate = input_model(ET.ASSET_STATE, create=True)
StateUpdate = input_model(ET.ASSET_STATE, create=False)


@router.get("/assets")
def list_assets(db: DbDep, _: UserDep) -> list[dict[str, Any]]:
    pid = _project_id(db)
    rows = db.scalars(_alive(models.Asset, pid).order_by(models.Asset.code))
    return serialize.assets_out(db, list(rows))


@router.get("/assets/{asset_id}")
def get_asset(asset_id: int, db: DbDep, _: UserDep) -> dict[str, Any]:
    asset = core.get(db, ET.ASSET, asset_id)
    item = serialize.assets_out(db, [asset])[0]  # type: ignore[list-item]
    shot_rows = db.execute(
        select(models.Shot.id, models.Shot.code, models.ShotAsset.asset_state_id)
        .join(models.ShotAsset, models.ShotAsset.shot_id == models.Shot.id)
        .join(models.Scene, models.Scene.id == models.Shot.scene_id)
        .where(models.ShotAsset.asset_id == asset_id, models.Shot.deleted_at.is_(None))
        .order_by(models.Scene.order, models.Shot.order)
    )
    item["shots"] = [{"id": i, "code": code, "state_id": state} for i, code, state in shot_rows]
    return item


@router.post("/assets", status_code=status.HTTP_201_CREATED)
def create_asset(body: AssetCreate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    data = _body(body)
    _require(ET.ASSET, data)
    asset = core.create(db, actor, ET.ASSET, data, project_id=_project_id(db))
    return serialize.assets_out(db, [asset])[0]  # type: ignore[list-item]


@router.patch("/assets/{asset_id}")
def update_asset(asset_id: int, body: AssetUpdate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    asset = core.update(db, actor, ET.ASSET, asset_id, _body(body))
    return serialize.assets_out(db, [asset])[0]


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: int, db: DbDep, actor: ActorDep) -> None:
    core.delete(db, actor, ET.ASSET, asset_id)


@router.post("/assets/{asset_id}/states", status_code=status.HTTP_201_CREATED)
def create_state(asset_id: int, body: StateCreate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    data = _body(body)
    data["asset_id"] = asset_id
    _require(ET.ASSET_STATE, data)
    asset = core.get(db, ET.ASSET, asset_id)
    data.setdefault("order", _next_order(db, ET.ASSET_STATE, data, 0))
    core.create(db, actor, ET.ASSET_STATE, data, project_id=asset.project_id)  # type: ignore[attr-defined]
    return serialize.assets_out(db, [asset])[0]  # type: ignore[list-item]


@router.patch("/asset-states/{state_id}")
def update_state(state_id: int, body: StateUpdate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    state = core.update(db, actor, ET.ASSET_STATE, state_id, _body(body))
    return serialize.assets_out(db, [core.get(db, ET.ASSET, state.asset_id)])[0]  # type: ignore[list-item]


@router.delete("/asset-states/{state_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_state(state_id: int, db: DbDep, actor: ActorDep) -> None:
    core.delete(db, actor, ET.ASSET_STATE, state_id)


# --- сетапы, звук, задачи ------------------------------------------------------------------------

SetupCreate = input_model(ET.SETUP_PAYOFF, create=True)
SetupUpdate = input_model(ET.SETUP_PAYOFF, create=False)
SoundCreate = input_model(ET.SOUND_CUE, create=True)
SoundUpdate = input_model(ET.SOUND_CUE, create=False)
TaskCreate = input_model(ET.TASK, create=True)
TaskUpdate = input_model(ET.TASK, create=False)


@router.get("/setups")
def list_setups(db: DbDep, _: UserDep) -> list[dict[str, Any]]:
    rows = db.scalars(
        _alive(models.SetupPayoff, _project_id(db)).order_by(
            models.SetupPayoff.number, models.SetupPayoff.id
        )
    )
    return serialize.setups_out(db, list(rows))


@router.post("/setups", status_code=status.HTTP_201_CREATED)
def create_setup(body: SetupCreate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    data = _body(body)
    _require(ET.SETUP_PAYOFF, data)
    pid = _project_id(db)
    if data.get("number") is None:
        data["number"] = (
            db.scalar(
                select(func.max(models.SetupPayoff.number)).where(
                    models.SetupPayoff.project_id == pid
                )
            )
            or 0
        ) + 1
    row = core.create(db, actor, ET.SETUP_PAYOFF, data, project_id=pid)
    return serialize.setups_out(db, [row])[0]  # type: ignore[list-item]


@router.patch("/setups/{setup_id}")
def update_setup(setup_id: int, body: SetupUpdate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    row = core.update(db, actor, ET.SETUP_PAYOFF, setup_id, _body(body))
    return serialize.setups_out(db, [row])[0]


@router.delete("/setups/{setup_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_setup(setup_id: int, db: DbDep, actor: ActorDep) -> None:
    core.delete(db, actor, ET.SETUP_PAYOFF, setup_id)


@router.get("/sound")
def list_sound(db: DbDep, _: UserDep) -> list[dict[str, Any]]:
    rows = db.scalars(_alive(models.SoundCue, _project_id(db)).order_by(models.SoundCue.code))
    return serialize.sounds_out(db, list(rows))


@router.post("/sound", status_code=status.HTTP_201_CREATED)
def create_sound(body: SoundCreate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    data = _body(body)
    _require(ET.SOUND_CUE, data)
    row = core.create(db, actor, ET.SOUND_CUE, data, project_id=_project_id(db))
    return serialize.sounds_out(db, [row])[0]  # type: ignore[list-item]


@router.patch("/sound/{cue_id}")
def update_sound(cue_id: int, body: SoundUpdate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    row = core.update(db, actor, ET.SOUND_CUE, cue_id, _body(body))
    return serialize.sounds_out(db, [row])[0]


@router.delete("/sound/{cue_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sound(cue_id: int, db: DbDep, actor: ActorDep) -> None:
    core.delete(db, actor, ET.SOUND_CUE, cue_id)


@router.get("/tasks")
def list_tasks(db: DbDep, _: UserDep) -> list[dict[str, Any]]:
    rows = db.scalars(_alive(models.Task, _project_id(db)).order_by(models.Task.code))
    return serialize.tasks_out(list(rows))


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_task(body: TaskCreate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    data = _body(body)
    _require(ET.TASK, data)
    row = core.create(db, actor, ET.TASK, data, project_id=_project_id(db))
    return serialize.tasks_out([row])[0]  # type: ignore[list-item]


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    row = core.update(db, actor, ET.TASK, task_id, _body(body))
    return serialize.tasks_out([row])[0]


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: DbDep, actor: ActorDep) -> None:
    core.delete(db, actor, ET.TASK, task_id)


# --- групповые операции --------------------------------------------------------------------------

STATUS_ENTITIES = Literal["scene", "shot", "asset", "setup_payoff", "sound_cue", "task"]


class BulkStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: STATUS_ENTITIES
    ids: list[int] = Field(min_length=1, max_length=500)
    status: Literal[c.values(c.Status)]  # type: ignore[valid-type]


@router.post("/bulk-status")
def bulk_status(body: BulkStatus, db: DbDep, actor: ActorDep) -> dict[str, int]:
    changed = core.bulk_status(db, actor, body.entity_type, body.ids, body.status)
    return {"updated": len(changed)}


class Reorder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: Literal["scene", "shot"]
    ids: list[int] = Field(min_length=1, max_length=1000)
    scene_id: int | None = None


@router.post("/reorder")
def reorder(body: Reorder, db: DbDep, actor: ActorDep) -> dict[str, int]:
    moved = ordering.reorder(
        db, actor, body.entity_type, body.ids, project_id=_project_id(db), scene_id=body.scene_id
    )
    return {"moved": moved}


# --- комментарии ---------------------------------------------------------------------------------

CommentCreate = input_model(ET.COMMENT, create=True)
CommentUpdate = input_model(ET.COMMENT, create=False)


def _comments_out(db: Session, rows: list[models.Comment]) -> list[dict[str, Any]]:
    people = serialize.authors(db, {r.created_by for r in rows})
    return [
        {**serialize.column_dict(r), "author": people.get(r.created_by) if r.created_by else None}
        for r in rows
    ]


@router.get("/comments")
def list_comments(
    db: DbDep,
    _: UserDep,
    entity_type: Annotated[str, Query()],
    entity_id: Annotated[int, Query()],
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(models.Comment)
        .where(
            models.Comment.entity_type == entity_type,
            models.Comment.entity_id == entity_id,
            models.Comment.deleted_at.is_(None),
        )
        .order_by(models.Comment.id)
    )
    return _comments_out(db, list(rows))


@router.post("/comments", status_code=status.HTTP_201_CREATED)
def create_comment(body: CommentCreate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    data = _body(body)
    _require(ET.COMMENT, data)
    core.get(db, data["entity_type"], data["entity_id"])  # комментировать можно только существующее
    row = core.create(db, actor, ET.COMMENT, data, project_id=_project_id(db))
    return _comments_out(db, [row])[0]  # type: ignore[list-item]


@router.patch("/comments/{comment_id}")
def update_comment(
    comment_id: int, body: CommentUpdate, db: DbDep, actor: ActorDep
) -> dict[str, Any]:  # type: ignore[valid-type]
    row = core.update(db, actor, ET.COMMENT, comment_id, _body(body))
    return _comments_out(db, [row])[0]


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: int, db: DbDep, actor: ActorDep) -> None:
    core.delete(db, actor, ET.COMMENT, comment_id)


# --- участники (роль меняет только владелец) -----------------------------------------------------

UserUpdate = input_model(ET.USER, create=False)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    user = core.update(db, actor, ET.USER, user_id, _body(body))
    return serialize.author(user) | {"role": user.role}  # type: ignore[operator]


# --- журнал --------------------------------------------------------------------------------------


@router.get("/activity")
def list_activity(
    db: DbDep,
    actor: ActorDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    actor_id: int | None = None,
) -> dict[str, Any]:
    """Журнал действий, новые сверху. Гостю не показывается."""
    permissions.require(permissions.can_view_journal(actor), "Журнал недоступен гостю")
    stmt = select(models.Activity).order_by(models.Activity.id.desc()).limit(limit + 1)
    if before_id is not None:
        stmt = stmt.where(models.Activity.id < before_id)
    if entity_type is not None:
        stmt = stmt.where(models.Activity.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(models.Activity.entity_id == entity_id)
    if actor_id is not None:
        stmt = stmt.where(models.Activity.actor_id == actor_id)
    rows = list(db.scalars(stmt))
    more = len(rows) > limit
    rows = rows[:limit]
    people = serialize.authors(db, {r.actor_id for r in rows})
    labels = serialize.entity_labels(db, {(r.entity_type, r.entity_id) for r in rows})
    items = [
        {
            "id": r.id,
            "at": r.at,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "label": labels.get((r.entity_type, r.entity_id)) if r.entity_id else None,
            "diff": r.diff,
            "actor": people.get(r.actor_id) if r.actor_id else None,
        }
        for r in rows
    ]
    return {"items": items, "next_before_id": rows[-1].id if more and rows else None}
