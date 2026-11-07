"""Коллаж из фотографий: раскладка рядами и сборка JPEG. Чистые функции над файлами: ни БД, ни HTTP.

Размер: ширина 3840 px (4K), высота выходит из раскладки (обычно 2000–3000 px). Фотографии лежат
рядами одной высоты и **не обрезаются**: ни один край снимка не теряется, пропорции сохраняются (с
точностью до пикселя). Порядок фото — как задал человек: ряды идут подряд, меняется только то, где
ряд ломается. Исходники не меняются и скачиваются отдельно, поэтому коллаж — обзор, а не замена
оригиналам.
"""

import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageCms, ImageOps

from app.media import to_8bit  # заодно подключает HEIC

MIN_PHOTOS = 2
MAX_PHOTOS = 10
CANVAS_WIDTH = 3840  # 4K по ширине
GAP = 16  # зазор между фото и поля по краям
TARGET_ASPECT = 1.5  # к какой пропорции (ширина / высота) тянется коллаж: 3:2
MAX_ROW_RATIO = 2.0  # ряды разной высоты допустимы, но не в разы
BACKGROUND = (14, 20, 32)  # ink из brand.ts: фон под зазорами и прозрачностью
JPEG_QUALITY = 90
MAX_SOURCE_PIXELS = 120_000_000  # крупнее — не фото, а «бомба»; Pillow предупреждает с 89 млн


class CollageError(Exception):
    """Коллаж собрать нельзя: сообщение для человека."""


@dataclass(frozen=True, slots=True)
class Cell:
    index: int  # номер фото в заданном порядке
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True, slots=True)
class Layout:
    width: int
    height: int
    cells: tuple[Cell, ...]


def _split(count: int, mask: int) -> list[list[int]]:
    """Подряд идущие фото → ряды: бит `mask` говорит, что после этого фото ряд заканчивается."""
    rows: list[list[int]] = [[0]]
    for i in range(1, count):
        if mask >> (i - 1) & 1:
            rows.append([i])
        else:
            rows[-1].append(i)
    return rows


def plan(aspects: Sequence[float], *, width: int = CANVAS_WIDTH, gap: int = GAP) -> Layout:
    """Раскладка рядами: из всех способов разбить фото на ряды берётся тот, что ближе к 3:2 и где
    ряды не слишком разной высоты. Фото ≤ 10, вариантов ≤ 512: перебор мгновенный и на одни и те
    же входные данные отвечает одинаково."""
    count = len(aspects)
    if not MIN_PHOTOS <= count <= MAX_PHOTOS:
        raise ValueError(f"Фото в коллаже: от {MIN_PHOTOS} до {MAX_PHOTOS}")
    if any(a <= 0 for a in aspects):
        raise ValueError("Пропорция фото должна быть положительной")
    inner = width - 2 * gap
    target_height = width / TARGET_ASPECT
    best: tuple[float, list[list[int]], list[float]] | None = None
    for mask in range(1 << (count - 1)):
        rows = _split(count, mask)
        heights = [(inner - gap * (len(r) - 1)) / sum(aspects[i] for i in r) for r in rows]
        total = sum(heights) + gap * (len(rows) + 1)
        ratio = max(heights) / min(heights)
        score = abs(math.log(total / target_height)) + 0.5 * math.log(ratio)
        if ratio > MAX_ROW_RATIO:
            score += 10 * (ratio - MAX_ROW_RATIO)  # крайняя мера: подходящих может не быть вовсе
        if best is None or score < best[0] - 1e-12:
            best = (score, rows, heights)
    assert best is not None
    _, rows, heights = best

    cells: list[Cell] = []
    y = gap
    for row, exact in zip(rows, heights, strict=True):
        row_h = max(1, round(exact))
        x = gap
        room = inner - gap * (len(row) - 1)
        used = 0
        for position, i in enumerate(row):
            last = position == len(row) - 1
            w = room - used if last else max(1, round(aspects[i] * row_h))
            cells.append(Cell(i, x, y, w, row_h))
            x += w + gap
            used += w
        y += row_h + gap
    cells.sort(key=lambda c: c.index)
    return Layout(width, y, tuple(cells))


