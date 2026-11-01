"""Экспорт в Resolve и Premiere: план из базы, фоновая задача `export`, история и срок хранения.

Читает базу короткими сессиями и не держит транзакцию на время сборки zip: ffmpeg и копирование
файлов идут минутами. Готовый zip лежит 7 дней (ТЗ), потом его удаляет `cleanup`.
"""

import logging
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db as database
from app import export_plan as ep
from app import exporter, models, permissions, storage
from app.config import Settings
from app.constants import EntityType, ExportTarget, JobType, Purpose
from app.db import utcnow
from app.export_plan import CueX, FileRef, Level, SceneX, ShotX
from app.media import MediaError
from app.permissions import Actor
from app.services import core, finals, jobs, projects, versions
from app.services.core import ValidationError, log_activity

log = logging.getLogger(__name__)

KEEP_DAYS = 7
MAX_MEDIA_ROOT = 260
MAX_SKIPPED_LISTED = 120
STALE_PART_SEC = 3600


@dataclass(frozen=True, slots=True)
class Plan:
    spec: exporter.PackageSpec
    bytes_needed: int


def clean_media_root(value: str | None) -> str:
    text = (value or "").strip()
    if len(text) > MAX_MEDIA_ROOT or re.search(r"[\x00-\x1f]", text):
        raise ValidationError("Папка на диске: слишком длинный путь или лишние символы")
    return text


def _ref(file: models.File | None, kind: str | None = None) -> FileRef | None:
    if file is None:
        return None
    return FileRef(
        file.id,
        file.path,
        file.original_name or f"file{file.id}",
        file.version_no,
        file.duration_sec,
        kind or file.kind,
    )


def _skip_reason(obj: models.Scene | models.Shot) -> str:
    if obj.final_file_id is None:
        return "нет финального файла"
    if obj.status != "done":
        return f"статус «{exporter.STATUS_RU.get(obj.status, obj.status)}»"
    return "финальный файл удалён"


def _audio_ref(file: models.File | None) -> FileRef | None:
    """Звуковым клипом на дорожке может быть только аудиофайл."""
    return _ref(file) if file is not None and file.kind == "audio" else None


def load_plan(
    db: Session,
    settings: Settings,
    *,
    level: Level,
    placeholders: bool,
    references: bool,
    media_root: str = "",
    base_url: str = "",
    target: str = ExportTarget.RESOLVE.value,
) -> Plan:
    project = projects.get_project(db)
    if project is None:
        raise ValidationError("Проект не создан")
    scenes = list(
        db.scalars(
            select(models.Scene)
            .where(models.Scene.project_id == project.id, models.Scene.deleted_at.is_(None))
            .order_by(models.Scene.order, models.Scene.id)
        )
    )
    shots = list(
        db.scalars(
            select(models.Shot)
            .where(models.Shot.project_id == project.id, models.Shot.deleted_at.is_(None))
            .order_by(models.Shot.order, models.Shot.id)
        )
    )
    scene_files = finals.resolve(db, scenes)
    shot_files = finals.resolve(db, shots)
    scene_x = [
        SceneX(
            s.id, s.number, s.title, s.order, s.status, s.planned_sec, _ref(scene_files.get(s.id))
        )
        for s in scenes
    ]
    shot_x = [
        ShotX(
            s.id,
            s.scene_id,
            s.code,
            s.order,
            s.status,
            s.duration_sec,
            _ref(shot_files.get(s.id)),
            s.description,
        )
        for s in shots
    ]
    clips = ep.plan_timeline(
        scene_x, shot_x, level=level, placeholders=placeholders, fps=project.fps
    )

    cues = list(
        db.scalars(
            select(models.SoundCue)
            .where(models.SoundCue.project_id == project.id, models.SoundCue.deleted_at.is_(None))
            .order_by(models.SoundCue.id)
        )
    )
    cue_files = versions.current_many(db, {c.file_id for c in cues if c.file_id})
    cue_x = [
        CueX(
            c.id,
            c.code,
            c.type,
            c.who,
            c.text_en,
            c.scene_id,
            c.shot_id,
            c.start_offset_sec,
            _audio_ref(cue_files.get(c.file_id) if c.file_id else None),
        )
        for c in cues
    ]
    placed = ep.place_cues(cue_x, scene_x, shot_x, clips, project.fps)

    on_timeline = {(c.scene_id, c.shot_id) for c in clips if c.kind == "file"}
    skipped = _skipped(on_timeline, level, scenes, shots)
    refs = _references(db, clips, scenes, shots) if references else []

    spec = exporter.PackageSpec(
        project_title=project.title,
        options=exporter.Options(
            target=target,
            level=level,
            placeholders=placeholders,
            references=references,
            media_root=media_root,
            base_url=base_url,
        ),
        clips=clips,
        placements=ep.audio_placements(placed),
        subtitles=ep.subtitles(placed),
        references=refs,
        skipped=skipped,
        files_dir=settings.files_dir,
        fps=project.fps,
        width=project.width,
        height=project.height,
        font=exporter.find_font(),
    )
    needed = _bytes_needed(db, spec)
    return Plan(spec, needed)


