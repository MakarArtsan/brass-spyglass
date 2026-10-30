"""Файлы: загрузка кусками с докачкой, привязки к карточкам, раздача по подписанным ссылкам."""

import asyncio
import hashlib
import mimetypes
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app import models, permissions, signing, uploads
from app.api import serialize
from app.api.entities import ActorDep, DbDep, UserDep, input_model
from app.auth import session
from app.config import get_settings
from app.constants import EntityType, Purpose
from app.services import core, files, links, projects

router = APIRouter(dependencies=[Depends(session.same_origin)])

FileUpdate = input_model(EntityType.FILE, create=False)
HASH_BLOCK = 1 << 20


def _project_id(db: Session) -> int:
    project = projects.get_project(db)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не создан")
    return project.id


def _raise(exc: uploads.UploadError) -> None:
    headers = {"Upload-Offset": str(exc.offset)} if exc.offset is not None else None
    raise HTTPException(exc.status, exc.detail, headers=headers) from exc


# --- загрузка кусками ----------------------------------------------------------------------------


class UploadInit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=500)
    size: int = Field(gt=0)
    mime: str | None = Field(default=None, max_length=200)


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
def init_upload(body: UploadInit, actor: ActorDep) -> dict[str, Any]:
    permissions.require(permissions.can_upload(actor), "Гость не загружает файлы")
    if files.kind_for(body.name) is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Формат «{files.extension(body.name) or '?'}» не поддерживается",
        )
    try:
        upload_id = uploads.create(get_settings(), actor.id, body.name, body.size, body.mime)
    except uploads.UploadError as exc:
        _raise(exc)
    return {"id": upload_id, "offset": 0, "size": body.size, "chunk_size": uploads.CHUNK_BYTES}


@router.get("/uploads/{upload_id}")
def upload_state(upload_id: str, actor: ActorDep) -> dict[str, Any]:
    """Где остановилась загрузка — клиент продолжает с этого смещения после обрыва."""
    try:
        meta = uploads.load(get_settings(), upload_id, actor.id)
    except uploads.UploadError as exc:
        _raise(exc)
    return {"id": upload_id, "offset": meta["offset"], "size": meta["size"], "name": meta["name"]}


@router.patch("/uploads/{upload_id}")
async def upload_chunk(
    upload_id: str,
    request: Request,
    actor: ActorDep,
    upload_offset: Annotated[int, Header(alias="Upload-Offset", ge=0)],
) -> dict[str, int]:
    permissions.require(permissions.can_upload(actor), "Гость не загружает файлы")
    declared = int(request.headers.get("content-length", "0") or 0)
    if declared > uploads.CHUNK_MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Кусок больше 16 МБ")
    data = await request.body()
    # Куски одной загрузки идут строго по очереди: параллельная запись испортила бы файл.
    locks = request.app.state.upload_locks
    lock = locks.setdefault(upload_id, asyncio.Lock())
    async with lock:
        try:
            offset = await asyncio.to_thread(
                uploads.append, get_settings(), upload_id, actor.id, upload_offset, data
            )
        except uploads.UploadError as exc:
            _raise(exc)
    return {"offset": offset}


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_upload(upload_id: str, actor: ActorDep) -> None:
    try:
        uploads.load(get_settings(), upload_id, actor.id)
    except uploads.UploadError as exc:
        _raise(exc)
    uploads.discard(get_settings(), upload_id)


class UploadComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: str | None = None
    entity_id: int | None = None
    purpose: Literal[tuple(p.value for p in Purpose)] = Purpose.REFERENCE.value  # type: ignore[valid-type]
    force: bool = False  # добавить, даже если такой файл уже есть


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(HASH_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def _duplicate_info(db: Session, duplicate: models.File) -> dict[str, Any]:
    uploader = db.get(models.User, duplicate.uploaded_by) if duplicate.uploaded_by else None
    pairs = list(
        db.execute(
            select(models.Attachment.entity_type, models.Attachment.entity_id).where(
                models.Attachment.file_id == duplicate.id
            )
        )
    )
    labels = serialize.entity_labels(db, {(t, i) for t, i in pairs})
    return {
        "file_id": duplicate.id,
        "original_name": duplicate.original_name,
        "uploaded_by": uploader.name if uploader else None,
        "uploaded_at": duplicate.uploaded_at,
        "attached_to": [labels[(t, i)] for t, i in pairs if (t, i) in labels],
    }


@router.post("/uploads/{upload_id}/complete", status_code=status.HTTP_201_CREATED)
def complete_upload(
    upload_id: str,
    body: UploadComplete,
    request: Request,
    db: DbDep,
    actor: ActorDep,
) -> Any:
    permissions.require(permissions.can_upload(actor), "Гость не загружает файлы")
    settings = get_settings()
    try:
        meta = uploads.load(settings, upload_id, actor.id)
    except uploads.UploadError as exc:
        _raise(exc)
    if meta["offset"] != meta["size"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Файл загружен не полностью",
            headers={"Upload-Offset": str(meta["offset"])},
        )
    if (body.entity_type is None) != (body.entity_id is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Нужны и тип, и id карточки")
    if body.entity_type is not None:
        core.get(db, body.entity_type, body.entity_id)  # type: ignore[arg-type]  # цель должна существовать

    part = uploads.part_path(settings, upload_id)
    digest = _sha256(part)
    project_id = _project_id(db)
    duplicates = files.find_duplicates(db, digest, project_id)
    if duplicates and not body.force:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "Такой файл уже есть в проекте",
                "duplicate": serialize_json(_duplicate_info(db, duplicates[0])),
            },
        )

    file = files.store_upload(
        db,
        actor,
        project_id=project_id,
        tmp_path=part,
        original_name=meta["name"],
        mime=meta.get("mime") or mimetypes.guess_type(meta["name"])[0],
        size_bytes=meta["size"],
        sha256=digest,
        files_dir=settings.files_dir,
    )
    uploads.discard(settings, upload_id)
    attachment_id = None
    if body.entity_type is not None:
        attachment = links.attach(
            db, actor, file.id, body.entity_type, body.entity_id, body.purpose
        )  # type: ignore[arg-type]
        attachment_id = attachment.id
    db.flush()
    request.app.state.jobs.wake()
    return {"file": serialize.files_out(db, [file])[0], "attachment_id": attachment_id}


def serialize_json(value: dict[str, Any]) -> dict[str, Any]:
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(value)


# --- файлы и привязки ----------------------------------------------------------------------------


@router.get("/files")
def list_entity_files(
    db: DbDep,
    _: UserDep,
    entity_type: Annotated[str, Query()],
    entity_id: Annotated[int, Query()],
) -> list[dict[str, Any]]:
    rows = list(
        db.execute(
            select(models.Attachment, models.File)
            .join(models.File, models.File.id == models.Attachment.file_id)
            .where(
                models.Attachment.entity_type == entity_type,
                models.Attachment.entity_id == entity_id,
                models.File.deleted_at.is_(None),
            )
            .order_by(models.Attachment.id)
        )
    )
    shown = serialize.files_out(db, [f for _, f in rows])
    people = serialize.authors(db, {a.created_by for a, _ in rows})
    return [
        {
            "attachment_id": a.id,
            "purpose": a.purpose,
            "attached_at": a.created_at,
            "attached_by": people.get(a.created_by) if a.created_by else None,
            "file": item,
        }
        for (a, _), item in zip(rows, shown, strict=True)
    ]


@router.get("/files/{file_id}")
def get_file(file_id: int, db: DbDep, _: UserDep) -> dict[str, Any]:
    return serialize.files_out(db, [core.get(db, EntityType.FILE, file_id)])[0]  # type: ignore[list-item]


@router.patch("/files/{file_id}")
def update_file(file_id: int, body: FileUpdate, db: DbDep, actor: ActorDep) -> dict[str, Any]:  # type: ignore[valid-type]
    file = core.update(db, actor, EntityType.FILE, file_id, body.model_dump(exclude_unset=True))
    return serialize.files_out(db, [file])[0]


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: int, db: DbDep, actor: ActorDep) -> None:
    """В корзину. Свой файл удаляет любой, чужой — режиссёр и владелец (и только они)."""
    core.delete(db, actor, EntityType.FILE, file_id)


class AttachBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: int
    entity_type: str
    entity_id: int
    purpose: Literal[tuple(p.value for p in Purpose)] = Purpose.REFERENCE.value  # type: ignore[valid-type]


@router.post("/attachments", status_code=status.HTTP_201_CREATED)
def attach_file(body: AttachBody, db: DbDep, actor: ActorDep) -> dict[str, int]:
    """Привязать уже загруженный файл к ещё одной карточке — без повторной загрузки."""
    row = links.attach(db, actor, body.file_id, body.entity_type, body.entity_id, body.purpose)
    return {"attachment_id": row.id}


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def detach_file(attachment_id: int, db: DbDep, actor: ActorDep) -> None:
    links.detach(db, actor, attachment_id)


# --- раздача -------------------------------------------------------------------------------------


def _content_disposition(name: str, attachment: bool) -> str:
    kind = "attachment" if attachment else "inline"
    return f"{kind}; filename*=UTF-8''{quote(name, safe='')}"


@router.api_route("/files/{file_id}/{variant}", methods=["GET", "HEAD"])
def serve_file(
    file_id: int,
    variant: str,
    db: DbDep,
    _: UserDep,
    t: str | None = None,
    download: bool = False,
) -> Any:
    """Файл по подписанной ссылке и только залогиненным. Range поддерживается (перемотка)."""
    if variant not in signing.VARIANTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нет такого варианта")
    if not signing.verify(t, file_id, variant):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ссылка недействительна или устарела")
    file = core.get(db, EntityType.FILE, file_id)
    settings = get_settings()

    if variant == "waveform":
        if not file.waveform_json:  # type: ignore[attr-defined]
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Волна ещё не готова")
        return JSONResponse(file.waveform_json, headers={"Cache-Control": "private, max-age=3600"})  # type: ignore[attr-defined]

    cache = settings.cache_dir
    paths: dict[str, Path | None] = {
        "original": settings.files_dir / file.path if file.path else None,  # type: ignore[attr-defined,operator]
        "thumb": cache / file.thumb_path if file.thumb_path else None,  # type: ignore[attr-defined,operator]
        "preview": cache / str(file_id) / "preview.jpg",
        "poster": cache / str(file_id) / "poster.jpg",
        "proxy": cache / file.proxy_path if file.proxy_path else None,  # type: ignore[attr-defined,operator]
    }
    path = paths[variant]
    if path is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")

    if variant == "original":
        media_type = file.mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"  # type: ignore[attr-defined]
        name = file.original_name or path.name  # type: ignore[attr-defined]
    else:
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        name = path.name
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Content-Disposition": _content_disposition(name, download),
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/entities/{entity_type}/{entity_id}/zip")
def zip_entity_files(entity_type: str, entity_id: int, db: DbDep, _: UserDep) -> Any:
    """Все файлы карточки одним zip (оригиналы, как были загружены)."""
    core.get(db, entity_type, entity_id)
    rows = list(
        db.execute(
            select(models.File)
            .join(models.Attachment, models.Attachment.file_id == models.File.id)
            .where(
                models.Attachment.entity_type == entity_type,
                models.Attachment.entity_id == entity_id,
                models.File.deleted_at.is_(None),
            )
            .order_by(models.Attachment.id)
        ).scalars()
    )
    settings = get_settings()
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "У карточки нет файлов")
    tmp_dir = settings.cache_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(suffix=".zip", dir=tmp_dir)
    os.close(handle)
    used: set[str] = set()
    with zipfile.ZipFile(tmp_name, "w", zipfile.ZIP_STORED) as archive:
        for file in rows:
            if not file.path or not (settings.files_dir / file.path).is_file():
                continue
            name = file.original_name or Path(file.path).name
            if name in used:
                name = f"{file.id}_{name}"
            used.add(name)
            archive.write(settings.files_dir / file.path, arcname=name)
    return FileResponse(
        tmp_name,
        media_type="application/zip",
        headers={
            "Content-Disposition": _content_disposition(f"{entity_type}-{entity_id}.zip", True)
        },
        background=BackgroundTask(lambda: Path(tmp_name).unlink(missing_ok=True)),
    )