def _oriented_size(image: Image.Image) -> tuple[int, int]:
    """Размер снимка с учётом поворота из EXIF (телефон пишет вертикальные кадры горизонтально)."""
    w, h = image.size
    try:
        orientation = image.getexif().get(0x0112, 1)
    except Exception:  # битый EXIF не повод отказать фото
        orientation = 1
    return (h, w) if orientation in (5, 6, 7, 8) else (w, h)


def _open(path: Path, name: str) -> Image.Image:
    try:
        image = Image.open(path)
        width, height = _oriented_size(image)
    except Exception as exc:
        raise CollageError(
            f"Не удалось открыть фото «{name}»: файл повреждён или это не картинка"
        ) from exc
    if image.size[0] * image.size[1] > MAX_SOURCE_PIXELS:
        image.close()
        raise CollageError(f"Фото «{name}» слишком большое для коллажа")
    if width < 1 or height < 1:
        raise CollageError(f"Фото «{name}» пустое")
    return image


def _to_srgb(image: Image.Image, icc: bytes | None) -> Image.Image:
    """Фото со встроенным профилем (телефоны снимают в Display P3) приводятся к sRGB, иначе цвета
    «выцветают». Нет профиля или он не читается — картинка остаётся как есть."""
    if not icc:
        return image
    try:
        source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        target = ImageCms.createProfile("sRGB")
        return ImageCms.profileToProfile(image, source, target, outputMode="RGB") or image
    except Exception:
        return image


def _prepare(image: Image.Image, size: tuple[int, int], name: str) -> Image.Image:
    """Снимок → RGB нужного размера: поворот по EXIF, 8 бит, прозрачность на тёмном фоне, sRGB."""
    try:
        icc = image.info.get("icc_profile")
        rotated = (size[1], size[0]) if _oriented_size(image) != image.size else size
        if image.format == "JPEG":
            image.draft("RGB", rotated)  # JPEG распаковывается сразу уменьшенным: в разы быстрее
        image.load()
        image = to_8bit(ImageOps.exif_transpose(image))
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            flat = Image.new("RGB", rgba.size, BACKGROUND)
            flat.paste(rgba, mask=rgba.getchannel("A"))
            image = flat
        else:
            image = image.convert("RGB")
        image = image.resize(size, Image.Resampling.LANCZOS, reducing_gap=2.0)
    except CollageError:
        raise
    except Exception as exc:
        raise CollageError(f"Не удалось обработать фото «{name}»: {exc}") from exc
    return _to_srgb(image, icc)


def render(photos: Sequence[tuple[Path, str]], dest: Path, *, width: int = CANVAS_WIDTH) -> Layout:
    """Собирает коллаж из фото (путь, имя для сообщений) в JPEG `dest`. Фото открываются по одному,
    а не все сразу: память не растёт с числом фото."""
    if not MIN_PHOTOS <= len(photos) <= MAX_PHOTOS:
        raise CollageError(f"В коллаже должно быть от {MIN_PHOTOS} до {MAX_PHOTOS} фото")
    opened = [_open(path, name) for path, name in photos]
    try:
        sizes = [_oriented_size(image) for image in opened]
        layout = plan([w / h for w, h in sizes], width=width)
        canvas = Image.new("RGB", (layout.width, layout.height), BACKGROUND)
        for cell, image, (_, name) in zip(layout.cells, opened, photos, strict=True):
            canvas.paste(_prepare(image, (cell.w, cell.h), name), (cell.x, cell.y))
            image.close()
        dest.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(dest, "JPEG", quality=JPEG_QUALITY, subsampling=0, optimize=True)
    finally:
        for image in opened:
            image.close()
    return layout
