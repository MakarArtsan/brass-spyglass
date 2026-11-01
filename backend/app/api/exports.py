"""Экспорт в DaVinci Resolve и Premiere Pro: параметры, что попадёт на таймлайн,
история, скачивание."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import export_plan as ep
from app import models, permissions
from app.api import serialize
from app.api.entities import ActorDep, DbDep
from app.auth import session
from app.config import get_settings
from app.constants import JobStatus
from app.export_plan import Level
from app.services import exports
from app.services.core import NotFoundError

router = APIRouter(dependencies=[Depends(session.same_origin)])


def _require_export(actor: ActorDep) -> None:
    permissions.require(permissions.can_export(actor), "Гость не делает экспорт")


ExportActor = Annotated[None, Depends(_require_export)]


class ExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Literal["resolve", "premiere"] = "resolve"
    level: Literal["scenes", "shots"] = "scenes"
    placeholders: bool = False
    references: bool = False
    media_root: str = Field(default="", max_length=exports.MAX_MEDIA_ROOT)


def _base_url(request: Request) -> str:
    origin = request.headers.get("origin")
    return (origin or str(request.base_url)).rstrip("/")


@router.get("/exports/preview")
def preview(
    db: DbDep,
    _: ExportActor,
    level: Literal["scenes", "shots"] = "scenes",
    placeholders: bool = False,
    references: bool = False,
) -> dict[str, Any]:
    """Что попадёт на таймлайн при таких параметрах, ещё до сборки: порядок, длительность, дыры."""
    plan = exports.load_plan(
        db,
        get_settings(),
        level=Level(level),
        placeholders=placeholders,
        references=references,
    )
    spec = plan.spec
    clips = [
        {
            "name": c.name,
            "kind": c.kind,
            "label": c.label,
            "scene_number": c.scene_number,
            "shot_code": c.shot_code,
            "timecode": ep.timecode(c.start_frame, spec.fps),
            "frames": c.frames,
            "seconds": round(c.frames / spec.fps, 2),
            "status": c.status,
        }
        for c in spec.clips
    ]
    return {
        "fps": spec.fps,
        "clips": clips,
        "ready": sum(1 for c in spec.clips if c.kind == "file"),
        "placeholders": sum(1 for c in spec.clips if c.kind == "placeholder"),
        "total_sec": round(sum(c.frames for c in spec.clips) / spec.fps, 2),
        "audio": len(spec.placements),
        "subtitles": len(spec.subtitles),
        "references": len(spec.references),
        "skipped": spec.skipped,
        "bytes_needed": plan.bytes_needed,
    }


def _item(
    row: models.ExportJob,
    job: models.Job | None,
    people: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    settings = get_settings()
    options = dict(row.options or {})
    available = exports.is_available(row, settings)
    state = job.status if job else JobStatus.DONE.value
    return {
        "id": row.id,
        "target": row.target,
        "level": row.scope,
        "placeholders": bool(options.get("placeholders")),
        "references": bool(options.get("references")),
        "media_root": options.get("media_root") or "",
        "created_at": row.created_at,
        "created_by": people.get(row.created_by) if row.created_by else None,
        "status": state,
        "progress": round(job.progress or 0, 2) if job else 1.0,
        "error": job.error if job else None,
        "result": options.get("result"),
        "expires_at": exports.expires_at(row),
        "expired": bool(options.get("expired")) or (not available and row.result_path is not None),
        "available": available,
        "download_url": f"/api/exports/{row.id}/download" if available else None,
    }


def _history(db: Session) -> list[dict[str, Any]]:
    rows = exports.history(db)
    jobs_by_id = {
        j.id: j
        for j in db.scalars(
            select(models.Job).where(models.Job.id.in_([r.job_id for r in rows if r.job_id]))
        )
    }
    people = serialize.authors(db, {r.created_by for r in rows})
    return [_item(r, jobs_by_id.get(r.job_id) if r.job_id else None, people) for r in rows]


@router.get("/subtitles.srt")
def subtitles_srt(db: DbDep, _: ExportActor) -> Response:
    """«Экспорт субтитров» с экрана «Звук»: английские реплики с таймкодами по таймлайну трекера
    (порядок и длительности сцен из трекера, без учёта того, какие файлы уже готовы)."""
    plan = exports.load_plan(
        db, get_settings(), level=Level.SCENES, placeholders=True, references=False, use_files=False
    )
    text = ep.format_srt(plan.spec.subtitles, plan.spec.fps)
    return Response(
        text,
        media_type="application/x-subrip; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=subtitles_en.srt"},
    )


@router.get("/exports")
def list_exports(db: DbDep, _: ExportActor) -> list[dict[str, Any]]:
    return _history(db)


@router.post("/exports", status_code=status.HTTP_201_CREATED)
def create_export(body: ExportIn, request: Request, db: DbDep, actor: ActorDep) -> dict[str, Any]:
    row = exports.create(
        db,
        actor,
        target=body.target,
        level=body.level,
        placeholders=body.placeholders,
        references=body.references,
        media_root=body.media_root,
        base_url=_base_url(request),
    )
    request.app.state.jobs.wake()
    db.flush()
    job = db.get(models.Job, row.job_id) if row.job_id else None
    return _item(row, job, serialize.authors(db, {row.created_by}))


@router.get("/exports/{export_id}/download")
def download(export_id: int, db: DbDep, _: ExportActor) -> FileResponse:
    try:
        row = exports.get(db, export_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    path = exports.path_of(row, get_settings())
    if path is None:
        raise HTTPException(
            status.HTTP_410_GONE,
            "Срок хранения пакета истёк или он ещё не собран. Соберите заново.",
        )
    return FileResponse(path, media_type="application/zip", filename=path.name)
