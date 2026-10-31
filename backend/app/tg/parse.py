"""Сообщение Telethon → запись индекса. Работает с атрибутами по именам (как у `telethon.Message`),
поэтому проверяется на подставных объектах, без настоящего Telegram.

В индекс попадает только то, что сайт умеет принять (ТЗ, форматы загрузки): иначе в окне были бы
файлы, которые нельзя импортировать. Остальное (стикеры, zip, mkv…) пропускается.
"""

import re
from datetime import UTC, datetime
from typing import Any

from app import linkpreview
from app.services.files import KIND_BY_EXT, extension
from app.tg.types import MediaInfo

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
TRAILING = ".,;:!?)»”’]"

# MIME → расширение, когда у файла нет имени (голосовые, кружки, фото)
EXT_BY_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/heic": "heic",
    "image/heif": "heif",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/markdown": "md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}


def _text(msg: Any) -> str:
    return (getattr(msg, "raw_text", None) or getattr(msg, "message", None) or "").strip()


def author_of(msg: Any) -> tuple[str | None, int | None]:
    sender = getattr(msg, "sender", None)
    name = None
    if sender is not None:
        full = " ".join(
            p
            for p in (getattr(sender, "first_name", None), getattr(sender, "last_name", None))
            if p
        )
        name = full or getattr(sender, "title", None) or getattr(sender, "username", None)
    return name, getattr(msg, "sender_id", None)


def import_name(info: MediaInfo) -> str:
    """Имя, под которым файл ляжет на сайт: своё из Telegram или собранное из темы и сообщения."""
    if info.file_name and extension(info.file_name) in KIND_BY_EXT:
        return info.file_name
    ext = EXT_BY_MIME.get(info.mime or "", "")
    if not ext and info.file_name:
        ext = extension(info.file_name)
    base = f"tg_{info.topic_id}_{info.message_id}"
    return f"{base}.{ext}" if ext else base


def _document(msg: Any) -> tuple[str, str] | None:
    """Вид документа по MIME и расширению; None — формат не поддерживается."""
    file = getattr(msg, "file", None)
    mime = (getattr(file, "mime_type", None) or "").lower()
    name = getattr(file, "name", None) or ""
    ext = extension(name) or EXT_BY_MIME.get(mime, "")
    kind = KIND_BY_EXT.get(ext)
    return (kind.value, mime) if kind is not None else None


def _first_url(msg: Any, text: str) -> str | None:
    candidates: list[str] = []
    entities = getattr(msg, "get_entities_text", None)
    if callable(entities):  # Telethon сам пересчитывает смещения UTF-16
        for entity, fragment in entities():
            kind = entity.__class__.__name__
            if kind == "MessageEntityTextUrl" and getattr(entity, "url", None):
                candidates.append(entity.url)
            elif kind == "MessageEntityUrl" and fragment:
                candidates.append(fragment)
    candidates += [m.rstrip(TRAILING) for m in URL_RE.findall(text)]
    preview = getattr(getattr(msg, "web_preview", None), "url", None)
    if preview:
        candidates.append(preview)
    for url in candidates:
        try:
            return linkpreview.parse_url(url).geturl()
        except linkpreview.LinkError:
            continue  # внутренний или кривой адрес в индекс не берём
    return None


def parse_message(msg: Any, topic_id: int) -> MediaInfo | None:
    """Запись индекса по сообщению или None, если в нём нет ничего, что можно принять."""
    if getattr(msg, "sticker", None):
        return None  # стикер — это документ webp, но не референс
    text = _text(msg)
    file = getattr(msg, "file", None)
    kind: str | None = None
    mime = getattr(file, "mime_type", None)

    if getattr(msg, "photo", None):
        kind, mime = "image", mime or "image/jpeg"
    elif getattr(msg, "voice", None) or getattr(msg, "audio", None):
        kind = "audio"
    elif (
        getattr(msg, "video", None) or getattr(msg, "video_note", None) or getattr(msg, "gif", None)
    ):
        kind = "video"
    elif getattr(msg, "document", None):
        found = _document(msg)
        if found is None:
            return None
        kind, mime = found[0], found[1] or mime

    url = None
    if kind is None:
        url = _first_url(msg, text)
        if url is None:
            return None
        kind = "link"

    name, tg_id = author_of(msg)
    posted = getattr(msg, "date", None) or datetime.now(UTC)
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=UTC)
    duration = getattr(file, "duration", None)
    return MediaInfo(
        message_id=msg.id,
        topic_id=topic_id,
        posted_at=posted,
        kind=kind,
        grouped_id=getattr(msg, "grouped_id", None),
        mime=mime,
        size_bytes=getattr(file, "size", None),
        duration_sec=float(duration) if isinstance(duration, int | float) else None,
        caption=text or None,
        file_name=getattr(file, "name", None),
        url=url,
        author_name=name,
        author_tg_id=tg_id,
    )
