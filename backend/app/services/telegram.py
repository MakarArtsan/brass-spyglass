"""Индекс медиа закрытого чата и импорт выбранного в карточки. Здесь — вся запись в БД по Telegram.

Индекс (`tg_topic`, `tg_media`) хранит только метаданные и маленькие превью; сам файл скачивается,
когда его выбрали. Повторный выбор того же сообщения не создаёт дубль: файл привязывается к ещё
одной карточке (ТЗ).
"""

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import linkpreview, models, permissions
from app.constants import EntityType, FileKind, FileSource, JobType, Purpose
from app.db import ci_contains, utcnow
from app.events import queue_event
from app.permissions import Actor
from app.services import core, files, jobs, links
from app.tg import parse
from app.tg.types import MediaInfo, TopicInfo

MAX_IMPORT_ITEMS = (
    200  # за один раз: ТЗ требует 20, а потолок нужен, чтобы запрос не был бесконечным
)


# --- индекс ------------------------------------------------------------------------------------


def upsert_topics(db: Session, chat_id: int, topics: Iterable[TopicInfo]) -> None:
    known = {
        t.topic_id: t
        for t in db.scalars(select(models.TgTopic).where(models.TgTopic.chat_id == chat_id))
    }
    for info in topics:
        row = known.get(info.topic_id)
        if row is None:
            db.add(
                models.TgTopic(
                    chat_id=chat_id,
                    topic_id=info.topic_id,
                    title=info.title,
                    icon_emoji=info.icon_emoji,
                )
            )
        else:
            row.title = info.title
            row.icon_emoji = info.icon_emoji
    db.flush()


def get_topic(db: Session, chat_id: int, topic_id: int) -> models.TgTopic | None:
    return db.scalar(
        select(models.TgTopic).where(
            models.TgTopic.chat_id == chat_id, models.TgTopic.topic_id == topic_id
        )
    )


def newest_message_id(db: Session, chat_id: int, topic_id: int) -> int:
    return (
        db.scalar(
            select(func.max(models.TgMedia.message_id)).where(
                models.TgMedia.chat_id == chat_id, models.TgMedia.topic_id == topic_id
            )
        )
        or 0
    )


def save_media(db: Session, chat_id: int, items: Iterable[MediaInfo]) -> int:
    """Добавляет новые записи, у известных обновляет подпись и размер (сообщение могли изменить).
    Возвращает, сколько записей создано."""
    items = list(items)
    if not items:
        return 0
    known = {
        m.message_id: m
        for m in db.scalars(
            select(models.TgMedia).where(
                models.TgMedia.chat_id == chat_id,
                models.TgMedia.message_id.in_([i.message_id for i in items]),
            )
        )
    }
    created = 0
    for info in items:
        row = known.get(info.message_id)
        if row is None:
            db.add(
                models.TgMedia(
                    chat_id=chat_id,
                    topic_id=info.topic_id,
                    message_id=info.message_id,
                    grouped_id=info.grouped_id,
                    kind=info.kind,
                    mime=info.mime,
                    size_bytes=info.size_bytes,
                    duration_sec=info.duration_sec,
                    caption=info.caption,
                    file_name=info.file_name,
                    url=info.url,
                    author_name=info.author_name,
                    author_tg_id=info.author_tg_id,
                    posted_at=info.posted_at,
                )
            )
            created += 1
        else:
            row.caption, row.file_name, row.size_bytes = (
                info.caption,
                info.file_name,
                info.size_bytes,
            )
    db.flush()
    if created:
        # Окно «Добавить из Telegram» у всех открытых вкладок перечитает список: свежее видно сразу.
        for topic_id in {i.topic_id for i in items}:
            queue_event(db, {"type": "tg", "topic_id": topic_id})
    return created


def mark_progress(
    db: Session,
    chat_id: int,
    topic_id: int,
    *,
    oldest: int | None = None,
    complete: bool | None = None,
) -> None:
    """Где индексатор дочитал историю темы: после перезапуска он продолжит отсюда, а не с начала."""
    topic = get_topic(db, chat_id, topic_id)
    if topic is None:
        return
    if oldest is not None and (topic.oldest_message_id is None or oldest < topic.oldest_message_id):
        topic.oldest_message_id = oldest
    if complete is not None:
        topic.history_complete = complete
    topic.last_synced_at = utcnow()
    topic.media_count = (
        db.scalar(
            select(func.count())
            .select_from(models.TgMedia)
            .where(models.TgMedia.chat_id == chat_id, models.TgMedia.topic_id == topic_id)
        )
        or 0
    )


