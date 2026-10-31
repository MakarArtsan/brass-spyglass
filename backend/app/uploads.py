"""Загрузка кусками с докачкой (ТЗ: «загрузка кусками с докачкой при обрыве, лимит 4 ГБ»).

Протокол (свой, в духе tus): создать сессию → слать куски с `Upload-Offset` → завершить.
Состояние хранится на диске (`/data/cache/uploads/<id>.part` и `.json`), а не в памяти, поэтому
обрыв сети и даже перезапуск контейнера не теряют принятые байты. Смещение — размер `.part`:
других источников правды нет, поэтому рассинхронизироваться нечему.
"""

import json
import re
import secrets
import time
from pathlib import Path

from app.config import Settings

MAX_FILE_BYTES = 4 * 1024**3
CHUNK_MAX_BYTES = 16 * 1024**2
CHUNK_BYTES = 8 * 1024**2  # рекомендованный клиенту размер куска
ID_RE = re.compile(r"^[0-9a-f]{32}$")
STALE_AFTER_SEC = 7 * 86400


class UploadError(Exception):
    def __init__(self, status: int, detail: str, offset: int | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.offset = offset


def _root(settings: Settings) -> Path:
    root = settings.cache_dir / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def part_path(settings: Settings, upload_id: str) -> Path:
    return _root(settings) / f"{upload_id}.part"


def _meta_path(settings: Settings, upload_id: str) -> Path:
    return _root(settings) / f"{upload_id}.json"


def create(settings: Settings, user_id: int, name: str, size: int, mime: str | None) -> str:
    if size <= 0:
        raise UploadError(422, "Пустой файл")
    if size > MAX_FILE_BYTES:
        raise UploadError(413, "Файл больше 4 ГБ")
    upload_id = secrets.token_hex(16)
    meta = {"id": upload_id, "user_id": user_id, "name": name, "size": size, "mime": mime}
    _meta_path(settings, upload_id).write_text(json.dumps(meta, ensure_ascii=False))
    part_path(settings, upload_id).touch()
    return upload_id


def load(settings: Settings, upload_id: str, user_id: int) -> dict:
    """Метаданные сессии и текущее смещение. Чужую сессию продолжить нельзя."""
    if not ID_RE.match(upload_id):
        raise UploadError(404, "Загрузка не найдена")
    try:
        meta = json.loads(_meta_path(settings, upload_id).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        raise UploadError(404, "Загрузка не найдена или устарела") from None
    if meta["user_id"] != user_id:
        raise UploadError(403, "Это чужая загрузка")
    part = part_path(settings, upload_id)
    meta["offset"] = part.stat().st_size if part.exists() else 0
    return meta


def append(settings: Settings, upload_id: str, user_id: int, offset: int, data: bytes) -> int:
    meta = load(settings, upload_id, user_id)
    if len(data) > CHUNK_MAX_BYTES:
        raise UploadError(413, "Кусок больше 16 МБ")
    if offset != meta["offset"]:
        # Клиент отстал или повторил кусок: сообщаем, где мы на самом деле, он продолжит оттуда.
        raise UploadError(409, "Смещение не совпадает", offset=meta["offset"])
    if meta["offset"] + len(data) > meta["size"]:
        raise UploadError(422, "Кусок выходит за размер файла")
    with part_path(settings, upload_id).open("ab") as handle:
        handle.write(data)
    return meta["offset"] + len(data)


def discard(settings: Settings, upload_id: str) -> None:
    for path in (part_path(settings, upload_id), _meta_path(settings, upload_id)):
        path.unlink(missing_ok=True)


def cleanup_stale(settings: Settings, max_age_sec: float = STALE_AFTER_SEC) -> int:
    """Убирает брошенные загрузки, чтобы они не копились на диске `/data`."""
    removed = 0
    cutoff = time.time() - max_age_sec
    for path in _root(settings).iterdir():
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed
