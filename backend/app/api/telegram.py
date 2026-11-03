"""Окно «Добавить из Telegram»: темы, медиа темы, просмотр, импорт, прогресс. Только для участников,
не для гостя: индекс чата — это содержимое закрытого чата команды."""

import mimetypes
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, permissions, scope, signing, tglinks
from app.api.entities import ActorDep, DbDep
from app.auth import session
from app.config import get_settings
from app.constants import JobStatus, JobType, Purpose
from app.db import utcnow
from app.permissions import Actor
from app.services import projects
from app.services import telegram as tg_service
from app.services.core import NotFoundError
from app.tg import previews, runtime
from app.tg.types import MediaInfo

KINDS = {"image", "video", "audio", "document", "link"}
RECENT_JOB_SEC = 120


def member(actor: ActorDep) -> Actor:
    permissions.require(permissions.can_upload(actor), "Чат команды недоступен гостю")
    return actor


router = APIRouter(prefix="/tg", dependencies=[Depends(session.same_origin), Depends(member)])


def _chat_id(db: Session) -> int:
    """Чат проекта: окно «Добавить из Telegram» показывает только его (один чат — один проект)."""
    chat = projects.current(db).tg_chat_id
    if chat is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "К проекту не привязан чат Telegram")
    return chat


def _signed_url(db: Session, media_id: int, part: str) -> str:
    pid, slug = scope.current_project_id(db), db.info[scope.PROJECT_SLUG]
    token = signing.sign(media_id, f"tg-{part}", pid)
    return f"/api/p/{slug}/tg/media/{media_id}/{part}?t={token}"


def thumb_url(db: Session, media_id: int) -> str:
    return _signed_url(db, media_id, "thumb")


def view_url(db: Session, media_id: int) -> str:
    return _signed_url(db, media_id, "view")


def _media_row(db: Session, media_id: int) -> models.TgMedia:
    """Медиа из индекса — только из чата проекта: чужой чат и несуществующее медиа неотличимы."""
    row = tg_service.get_media(db, media_id)
    if row.chat_id != _chat_id(db):
        raise NotFoundError("Такого медиа нет в индексе Telegram")
    return row


def _item(db: Session, row: models.TgMedia) -> dict[str, Any]:
    return {
        "id": row.id,
        "message_id": row.message_id,
        "topic_id": row.topic_id,
        "kind": row.kind,
        "mime": row.mime,
        "caption": row.caption,
        "file_name": row.file_name,
        "url": row.url,
        "grouped_id": row.grouped_id,
        "author_name": row.author_name,
        "posted_at": row.posted_at,
        "size_bytes": row.size_bytes,
        "duration_sec": row.duration_sec,
        "thumb_url": thumb_url(db, row.id) if row.thumb_path else None,
        "imported_file_id": row.imported_file_id,
        "open_url": tglinks.message_url(row.chat_id, row.topic_id, row.message_id),
    }


@router.get("/status")
def tg_status(db: DbDep, request: Request) -> dict[str, Any]:
    settings = get_settings()
    chat = projects.current(db).tg_chat_id
    mine = runtime.gateway is not None and getattr(runtime.gateway, "chat_id", None) == chat
    indexer = runtime.indexer if mine else None
    state = indexer.state if indexer else None
    overview = tg_service.overview(db, chat) if chat is not None else None
    return {
        "configured": bool(settings.tg_session and chat is not None),
        "connected": mine,
        "userbot_error": getattr(request.app.state.tg, "userbot_error", None),
        "chat_id": chat,
        "syncing": bool(state and state.running),
        "phase": state.phase if state else "idle",
        "topic": state.topic if state else None,
        "thumbs_left": state.thumbs_left if state else 0,
        "last_error": state.last_error if state else None,
        "last_run_at": state.last_run_at if state else None,
        "overview": overview,
    }


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
def tg_sync(db: DbDep, actor: ActorDep) -> dict[str, bool]:
    """Прочитать чат заново, не дожидаясь плановой синхронизации. Только владелец."""
    permissions.require(permissions.can_manage_users(actor), "Синхронизацию запускает владелец")
    chat = projects.current(db).tg_chat_id
    if runtime.indexer is None or getattr(runtime.gateway, "chat_id", None) != chat:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Юзербот Telegram не подключён")
    runtime.indexer.request_sync()
    return {"started": True}


@router.get("/topics")
def tg_topics(db: DbDep) -> list[dict[str, Any]]:
    topics = tg_service.topics_with_latest_thumb(db, _chat_id(db))
    for topic in topics:
        media_id = topic.pop("latest_thumb_media_id")
        topic["latest_thumb_url"] = thumb_url(db, media_id) if media_id else None
    return topics