def without_thumbs(db: Session, chat_id: int, limit: int) -> list[tuple[int, int]]:
    """(id записи, id сообщения) без превью, новые первыми: сначала то, что люди увидят в окне."""
    rows = db.execute(
        select(models.TgMedia.id, models.TgMedia.message_id)
        .where(
            models.TgMedia.chat_id == chat_id,
            models.TgMedia.thumb_path.is_(None),
            models.TgMedia.kind.in_([FileKind.IMAGE.value, FileKind.VIDEO.value]),
        )
        .order_by(models.TgMedia.posted_at.desc())
        .limit(limit)
    )
    return [(i, m) for i, m in rows]


def set_thumb(db: Session, media_id: int, path: str) -> None:
    row = db.get(models.TgMedia, media_id)
    if row is not None:
        row.thumb_path = path


def find_media(db: Session, chat_id: int, message_id: int) -> models.TgMedia | None:
    return db.scalar(
        select(models.TgMedia).where(
            models.TgMedia.chat_id == chat_id, models.TgMedia.message_id == message_id
        )
    )


def get_media(db: Session, media_id: int) -> models.TgMedia:
    row = db.get(models.TgMedia, media_id)
    if row is None:
        raise core.NotFoundError("Такого медиа нет в индексе Telegram")
    return row


# --- импорт ------------------------------------------------------------------------------------


def queue_import(
    db: Session,
    actor: Actor,
    *,
    project_id: int,
    media_ids: list[int],
    entity_type: str,
    entity_id: int,
    purpose: str,
) -> models.Job:
    """Ставит задачу `tg_import`: скачать оригиналы, сделать превью, привязать к карточке."""
    permissions.require(permissions.can_upload(actor), "Гость не загружает файлы")
    ids = list(dict.fromkeys(media_ids))  # без повторов, порядок сохраняется
    if not ids:
        raise core.ValidationError("Не выбрано ни одного файла")
    if len(ids) > MAX_IMPORT_ITEMS:
        raise core.ValidationError(f"За один раз не больше {MAX_IMPORT_ITEMS} файлов")
    if purpose not in {p.value for p in Purpose}:
        raise core.ValidationError(f"Неизвестное назначение: {purpose}")
    links.require_attach_target(entity_type)
    core.get(db, entity_type, entity_id)  # цель должна существовать
    found = set(db.scalars(select(models.TgMedia.id).where(models.TgMedia.id.in_(ids))))
    if found != set(ids):
        raise core.NotFoundError("Часть выбранных файлов не найдена в индексе Telegram")
    return jobs.enqueue(
        db,
        JobType.TG_IMPORT,
        {
            "media_ids": ids,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "purpose": purpose,
            "project_id": project_id,
        },
        actor.id,
    )


def queue_preview(db: Session, actor: Actor, media_id: int) -> models.Job:
    """Просмотр не скачанного файла прямо в окне: качаем во временный кэш, не в проект."""
    permissions.require(permissions.can_upload(actor), "Гость не смотрит чат")
    get_media(db, media_id)
    return jobs.enqueue(db, JobType.TG_IMPORT, {"preview": media_id}, actor.id)


def existing_file(db: Session, chat_id: int, message_id: int) -> models.File | None:
    return db.scalar(
        select(models.File).where(
            models.File.tg_chat_id == chat_id,
            models.File.tg_message_id == message_id,
            models.File.deleted_at.is_(None),
        )
    )


def _attach(
    db: Session, actor: Actor, file: models.File, entity_type: str, entity_id: int, purpose: str
) -> bool:
    """Привязка; уже привязанный к этой карточке файл не ошибка. Возвращает, привязали ли заново."""
    try:
        links.attach(db, actor, file.id, entity_type, entity_id, purpose)
    except core.ConflictError:
        return False
    return True


def attach_imported(
    db: Session, actor: Actor, media: models.TgMedia, entity_type: str, entity_id: int, purpose: str
) -> models.File | None:
    """Файл из этого сообщения уже на сайте: привязываем к ещё одной карточке, без скачивания."""
    file = existing_file(db, media.chat_id, media.message_id)
    if file is None:
        return None
    media.imported_file_id = file.id
    _attach(db, actor, file, entity_type, entity_id, purpose)
    return file


def import_link(
    db: Session,
    actor: Actor,
    media: models.TgMedia,
    *,
    project_id: int,
    entity_type: str,
    entity_id: int,
    purpose: str,
) -> models.File:
    """Ссылка из текста сообщения: карточка без скачивания, заголовок подтянет фоновая задача."""
    if not media.url:
        raise core.ValidationError("В сообщении нет ссылки")
    try:
        url = linkpreview.parse_url(media.url).geturl()
    except linkpreview.LinkError as exc:
        raise core.ValidationError(str(exc)) from exc
    file = core.create(
        db,
        actor,
        EntityType.FILE,
        {
            "kind": FileKind.LINK.value,
            "source": FileSource.TELEGRAM.value,
            "url": url,
            "tg_chat_id": media.chat_id,
            "tg_topic_id": media.topic_id,
            "tg_message_id": media.message_id,
            "tg_author": media.author_name,
        },
        project_id=project_id,
    )
    jobs.enqueue(db, JobType.PREVIEW, {"file_id": file.id}, actor.id)
    media.imported_file_id = file.id
    _attach(db, actor, file, entity_type, entity_id, purpose)
    return file