def _skipped(
    on_timeline: set[tuple[int, int | None]],
    level: Level,
    scenes: list[models.Scene],
    shots: list[models.Shot],
) -> list[str]:
    """Что не попало на таймлайн и почему: чтобы дыра в хронометраже не была сюрпризом."""
    out: list[str] = []
    scene_by_id = {s.id: s for s in scenes}
    if level is Level.SCENES:
        for scene in scenes:
            if scene.status != "cut" and (scene.id, None) not in on_timeline:
                out.append(f"Сцена {scene.number} · {scene.title} — {_skip_reason(scene)}")
    else:
        for shot in shots:
            scene = scene_by_id.get(shot.scene_id)
            if shot.status == "cut" or scene is None or scene.status == "cut":
                continue
            if (scene.id, shot.id) not in on_timeline:
                out.append(f"Шот {shot.code} — {_skip_reason(shot)}")
    if len(out) > MAX_SKIPPED_LISTED:
        rest = len(out) - MAX_SKIPPED_LISTED
        out = [*out[:MAX_SKIPPED_LISTED], f"…и ещё {rest}"]
    return out


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "file"


def _references(
    db: Session, clips: list[ep.Clip], scenes: list[models.Scene], shots: list[models.Shot]
) -> list[exporter.Reference]:
    """Референсы сцен и шотов, которые есть на таймлайне, — отдельной папкой Media/References."""
    scene_ids = {c.scene_id for c in clips}
    shot_ids = {c.shot_id for c in clips if c.shot_id}
    if level_has_scene_clips(clips):
        shot_ids |= {s.id for s in shots if s.scene_id in scene_ids}
    rows = db.execute(
        select(models.File)
        .join(models.Attachment, models.Attachment.file_id == models.File.id)
        .where(
            models.Attachment.purpose == Purpose.REFERENCE.value,
            models.File.deleted_at.is_(None),
            models.File.is_current.is_(True),
            models.File.kind != "link",
            (
                (models.Attachment.entity_type == EntityType.SCENE.value)
                & models.Attachment.entity_id.in_(scene_ids or {0})
            )
            | (
                (models.Attachment.entity_type == EntityType.SHOT.value)
                & models.Attachment.entity_id.in_(shot_ids or {0})
            ),
        )
        .order_by(models.File.id)
    ).scalars()
    seen: set[int] = set()
    out: list[exporter.Reference] = []
    for file in rows:
        if file.id in seen or not file.path:
            continue
        seen.add(file.id)
        ref = _ref(file)
        assert ref is not None
        out.append(
            exporter.Reference(ref, f"Media/References/R{file.id:05d}_{_safe_name(ref.name)}")
        )
    return out


def level_has_scene_clips(clips: list[ep.Clip]) -> bool:
    return any(c.shot_id is None for c in clips)


def _bytes_needed(db: Session, spec: exporter.PackageSpec) -> int:
    ids = {c.file.id for c in spec.clips if c.file}
    ids |= {p.cue.file.id for p in spec.placements if p.cue.file}
    ids |= {r.file.id for r in spec.references}
    if not ids:
        return 0
    sizes = db.scalars(select(models.File.size_bytes).where(models.File.id.in_(ids)))
    return sum(s or 0 for s in sizes)


# --- постановка и история -----------------------------------------------------------------------


