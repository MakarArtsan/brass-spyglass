"""Применение Excel-пакета к БД (ТЗ, «Импорт Excel-трекера и сид-данные»).

Импорт идемпотентный: записи ищутся по коду (`01.03`, `CH-01`, `T-05`, номер сцены/сетапа),
повторный запуск обновляет их, а не плодит дубли; удалённая в корзину запись с тем же кодом
восстанавливается. Содержимое карточек обновляется всегда, а рабочие поля (статус, приоритет,
дедлайн, комментарий) и порядок существующих записей — только с `overwrite_work_fields=True`:
иначе повторный запуск стёр бы то, что команда уже поменяла на сайте.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.services.core import log_activity
from app.xlsx_reader import Bundle

MAX_LOGGED_WARNINGS = 50


@dataclass
class ImportReport:
    created: Counter[str] = field(default_factory=Counter)
    updated: Counter[str] = field(default_factory=Counter)
    restored: Counter[str] = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "created": dict(self.created),
            "updated": dict(self.updated),
            "restored": dict(self.restored),
            "warnings": self.warnings[:MAX_LOGGED_WARNINGS],
            "warnings_total": len(self.warnings),
        }


def _assign(obj: Any, values: dict[str, Any]) -> bool:
    changed = False
    for key, value in values.items():
        if getattr(obj, key) != value:
            setattr(obj, key, value)
            changed = True
    return changed


def _upsert(
    db: Session,
    model: type[models.Base],
    kind: str,
    lookup: dict[str, Any],
    content: dict[str, Any],
    work: dict[str, Any],
    create_only: dict[str, Any],
    report: ImportReport,
    overwrite_work_fields: bool,
) -> Any:
    conditions = [getattr(model, k) == v for k, v in lookup.items()]
    obj = db.scalar(select(model).where(*conditions, model.deleted_at.is_(None)))  # type: ignore[attr-defined]
    restored = False
    if obj is None:
        obj = db.scalar(select(model).where(*conditions, model.deleted_at.is_not(None)))  # type: ignore[attr-defined]
        if obj is not None:
            obj.deleted_at = None
            restored = True
    if obj is None:
        obj = model(**lookup, **content, **work, **create_only)
        db.add(obj)
        db.flush()
        report.created[kind] += 1
        return obj
    changed = _assign(obj, content)
    if overwrite_work_fields:
        changed |= _assign(obj, work)
    if restored:
        report.restored[kind] += 1
    elif changed:
        report.updated[kind] += 1
    db.flush()
    return obj


def _work(row: Any, *, priority: bool = True, due: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {"status": row.status, "comment": row.comment}
    if priority:
        out["priority"] = row.priority
    if due:
        out["due_date"] = row.due_date
    return out


def apply_bundle(
    db: Session,
    project_id: int,
    bundle: Bundle,
    *,
    overwrite_work_fields: bool = False,
) -> ImportReport:
    report = ImportReport(warnings=list(bundle.warnings))
    overwrite = overwrite_work_fields

    def upsert(model, kind, lookup, content, work, create_only=None):  # noqa: ANN001, ANN202
        return _upsert(db, model, kind, lookup, content, work, create_only or {}, report, overwrite)

    # Сцены
    next_scene_order = (
        db.scalar(select(func.max(models.Scene.order)).where(models.Scene.project_id == project_id))
        or 0
    )
    scene_ids: dict[int, int] = {}
    for row in bundle.scenes:
        next_scene_order_here = next_scene_order + 1
        scene = upsert(
            models.Scene,
            "scene",
            {"project_id": project_id, "number": row.number},
            {
                "title": row.title,
                "location": row.location,
                "time_of_day": row.time_of_day,
                "planned_sec": row.planned_sec,
                "characters": row.characters,
                "key_assets": row.key_assets,
                "lines_en": row.lines_en,
                "drum_level": row.drum_level,
                "meaning": row.meaning,
                "cut_notes": row.cut_notes,
            },
            _work(row),
            {"order": next_scene_order_here},
        )
        if scene.order == next_scene_order_here:
            next_scene_order = next_scene_order_here
        scene_ids[row.number] = scene.id

    # Ассеты и их состояния
    asset_ids: dict[str, int] = {}
    for row in bundle.assets:
        asset = upsert(
            models.Asset,
            "asset",
            {"project_id": project_id, "code": row.code},
            {"type": row.type, "name": row.name, "description": row.description},
            _work(row),
        )
        asset_ids[row.code] = asset.id
        for position, name in enumerate(row.states, start=1):
            upsert(
                models.AssetState,
                "asset_state",
                {"asset_id": asset.id, "name": name},
                {"description": None},
                {},
                {"order": position},
            )

    # Шоты и континьюити
    shot_ids: dict[str, int] = {}
    shot_order_in_scene: dict[int, int] = {}
    for row in bundle.shots:
        scene_id = scene_ids.get(row.scene_number)
        if scene_id is None:
            report.warnings.append(f"Шот {row.code}: сцена {row.scene_number} не найдена, пропущен")
            continue
        if scene_id not in shot_order_in_scene:
            shot_order_in_scene[scene_id] = (
                db.scalar(
                    select(func.max(models.Shot.order)).where(models.Shot.scene_id == scene_id)
                )
                or 0
            )
        position = shot_order_in_scene[scene_id] + 1
        shot = upsert(
            models.Shot,
            "shot",
            {"project_id": project_id, "code": row.code},
            {
                "scene_id": scene_id,
                "description": row.description,
                "size": row.size,
                "camera": row.camera,
                "sound_note": row.sound_note,
                "duration_sec": row.duration_sec,
                "tool": row.tool,
                "stage": row.stage,
            },
            _work(row),
            {"order": position, "takes_count": row.takes_count},
        )
        if shot.order == position:
            shot_order_in_scene[scene_id] = position
        shot_ids[row.code] = shot.id

    linked = {
        (shot_id, asset_id)
        for shot_id, asset_id in db.execute(
            select(models.ShotAsset.shot_id, models.ShotAsset.asset_id)
        )
    }
    for row in bundle.shots:
        shot_id = shot_ids.get(row.code)
        if shot_id is None:
            continue
        for code in row.asset_codes:
            asset_id = asset_ids.get(code)
            if asset_id is None:
                continue  # предупреждение о неизвестном ID уже есть в bundle.warnings
            if (shot_id, asset_id) not in linked:
                db.add(models.ShotAsset(shot_id=shot_id, asset_id=asset_id))
                linked.add((shot_id, asset_id))
                report.created["shot_asset"] += 1
    db.flush()

    # Сетапы и пэйоффы
    for row in bundle.setups:
        upsert(
            models.SetupPayoff,
            "setup_payoff",
            {"project_id": project_id, "number": row.number},
            {
                "motif": row.motif,
                "setup_shot_ids": [shot_ids[c] for c in row.setup_codes if c in shot_ids],
                "payoff_shot_ids": [shot_ids[c] for c in row.payoff_codes if c in shot_ids],
                "reader_takeaway": row.reader_takeaway,
                "risk": row.risk,
            },
            _work(row, priority=False, due=False),
        )

    # Звук
    for row in bundle.sounds:
        upsert(
            models.SoundCue,
            "sound_cue",
            {"project_id": project_id, "code": row.code},
            {
                "type": row.type,
                "who": row.who,
                "text_en": row.text_en,
                "text_ru": row.text_ru,
                "rights": row.rights,
                "scene_id": scene_ids.get(row.scene_number) if row.scene_number else None,
                "shot_id": shot_ids.get(row.shot_code) if row.shot_code else None,
            },
            _work(row, priority=False, due=False),
        )

    # Задачи
    for row in bundle.tasks:
        upsert(
            models.Task,
            "task",
            {"project_id": project_id, "code": row.code},
            {"block": row.block, "title": row.title},
            _work(row),
        )

    log_activity(db, None, "import", "project", project_id, report.summary(), project_id)
    return report