def import_downloaded(
    db: Session,
    actor: Actor,
    media: models.TgMedia,
    *,
    project_id: int,
    tmp_path: Path,
    sha256: str,
    size_bytes: int,
    files_dir: Path,
    entity_type: str,
    entity_id: int,
    purpose: str,
) -> models.File:
    """Скачанный файл становится файлом проекта: автор — тот, кто выбрал, откуда пришёл — тема,
    сообщение и автор в Telegram; оригинал не меняется, превью делает фоновая задача."""
    info = MediaInfo(
        message_id=media.message_id,
        topic_id=media.topic_id,
        posted_at=media.posted_at,
        kind=media.kind,
        mime=media.mime,
        file_name=media.file_name,
    )
    file = files.store_upload(
        db,
        actor,
        project_id=project_id,
        tmp_path=tmp_path,
        original_name=parse.import_name(info),
        mime=media.mime,
        size_bytes=size_bytes,
        sha256=sha256,
        files_dir=files_dir,
        source=FileSource.TELEGRAM,
        extra={
            "tg_chat_id": media.chat_id,
            "tg_topic_id": media.topic_id,
            "tg_message_id": media.message_id,
            "tg_author": media.author_name,
        },
    )
    media.imported_file_id = file.id
    _attach(db, actor, file, entity_type, entity_id, purpose)
    return file


# --- чтение для окна «Добавить из Telegram» -----------------------------------------------------


def topics_with_latest_thumb(db: Session, chat_id: int) -> list[dict[str, Any]]:
    topics = list(
        db.scalars(
            select(models.TgTopic)
            .where(models.TgTopic.chat_id == chat_id)
            .order_by(models.TgTopic.media_count.desc(), models.TgTopic.title)
        )
    )
    latest: dict[int, int] = {}
    for media_id, topic_id in db.execute(
        select(models.TgMedia.id, models.TgMedia.topic_id)
        .where(models.TgMedia.chat_id == chat_id, models.TgMedia.thumb_path.is_not(None))
        .order_by(models.TgMedia.posted_at.asc())
    ):
        latest[topic_id] = media_id  # последняя в порядке возрастания — самая новая
    return [
        {
            "topic_id": t.topic_id,
            "title": t.title,
            "icon_emoji": t.icon_emoji,
            "media_count": t.media_count,
            "last_synced_at": t.last_synced_at,
            "history_complete": t.history_complete,
            "latest_thumb_media_id": latest.get(t.topic_id),
        }
        for t in topics
    ]


def media_page(
    db: Session,
    chat_id: int,
    *,
    topic_id: int | None,
    kinds: list[str] | None,
    query: str | None,
    hide_imported: bool,
    before: tuple[datetime, int] | None,
    limit: int,
) -> list[models.TgMedia]:
    stmt = select(models.TgMedia).where(models.TgMedia.chat_id == chat_id)
    if topic_id is not None:
        stmt = stmt.where(models.TgMedia.topic_id == topic_id)
    if kinds:
        stmt = stmt.where(models.TgMedia.kind.in_(kinds))
    if hide_imported:
        stmt = stmt.where(models.TgMedia.imported_file_id.is_(None))
    if query and query.strip():
        needle = query.strip()
        stmt = stmt.where(
            ci_contains(models.TgMedia.caption, needle)
            | ci_contains(models.TgMedia.file_name, needle)
            | ci_contains(models.TgMedia.author_name, needle)
        )
    if before is not None:
        when, mid = before
        stmt = stmt.where(
            (models.TgMedia.posted_at < when)
            | ((models.TgMedia.posted_at == when) & (models.TgMedia.id < mid))
        )
    return list(
        db.scalars(
            stmt.order_by(models.TgMedia.posted_at.desc(), models.TgMedia.id.desc()).limit(limit)
        )
    )


def overview(db: Session, chat_id: int) -> dict[str, Any]:
    topics = db.scalar(
        select(func.count()).select_from(models.TgTopic).where(models.TgTopic.chat_id == chat_id)
    )
    media = db.scalar(
        select(func.count()).select_from(models.TgMedia).where(models.TgMedia.chat_id == chat_id)
    )
    synced = db.scalar(
        select(func.max(models.TgTopic.last_synced_at)).where(models.TgTopic.chat_id == chat_id)
    )
    complete = db.scalar(
        select(func.count())
        .select_from(models.TgTopic)
        .where(models.TgTopic.chat_id == chat_id, models.TgTopic.history_complete.is_(True))
    )
    return {
        "topics": topics or 0,
        "media": media or 0,
        "topics_complete": complete or 0,
        "last_synced_at": synced,
    }
