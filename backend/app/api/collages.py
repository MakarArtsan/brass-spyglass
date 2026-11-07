"""Коллажи: список, сборка из загруженных фото, скачивание картинки и исходных фото, удаление.

Фото загружаются обычным способом (`/uploads`), сюда приходят их id. Права (гость, неподтверждённый
проект, чужой коллаж) проверяет сервис, не роутер.
"""

import os
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app import models, scope, storage
from app.api import serialize
from app.api.entities import ActorDep, DbDep, UserDep
from app.api.files import _content_disposition
from app.auth import session
from app.config import get_settings
from app.services import collages, projects

router = APIRouter(prefix="/collages", dependencies=[Depends(session.same_origin)])


class CollageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, Field(min_length=1, max_length=400)]  # точную границу ставит сервис
    file_ids: Annotated[list[int], Field(min_length=1, max_length=50)]


def _photo(file: models.File) -> dict[str, Any]:
    return {
        "id": file.id,
        "original_name": file.original_name,
        "size_bytes": file.size_bytes,
        "width": file.width,
        "height": file.height,
        "urls": serialize.file_urls(file),
    }


def _items(db: Session, rows: list[models.Collage]) -> list[dict[str, Any]]:
    """Карточки коллажей для списка: картинка, автор, сколько фото; сами фото — в карточке."""
    ids = {r.file_id for r in rows}
    images = (
        {f.id: f for f in db.scalars(select(models.File).where(models.File.id.in_(ids)))}
        if ids
        else {}
    )
    counts = collages.photo_counts(db, [r.id for r in rows])
    people = serialize.authors(db, {r.created_by for r in rows})
    base = f"/api/p/{db.info[scope.PROJECT_SLUG]}/collages"
    return [
        {
            "id": r.id,
            "title": r.title,
            "width": r.width,
            "height": r.height,
            "photos": counts.get(r.id, 0),
            "size_bytes": images[r.file_id].size_bytes,
            "created_at": r.created_at,
            "created_by": people.get(r.created_by) if r.created_by else None,
            "urls": serialize.file_urls(images[r.file_id]),
            "download_url": f"{base}/{r.id}/download",
            "zip_url": f"{base}/{r.id}/photos.zip",
        }
        for r in rows
        if r.file_id in images
    ]


@router.get("")
def list_collages(db: DbDep, _: UserDep) -> list[dict[str, Any]]:
    return _items(db, collages.listing(db))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_collage(body: CollageIn, request: Request, db: DbDep, actor: ActorDep) -> dict[str, Any]:
    """Собирает коллаж из уже загруженных фото. Работа долгая (секунды): запрос ждёт её в потоке."""
    try:
        row = collages.create(
            db,
            actor,
            projects.current(db),
            title=body.title,
            file_ids=body.file_ids,
            settings=get_settings(),
        )
    except storage.NoRoom as exc:
        raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, str(exc)) from exc
    request.app.state.jobs.wake()  # превью коллажа
    return _items(db, [row])[0]


@router.get("/{collage_id}")
def get_collage(collage_id: int, db: DbDep, _: UserDep) -> dict[str, Any]:
    row = collages.get(db, collage_id)
    return {**_items(db, [row])[0], "photo_list": [_photo(f) for f in collages.photos_of(db, row)]}


@router.get("/{collage_id}/download")
def download_collage(collage_id: int, db: DbDep, _: UserDep) -> FileResponse:
    """Картинка коллажа (3840 px по ширине) под названием коллажа."""
    row = collages.get(db, collage_id)
    image = db.get(models.File, row.file_id)
    path = get_settings().files_dir / image.path if image and image.path else None
    if path is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл коллажа не найден")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Content-Disposition": _content_disposition(collages.file_name(row.title), True)},
    )


@router.get("/{collage_id}/photos.zip")
def download_photos(collage_id: int, db: DbDep, _: UserDep) -> FileResponse:
    """Исходные фото коллажа одним zip, как были загружены; имена с номером по порядку раскладки."""
    row = collages.get(db, collage_id)
    settings = get_settings()
    found = [
        (f, settings.files_dir / f.path)
        for f in collages.photos_of(db, row)
        if f.path and (settings.files_dir / f.path).is_file()
    ]
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Исходных фото не осталось")
    tmp_dir = settings.cache_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(suffix=".zip", dir=tmp_dir)
    os.close(handle)
    with zipfile.ZipFile(tmp_name, "w", zipfile.ZIP_STORED) as archive:  # JPEG уже сжат
        for position, (file, path) in enumerate(found, start=1):
            name = (file.original_name or path.name).replace("/", "_").replace("\\", "_")
            archive.write(path, arcname=f"{position:02d}_{name}")
    return FileResponse(
        tmp_name,
        media_type="application/zip",
        headers={
            "Content-Disposition": _content_disposition(
                collages.file_name(row.title).removesuffix(".jpg") + " — фото.zip", True
            )
        },
        background=BackgroundTask(lambda: Path(tmp_name).unlink(missing_ok=True)),
    )


@router.delete("/{collage_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collage(collage_id: int, db: DbDep, actor: ActorDep) -> None:
    collages.delete(db, actor, collage_id)
