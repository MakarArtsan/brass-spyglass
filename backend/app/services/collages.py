"""Коллажи: сборка из фото проекта, список, удаление. Вся запись в базу по коллажам — здесь.

Фото человек загружает обычным способом (с докачкой, без сжатия), а сюда приходят их id. Сервер сам
проверяет, что это картинки этого проекта, собирает коллаж (`app/collage.py`) и кладёт его как
обычный файл проекта: так он попадает в учёт места, получает превью и виден в медиатеке. Сборка идёт
до записи в базу, чтобы долгая работа с картинками не держала транзакцию.
"""

import hashlib
import os
import re
import tempfile
from pathlib import Path

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import collage as engine
from app import models, permissions, storage
from app.config import Settings
from app.constants import FileKind
from app.db import utcnow
from app.permissions import Actor
from app.services import files
from app.services.core import NotFoundError, ValidationError, log_activity

MAX_TITLE = 120
RESERVE_BYTES = 40 * 1024 * 1024  # запас под картинку коллажа: даже из шума 10 фото в нём не больше
HASH_BLOCK = 1 << 20
ENTITY = "collage"
NAME_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def file_name(title: str) -> str:
    """Имя файла для скачивания: из названия коллажа, без символов, которых нет в именах файлов."""
    clean = re.sub(r"\s+", " ", NAME_FORBIDDEN.sub(" ", title)).strip(" .")[:80]
    return f"{clean or 'collage'}.jpg"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(HASH_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def _photos(db: Session, settings: Settings, file_ids: list[int]) -> list[models.File]:
    """Фото проекта в том порядке, в каком их назвали. Чужой проект, удалённое, не картинка и
    «старая версия» отвечают одинаково: такого фото нет."""
    rows = {
        f.id: f
        for f in db.scalars(
            select(models.File).where(
                models.File.id.in_(file_ids),
                models.File.deleted_at.is_(None),
                models.File.is_current.is_(True),
                models.File.kind == FileKind.IMAGE.value,
            )
        )
    }
    missing = [i for i in file_ids if i not in rows]
    if missing:
        raise ValidationError("Одного из фото нет в проекте: загрузите его заново")
    ordered = [rows[i] for i in file_ids]
    for photo in ordered:
        if not photo.path or not (settings.files_dir / photo.path).is_file():
            raise ValidationError(f"Файл «{photo.original_name}» недоступен: загрузите его заново")
    return ordered


def clean_title(title: str) -> str:
    title = " ".join(title.split())
    if not title:
        raise ValidationError("Назовите коллаж")
    if len(title) > MAX_TITLE:
        raise ValidationError(f"Название длиннее {MAX_TITLE} знаков")
    return title


def _check_ids(file_ids: list[int]) -> None:
    if not engine.MIN_PHOTOS <= len(file_ids) <= engine.MAX_PHOTOS:
        raise ValidationError(
            f"В коллаже должно быть от {engine.MIN_PHOTOS} до {engine.MAX_PHOTOS} фото"
        )
    if len(set(file_ids)) != len(file_ids):
        raise ValidationError("Одно и то же фото выбрано дважды")


def _build_image(
    db: Session,
    actor: Actor,
    project: models.Project,
    photos: list[models.File],
    title: str,
    settings: Settings,
) -> tuple[models.File, engine.Layout]:
    """Собирает картинку коллажа и кладёт её файлом проекта (или берёт уже собранную такую же)."""
    storage.ensure_room(settings, db, project.id, project.storage_limit_gb, RESERVE_BYTES)
    tmp_dir = settings.cache_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(suffix=".jpg", dir=tmp_dir)
    os.close(handle)
    tmp = Path(tmp_name)
    try:
        try:
            layout = engine.render(
                [(settings.files_dir / p.path, p.original_name or f"{p.id}") for p in photos],  # type: ignore[operator]
                tmp,
            )
        except engine.CollageError as exc:
            raise ValidationError(str(exc)) from exc
        digest = _sha256(tmp)
        duplicates = files.find_duplicates(db, digest, project.id)
        if duplicates:
            image = duplicates[0]  # тот же набор в том же порядке уже собирали: картинка та же
            tmp.unlink(missing_ok=True)
        else:
            image = files.store_upload(
                db,
                actor,
                project_id=project.id,
                tmp_path=tmp,
                original_name=file_name(title),
                mime="image/jpeg",
                size_bytes=tmp.stat().st_size,
                sha256=digest,
                files_dir=settings.files_dir,
                compress=False,  # уже собранный JPEG: повторное сжатие только испортит
            )
    finally:
        tmp.unlink(missing_ok=True)  # после store_upload файл уже переехал, остаток не мешает
    return image, layout


def _put_photos(db: Session, collage_id: int, photos: list[models.File]) -> None:
    db.add_all(
        models.CollagePhoto(collage_id=collage_id, file_id=p.id, position=i)
        for i, p in enumerate(photos)
    )
    db.flush()


def create(
    db: Session,
    actor: Actor,
    project: models.Project,
    *,
    title: str,
    file_ids: list[int],
    settings: Settings,
) -> models.Collage:
    """Собирает коллаж. Гостю и неподтверждённому проекту нельзя: коллаж — новый файл."""
    permissions.require(permissions.can_create(actor, ENTITY), "Гость не создаёт коллажи")
    permissions.require_upload(actor, "Гость не создаёт коллажи")
    title = clean_title(title)
    _check_ids(file_ids)
    photos = _photos(db, settings, file_ids)
    image, layout = _build_image(db, actor, project, photos, title, settings)

    row = models.Collage(
        project_id=project.id,
        title=title,
        file_id=image.id,
        width=layout.width,
        height=layout.height,
        created_by=actor.id,
    )
    db.add(row)
    db.flush()
    _put_photos(db, row.id, photos)
    log_activity(
        db, actor.id, "create", ENTITY, row.id, {"title": title, "photos": len(photos)}, project.id
    )
    return row


def photo_ids(db: Session, collage: models.Collage) -> list[int]:
    """Какие фото в коллаже по порядку раскладки (как записано, даже если файл потом удалили)."""
    return list(
        db.scalars(
            select(models.CollagePhoto.file_id)
            .where(models.CollagePhoto.collage_id == collage.id)
            .order_by(models.CollagePhoto.position)
        )
    )


def _release_image(db: Session, collage: models.Collage, image_id: int) -> None:
    """Картинку, которой больше не пользуется ни один коллаж, убираем из проекта (в удалённые):
    иначе каждая правка оставляла бы в медиатеке и на диске устаревшую копию."""
    shared = db.scalar(
        select(func.count())
        .select_from(models.Collage)
        .where(
            models.Collage.file_id == image_id,
            models.Collage.id != collage.id,
            models.Collage.deleted_at.is_(None),
        )
    )
    image = db.scalar(select(models.File).where(models.File.id == image_id))
    if not shared and image is not None and image.deleted_at is None:
        image.deleted_at = utcnow()


def update(
    db: Session,
    actor: Actor,
    project: models.Project,
    collage_id: int,
    *,
    title: str | None = None,
    file_ids: list[int] | None = None,
    settings: Settings,
) -> models.Collage:
    """Правит готовый коллаж: название и/или состав и порядок фото. Другое название картинку не
    трогает; другой состав или порядок собирают её заново (старая картинка, если она больше никому
    не нужна, уходит в удалённые). Менять может автор, режиссёр и владелец. Пересборка — это новый
    файл, поэтому закрыта гостю и неподтверждённому проекту, а переименование — нет."""
    row = get(db, collage_id)
    permissions.require(
        permissions.can_edit(actor, ENTITY, row.created_by, {"title", "photos"}),
        "Чужой коллаж менять нельзя",
    )
    if title is None and file_ids is None:
        raise ValidationError("Нечего менять: укажите название или фото")
    old_title = row.title
    new_title = clean_title(title) if title is not None else old_title
    current = photo_ids(db, row)
    reorder = file_ids is not None and file_ids != current
    diff: dict[str, object] = {}

    if reorder:
        assert file_ids is not None
        permissions.require_upload(actor, "Гость не собирает коллажи")
        _check_ids(file_ids)
        photos = _photos(db, settings, file_ids)
        image, layout = _build_image(db, actor, project, photos, new_title, settings)
        old_image = row.file_id
        row.file_id, row.width, row.height = image.id, layout.width, layout.height
        db.execute(sql_delete(models.CollagePhoto).where(models.CollagePhoto.collage_id == row.id))
        db.flush()
        _put_photos(db, row.id, photos)
        if old_image != image.id:
            _release_image(db, row, old_image)
        diff["photos"] = {"было": len(current), "стало": len(photos)}
    if new_title != old_title:
        row.title = new_title
        diff["title"] = {"было": old_title, "стало": new_title}
        if not reorder:
            # Имя файла картинки следует за названием, пока файл только этого коллажа.
            image = db.scalar(select(models.File).where(models.File.id == row.file_id))
            others = db.scalar(
                select(func.count())
                .select_from(models.Collage)
                .where(
                    models.Collage.file_id == row.file_id,
                    models.Collage.id != row.id,
                    models.Collage.deleted_at.is_(None),
                )
            )
            if image is not None and not others and image.original_name == file_name(old_title):
                image.original_name = file_name(new_title)
    if diff:
        db.flush()
        log_activity(db, actor.id, "update", ENTITY, row.id, diff, project.id)
    return row


def get(db: Session, collage_id: int) -> models.Collage:
    row = db.scalar(
        select(models.Collage).where(
            models.Collage.id == collage_id, models.Collage.deleted_at.is_(None)
        )
    )
    if row is None:
        raise NotFoundError("Такого коллажа нет")
    return row


def listing(db: Session, *, limit: int = 200) -> list[models.Collage]:
    """Свежие коллажи проекта сверху."""
    return list(
        db.scalars(
            select(models.Collage)
            .where(models.Collage.deleted_at.is_(None))
            .order_by(models.Collage.id.desc())
            .limit(limit)
        )
    )


def photos_of(db: Session, collage: models.Collage) -> list[models.File]:
    """Фото коллажа в порядке раскладки (в том числе те, что потом убрали из проекта: пропадают)."""
    rows = db.execute(
        select(models.File)
        .join(models.CollagePhoto, models.CollagePhoto.file_id == models.File.id)
        .where(models.CollagePhoto.collage_id == collage.id, models.File.deleted_at.is_(None))
        .order_by(models.CollagePhoto.position)
    )
    return list(rows.scalars())


def photo_counts(db: Session, collage_ids: list[int]) -> dict[int, int]:
    if not collage_ids:
        return {}
    rows = db.execute(
        select(models.CollagePhoto.collage_id, func.count())
        .where(models.CollagePhoto.collage_id.in_(collage_ids))
        .group_by(models.CollagePhoto.collage_id)
    )
    return {collage_id: count for collage_id, count in rows}


def delete(db: Session, actor: Actor, collage_id: int) -> None:
    """В корзину (мягко): владелец и режиссёр — любые, «Команда» — только свои. Файлы остаются."""
    row = get(db, collage_id)
    permissions.require(
        permissions.can_delete(actor, row.created_by), "Чужой коллаж удалять нельзя"
    )
    row.deleted_at = utcnow()
    db.flush()
    log_activity(db, actor.id, "delete", ENTITY, row.id, {"title": row.title}, row.project_id)
