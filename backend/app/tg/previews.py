"""Просмотр не импортированного файла прямо в окне «Добавить из Telegram» (ТЗ: «видео играет,
фото в полный размер»). Файл качается во временный кэш, а не в проект, старое удаляется."""

from pathlib import Path

from app.config import Settings
from app.tg.parse import import_name
from app.tg.types import MediaInfo


def target(settings: Settings, info: MediaInfo) -> Path:
    suffix = Path(import_name(info)).suffix.lower()
    return settings.tg_view_dir / f"{info.message_id}-{info.topic_id}{suffix}"


def cached(settings: Settings, message_id: int, topic_id: int) -> Path | None:
    folder = settings.tg_view_dir
    if not folder.is_dir():
        return None
    for path in folder.glob(f"{message_id}-{topic_id}.*"):
        if path.suffix != ".part" and path.is_file():
            return path
    return None


def evict(settings: Settings, keep: Path | None = None) -> int:
    """Удаляет самые старые файлы кэша, пока он не уложится в лимит. Возвращает, сколько удалено."""
    folder = settings.tg_view_dir
    if not folder.is_dir():
        return 0
    cap = settings.tg_preview_cache_mb * 1024 * 1024
    files = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    removed = 0
    for path in files:
        if total <= cap:
            break
        if keep is not None and path == keep:
            continue
        total -= path.stat().st_size
        path.unlink(missing_ok=True)
        removed += 1
    return removed