@router.get("/media")
def tg_media(
    db: DbDep,
    topic_id: int | None = None,
    kinds: Annotated[
        str | None, Query(description="через запятую: image,video,audio,document,link")
    ] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    hide_imported: bool = False,
    before_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
) -> dict[str, Any]:
    wanted = [k for k in (kinds or "").split(",") if k]
    if any(k not in KINDS for k in wanted):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Неизвестный тип медиа")
    before = None
    if before_id is not None:
        anchor = db.get(models.TgMedia, before_id)
        if anchor is not None and anchor.chat_id != _chat_id(db):
            anchor = None  # курсор из чужого чата не годится
        if anchor is not None:
            before = (anchor.posted_at, anchor.id)
    rows = tg_service.media_page(
        db,
        _chat_id(db),
        topic_id=topic_id,
        kinds=wanted or None,
        query=q,
        hide_imported=hide_imported,
        before=before,
        limit=limit + 1,
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [_item(db, r) for r in rows],
        "next_before_id": rows[-1].id if more and rows else None,
    }


def _thumb_path(row: models.TgMedia) -> Path | None:
    if not row.thumb_path:
        return None
    base = get_settings().tg_thumbs_dir.resolve()
    path = (base / row.thumb_path).resolve()
    return path if path.is_relative_to(base) and path.is_file() else None


@router.get("/media/{media_id}/thumb")
def tg_thumb(media_id: int, db: DbDep, t: str | None = None) -> FileResponse:
    if not signing.verify(t, media_id, "tg-thumb", scope.current_project_id(db)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ссылка устарела")
    path = _thumb_path(_media_row(db, media_id))
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Миниатюры нет")
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"}
    )


def _view_info(row: models.TgMedia) -> MediaInfo:
    return MediaInfo(
        message_id=row.message_id, topic_id=row.topic_id, posted_at=row.posted_at,
        kind=row.kind, mime=row.mime, file_name=row.file_name,
    )  # fmt: skip


@router.post("/media/{media_id}/view")
def tg_view(media_id: int, request: Request, db: DbDep, actor: ActorDep) -> dict[str, Any]:
    """Готов ли файл к просмотру в окне. Если нет — ставит задачу скачать его в кэш просмотра."""
    row = _media_row(db, media_id)
    if row.kind == "link":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Ссылку открывают в новой вкладке"
        )
    if previews.cached(get_settings(), row.message_id, row.topic_id) is not None:
        return {"ready": True, "url": view_url(db, row.id), "job_id": None}
    pending = db.scalars(
        select(models.Job).where(
            models.Job.type == JobType.TG_IMPORT.value,
            models.Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
        )
    )
    job = next((j for j in pending if j.payload.get("preview") == media_id), None)
    if job is None:
        job = tg_service.queue_preview(db, actor, media_id)
        db.flush()
        request.app.state.jobs.wake()
    return {"ready": False, "url": None, "job_id": job.id}


@router.get("/media/{media_id}/view")
def tg_view_file(media_id: int, db: DbDep, t: str | None = None) -> FileResponse:
    if not signing.verify(t, media_id, "tg-view", scope.current_project_id(db)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ссылка устарела")
    row = _media_row(db, media_id)
    path = previews.cached(get_settings(), row.message_id, row.topic_id)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл ещё не загружен для просмотра")
    media_type = mimetypes.guess_type(path.name)[0] or row.mime or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_ids: list[int] = Field(min_length=1, max_length=tg_service.MAX_IMPORT_ITEMS)
    entity_type: str
    entity_id: int
    purpose: Purpose = Purpose.REFERENCE


@router.post("/import", status_code=status.HTTP_202_ACCEPTED)
def tg_import(body: ImportIn, request: Request, db: DbDep, actor: ActorDep) -> dict[str, Any]:
    """Отметили файлы → сервер скачает оригиналы, сделает превью и привяжет к карточке."""
    project = projects.current(db)
    job = tg_service.queue_import(
        db,
        actor,
        project_id=project.id,
        media_ids=body.media_ids,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        purpose=body.purpose.value,
    )
    db.flush()
    request.app.state.jobs.wake()
    return {"job_id": job.id, "count": len(job.payload["media_ids"])}


@router.get("/jobs")
def tg_jobs(db: DbDep, actor: ActorDep) -> list[dict[str, Any]]:
    """Мои импорты из Telegram: идущие и закончившиеся только что. Прогресс в углу экрана."""
    since = utcnow() - timedelta(seconds=RECENT_JOB_SEC)
    rows = db.scalars(
        select(models.Job)
        .where(models.Job.type == JobType.TG_IMPORT.value, models.Job.created_by == actor.id)
        .order_by(models.Job.id.desc())
        .limit(20)
    )
    out = []
    for job in rows:
        if "media_ids" not in job.payload:  # просмотр, а не импорт
            continue
        finished = job.finished_at
        if finished is not None and finished < since:
            continue
        out.append(
            {
                "id": job.id,
                "status": job.status,
                "progress": job.progress,
                "error": job.error,
                "total": len(job.payload["media_ids"]),
                "entity_type": job.payload.get("entity_type"),
                "entity_id": job.payload.get("entity_id"),
            }
        )
    return out
