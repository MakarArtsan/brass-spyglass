"""Превращает записи БД в ответы API. Списки собираются несколькими запросами на всю
выборку (без N+1), поэтому шот-лист из 69 строк отдаётся быстро."""

from collections import defaultdict
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app import metrics, models
from app.constants import EntityType
from app.signing import file_url

DROP = ("deleted_at",)
# Что показывать превью карточки: финал, потом дубль, потом референс.
PREVIEW_RANK = {"final": 0, "take": 1, "reference": 2}


def column_dict(obj: Any, drop: tuple[str, ...] = DROP) -> dict[str, Any]:
    return {
        a.key: getattr(obj, a.key) for a in inspect(obj).mapper.column_attrs if a.key not in drop
    }


def previews(db: Session, entity_type: str, ids: list[int]) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}
    rows = db.execute(
        select(
            models.Attachment.entity_id, models.Attachment.purpose, models.File.id, models.File.kind
        )
        .join(models.File, models.File.id == models.Attachment.file_id)
        .where(
            models.Attachment.entity_type == entity_type,
            models.Attachment.entity_id.in_(ids),
            models.File.deleted_at.is_(None),
            models.File.thumb_path.is_not(None),
        )
        .order_by(models.Attachment.id)
    )
    best: dict[int, tuple[int, int, str]] = {}
    for entity_id, purpose, file_id, kind in rows:
        rank = PREVIEW_RANK.get(purpose, 3)
        current = best.get(entity_id)
        # при равенстве у дублей побеждает последний, у остальных — первый
        if current is None or rank < current[0] or (rank == current[0] == 1):
            best[entity_id] = (rank, file_id, kind)
    return {
        entity_id: {"file_id": fid, "kind": kind, "url": file_url(fid, "thumb")}
        for entity_id, (_, fid, kind) in best.items()
    }


