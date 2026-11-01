"""Превращает записи БД в ответы API. Списки собираются несколькими запросами на всю
выборку (без N+1), поэтому шот-лист из 69 строк отдаётся быстро."""

from collections import defaultdict
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app import metrics, models, tglinks
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
            models.File.is_current.is_(True),
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
            models.File.is_current.is_(True),
        )
        .group_by(models.Attachment.entity_id)
    )
    return dict(rows.all())


def final_info(file: models.File | None) -> dict[str, Any] | None:
    """Финальный файл карточки: текущая версия, ссылки для плеера и размеры для аниматика."""
    if file is None:
        return None
    urls = file_urls(file)
    return {
        "id": file.id,
        "original_name": file.original_name,
        "version_no": file.version_no,
        "duration_sec": file.duration_sec,
        "kind": file.kind,
        "processing": False,
        "urls": {k: v for k, v in urls.items() if k in ("original", "play", "poster", "thumb")},
    }


def scenes_out(db: Session, project_id: int, scenes: list[models.Scene]) -> list[dict[str, Any]]:
    from app.services import finals

    stats = metrics.project_scene_stats(db, project_id)
    shown = previews(db, EntityType.SCENE, [s.id for s in scenes])
    final_files = finals.resolve(db, scenes)
    out = []
    for scene in scenes:
        stat = stats.get(scene.id)
        item = column_dict(scene)
        item["final"] = final_info(final_files.get(scene.id))
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
    from app.services import finals

    shown = previews(db, EntityType.SHOT, ids)
    counts = file_counts(db, EntityType.SHOT, ids)
    final_files = finals.resolve(db, shots)
    out = []
    for shot in shots:
        item = column_dict(shot)
        item["final"] = final_info(final_files.get(shot.id))
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
    fill(EntityType.COMMENT, models.Comment, lambda r: "комментарий")
    return out


# --- файлы -----------------------------------------------------------------------------------


def file_urls(file: models.File) -> dict[str, str]:
    """Подписанные ссылки на то, что у файла уже готово (превью появляются после обработки)."""
    urls = {"original": file_url(file.id, "original")}
    ready = bool(file.thumb_path)
    if ready:
        urls["thumb"] = file_url(file.id, "thumb")
    if file.kind == "video":
        if ready:
            urls["poster"] = file_url(file.id, "poster")
        urls["play"] = file_url(file.id, "proxy" if file.proxy_path else "original")
    elif file.kind == "image" and ready:
        urls["preview"] = file_url(file.id, "preview")
    elif file.kind == "audio":
        urls["play"] = urls["original"]
        if file.waveform_json:
            urls["waveform"] = file_url(file.id, "waveform")
    elif file.kind == "document" and ready:
        urls["preview"] = file_url(file.id, "preview")
    return urls


def _topic_titles(db: Session, files: list[models.File]) -> dict[tuple[int, int], str]:
    pairs = {(f.tg_chat_id, f.tg_topic_id) for f in files if f.tg_chat_id and f.tg_topic_id}
    if not pairs:
        return {}
    rows = db.execute(
        select(models.TgTopic.chat_id, models.TgTopic.topic_id, models.TgTopic.title).where(
            models.TgTopic.chat_id.in_({chat for chat, _ in pairs})
        )
    )
    return {(chat, topic): title for chat, topic, title in rows if (chat, topic) in pairs}


def _tg_info(f: models.File, titles: dict[tuple[int, int], str]) -> dict[str, Any] | None:
    """Откуда файл из Telegram: тема, автор сообщения в чате и ссылка «Открыть в Telegram»."""
    if f.tg_message_id is None:
        return None
    return {
        "topic_id": f.tg_topic_id,
        "topic_title": titles.get((f.tg_chat_id or 0, f.tg_topic_id or 0)),
        "message_id": f.tg_message_id,
        "author": f.tg_author,
        "url": tglinks.message_url(f.tg_chat_id, f.tg_topic_id, f.tg_message_id),
    }


def files_out(db: Session, files: list[models.File]) -> list[dict[str, Any]]:
    from app.services import jobs

    active, failed = jobs.file_activity(db, [f.id for f in files])
    uploaders = authors(db, {f.uploaded_by for f in files})
    topic_titles = _topic_titles(db, files)
    from app.services import versions

    version_counts = versions.counts(db, files)
    out = []
    for f in files:
        out.append(
            {
                "id": f.id,
                "version_group_id": f.version_group_id,
                "version_no": f.version_no,
                "is_current": f.is_current,
                "versions_count": version_counts.get(f.version_group_id or 0, 1),
                "kind": f.kind,
                "source": f.source,
                "original_name": f.original_name,
                "mime": f.mime,
                "size_bytes": f.size_bytes,
                "sha256": f.sha256,
                "duration_sec": f.duration_sec,
                "width": f.width,
                "height": f.height,
                "fps": f.fps,
                "ai_tool": f.ai_tool,
                "ai_prompt": f.ai_prompt,
                "ai_seed": f.ai_seed,
                "url": f.url,
                "link_title": f.link_title,
                "tg": _tg_info(f, topic_titles),
                "uploaded_at": f.uploaded_at,
                "uploaded_by": uploaders.get(f.uploaded_by) if f.uploaded_by else None,
                "processing": f.id in active,
                "error": failed.get(f.id),
                "urls": file_urls(f),
            }
        )
    return out