def create(
    db: Session,
    actor: Actor,
    *,
    target: str,
    level: str,
    placeholders: bool,
    references: bool,
    media_root: str,
    base_url: str,
) -> models.ExportJob:
    permissions.require(permissions.can_export(actor), "Гость не делает экспорт")
    if target not in {t.value for t in ExportTarget}:
        raise ValidationError(f"Неизвестная программа: {target}")
    if level not in {lv.value for lv in Level}:
        raise ValidationError(f"Неизвестный уровень: {level}")
    project = projects.get_project(db)
    if project is None:
        raise ValidationError("Проект не создан")
    row = models.ExportJob(
        project_id=project.id,
        target=target,
        scope=level,
        options={
            "placeholders": placeholders,
            "references": references,
            "media_root": clean_media_root(media_root),
            "base_url": base_url.strip()[:300],
        },
        created_by=actor.id,
    )
    db.add(row)
    db.flush()
    job = jobs.enqueue(db, JobType.EXPORT, {"export_id": row.id}, actor.id)
    row.job_id = job.id
    log_activity(
        db,
        actor.id,
        "export",
        EntityType.PROJECT.value,
        project.id,
        {"target": target, "level": level, "export_id": row.id},
        project.id,
    )
    return row


def expires_at(row: models.ExportJob) -> datetime:
    return row.created_at + timedelta(days=KEEP_DAYS)


def is_available(row: models.ExportJob, settings: Settings, now: datetime | None = None) -> bool:
    if not row.result_path or expires_at(row) <= (now or utcnow()):
        return False
    return (settings.exports_dir / row.result_path).is_file()


def history(db: Session, limit: int = 30) -> list[models.ExportJob]:
    return list(
        db.scalars(select(models.ExportJob).order_by(models.ExportJob.id.desc()).limit(limit))
    )


def get(db: Session, export_id: int) -> models.ExportJob:
    row = db.get(models.ExportJob, export_id)
    if row is None:
        raise core.NotFoundError("Экспорт не найден")
    return row


# --- выполнение (поток воркера) ------------------------------------------------------------------


def run(export_id: int, job_id: int, settings: Settings) -> None:
    """Собирает пакет. База читается короткой сессией, потом идёт долгая сборка без транзакции."""
    with database.session_factory()() as db:
        row = get(db, export_id)
        opts = dict(row.options or {})
        plan = load_plan(
            db,
            settings,
            level=Level(row.scope),
            placeholders=bool(opts.get("placeholders")),
            references=bool(opts.get("references")),
            media_root=str(opts.get("media_root") or ""),
            base_url=str(opts.get("base_url") or ""),
            target=row.target,
        )
        limit = projects.get_project(db).storage_limit_gb  # type: ignore[union-attr]
        stamp = row.created_at.strftime("%Y%m%d-%H%M%S")
        name = f"brass-spyglass-{row.id:04d}-{row.target}-{stamp}.zip"
    if not plan.spec.clips:
        raise MediaError(
            "На таймлайне нечего собирать: нет готовых сцен с финальным файлом. "
            "Включите «Плейсхолдеры» или отметьте финальные файлы."
        )
    try:
        storage.ensure_room(settings, limit, plan.bytes_needed + plan.bytes_needed // 20)
    except storage.NoRoom as exc:
        raise MediaError(str(exc)) from exc

    def progress(value: float) -> None:
        with database.session_factory()() as short:
            jobs.set_progress(short, job_id, value)
            short.commit()

    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    result = exporter.build_package(plan.spec, settings.exports_dir / name, progress)
    with database.session_factory()() as db:
        row = get(db, export_id)
        row.result_path = name
        row.options = {**(row.options or {}), "result": result.as_dict()}
        db.commit()


def cleanup(settings: Settings, now: datetime | None = None) -> int:
    """Удаляет пакеты старше 7 дней и обрывки недособранных. Возвращает число удалённых zip."""
    now = now or utcnow()
    removed = 0
    with database.session_factory()() as db:
        for row in db.scalars(
            select(models.ExportJob).where(models.ExportJob.result_path.is_not(None))
        ):
            if expires_at(row) > now:
                continue
            (settings.exports_dir / str(row.result_path)).unlink(missing_ok=True)
            row.options = {**(row.options or {}), "expired": True}
            row.result_path = None
            removed += 1
        db.commit()
    if settings.exports_dir.is_dir():
        stale_before = time.time() - STALE_PART_SEC  # свежие обрывки — это идущая сборка
        for leftover in settings.exports_dir.iterdir():
            if leftover.stat().st_mtime > stale_before:
                continue
            if leftover.name.startswith("export-") and leftover.is_dir():
                shutil.rmtree(leftover, ignore_errors=True)
            elif leftover.suffix == ".part":
                leftover.unlink(missing_ok=True)
    return removed


def path_of(row: models.ExportJob, settings: Settings) -> Path | None:
    return settings.exports_dir / row.result_path if is_available(row, settings) else None  # type: ignore[operator]