def file_counts(db: Session, entity_type: str, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = db.execute(
        select(models.Attachment.entity_id, func.count())
        .join(models.File, models.File.id == models.Attachment.file_id)
        .where(
            models.Attachment.entity_type == entity_type,
            models.Attachment.entity_id.in_(ids),
            models.File.deleted_at.is_(None),
        )
        .group_by(models.Attachment.entity_id)
    )
    return dict(rows.all())


def scenes_out(db: Session, project_id: int, scenes: list[models.Scene]) -> list[dict[str, Any]]:
    stats = metrics.project_scene_stats(db, project_id)
    shown = previews(db, EntityType.SCENE, [s.id for s in scenes])
    out = []
    for scene in scenes:
        stat = stats.get(scene.id)
        item = column_dict(scene)
        if stat:
            item.update(
                start_sec=stat.start_sec,
                end_sec=stat.end_sec,
                shots_count=stat.shots_count,
                shots_sec=stat.shots_sec,
                delta_sec=stat.delta_sec,
                done_shots=stat.done_shots,
                ready_pct=stat.ready_pct,
            )
        item["preview"] = shown.get(scene.id)
        out.append(item)
    return out


def shots_out(db: Session, shots: list[models.Shot]) -> list[dict[str, Any]]:
    if not shots:
        return []
    ids = [s.id for s in shots]
    scene_numbers = dict(
        db.execute(
            select(models.Scene.id, models.Scene.number).where(
                models.Scene.id.in_({s.scene_id for s in shots})
            )
        ).all()
    )
    links: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for shot_id, asset_id, code, name, type_, state_id, state_name in db.execute(
        select(
            models.ShotAsset.shot_id,
            models.Asset.id,
            models.Asset.code,
            models.Asset.name,
            models.Asset.type,
            models.AssetState.id,
            models.AssetState.name,
        )
        .join(models.Asset, models.Asset.id == models.ShotAsset.asset_id)
        .outerjoin(models.AssetState, models.AssetState.id == models.ShotAsset.asset_state_id)
        .where(models.ShotAsset.shot_id.in_(ids))
        .order_by(models.ShotAsset.id)
    ):
        links[shot_id].append(
            {
                "asset_id": asset_id,
                "code": code,
                "name": name,
                "type": type_,
                "state_id": state_id,
                "state_name": state_name,
            }
        )
    shown = previews(db, EntityType.SHOT, ids)
    counts = file_counts(db, EntityType.SHOT, ids)
    out = []
    for shot in shots:
        item = column_dict(shot)
        item["scene_number"] = scene_numbers.get(shot.scene_id)
        item["assets"] = links.get(shot.id, [])
        item["files_count"] = counts.get(shot.id, 0)
        item["preview"] = shown.get(shot.id)
        out.append(item)
    return out


def assets_out(db: Session, assets: list[models.Asset]) -> list[dict[str, Any]]:
    if not assets:
        return []
    ids = [a.id for a in assets]
    states: dict[int, list[models.AssetState]] = defaultdict(list)
    for state in db.scalars(
        select(models.AssetState)
        .where(models.AssetState.asset_id.in_(ids), models.AssetState.deleted_at.is_(None))
        .order_by(models.AssetState.order, models.AssetState.id)
    ):
        states[state.asset_id].append(state)
    state_ids = [s.id for group in states.values() for s in group]
    state_files = file_counts(db, EntityType.ASSET_STATE, state_ids)
    state_previews = previews(db, EntityType.ASSET_STATE, state_ids)
    shots_in = dict(
        db.execute(
            select(models.ShotAsset.asset_id, func.count(func.distinct(models.ShotAsset.shot_id)))
            .join(models.Shot, models.Shot.id == models.ShotAsset.shot_id)
            .where(models.ShotAsset.asset_id.in_(ids), models.Shot.deleted_at.is_(None))
            .group_by(models.ShotAsset.asset_id)
        ).all()
    )
    shown = previews(db, EntityType.ASSET, ids)
    counts = file_counts(db, EntityType.ASSET, ids)
    out = []
    for asset in assets:
        item = column_dict(asset)
        item["states"] = [
            {
                **column_dict(s, drop=("deleted_at", "created_at", "updated_at")),
                "files_count": state_files.get(s.id, 0),
                "preview": state_previews.get(s.id),
            }
            for s in states.get(asset.id, [])
        ]
        item["shots_count"] = shots_in.get(asset.id, 0)
        item["files_count"] = counts.get(asset.id, 0)
        item["preview"] = shown.get(asset.id)
        out.append(item)
    return out


def setups_out(db: Session, setups: list[models.SetupPayoff]) -> list[dict[str, Any]]:
    wanted = {i for s in setups for i in (*s.setup_shot_ids, *s.payoff_shot_ids)}
    codes = (
        dict(
            db.execute(
                select(models.Shot.id, models.Shot.code).where(models.Shot.id.in_(wanted))
            ).all()
        )
        if wanted
        else {}
    )

    def refs(ids: list[int]) -> list[dict[str, Any]]:
        return [{"id": i, "code": codes[i]} for i in ids if i in codes]

    out = []
    for setup in setups:
        item = column_dict(setup)
        item["setup_shots"] = refs(setup.setup_shot_ids)
        item["payoff_shots"] = refs(setup.payoff_shot_ids)
        out.append(item)
    return out


def sounds_out(db: Session, cues: list[models.SoundCue]) -> list[dict[str, Any]]:
    scene_ids = {c.scene_id for c in cues if c.scene_id}
    shot_ids = {c.shot_id for c in cues if c.shot_id}
    scenes = (
        dict(
            db.execute(
                select(models.Scene.id, models.Scene.number).where(models.Scene.id.in_(scene_ids))
            ).all()
        )
        if scene_ids
        else {}
    )
    shots = (
        dict(
            db.execute(
                select(models.Shot.id, models.Shot.code).where(models.Shot.id.in_(shot_ids))
            ).all()
        )
        if shot_ids
        else {}
    )
    out = []
    for cue in cues:
        item = column_dict(cue)
        item["scene_number"] = scenes.get(cue.scene_id)
        item["shot_code"] = shots.get(cue.shot_id)
        out.append(item)
    return out


def tasks_out(tasks: list[models.Task]) -> list[dict[str, Any]]:
    return [column_dict(t) for t in tasks]


def author(user: models.User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "name": user.name,
        "color": user.color,
        "has_avatar": bool(user.avatar_path),
    }


def authors(db: Session, ids: set[int | None]) -> dict[int, dict[str, Any]]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return {
        u.id: author(u) or {}
        for u in db.scalars(select(models.User).where(models.User.id.in_(wanted)))
    }


def entity_labels(db: Session, pairs: set[tuple[str, int | None]]) -> dict[tuple[str, int], str]:
    """Короткая подпись сущности для журнала: «шот 01.03», «ассет CH-01» …"""
    by_type: dict[str, set[int]] = defaultdict(set)
    for entity_type, entity_id in pairs:
        if entity_id is not None:
            by_type[entity_type].add(entity_id)
    out: dict[tuple[str, int], str] = {}

    def fill(entity_type: str, model: Any, fmt: Any) -> None:
        ids = by_type.get(entity_type)
        if not ids:
            return
        for row in db.scalars(select(model).where(model.id.in_(ids))):
            out[(entity_type, row.id)] = fmt(row)

    fill(EntityType.SCENE, models.Scene, lambda r: f"сцена {r.number} «{r.title}»")
    fill(EntityType.SHOT, models.Shot, lambda r: f"шот {r.code}")
    fill(EntityType.ASSET, models.Asset, lambda r: f"ассет {r.code}")
    fill(EntityType.ASSET_STATE, models.AssetState, lambda r: f"состояние «{r.name}»")
    fill(EntityType.SETUP_PAYOFF, models.SetupPayoff, lambda r: f"сетап {r.number}")
    fill(EntityType.SOUND_CUE, models.SoundCue, lambda r: f"звук {r.code}")
    fill(EntityType.TASK, models.Task, lambda r: f"задача {r.code}")
    fill(EntityType.FILE, models.File, lambda r: f"файл {r.original_name or r.id}")
    fill(EntityType.USER, models.User, lambda r: f"участник {r.name}")
    return out
