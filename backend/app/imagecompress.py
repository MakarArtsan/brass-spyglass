"""Сжатие картинок при загрузке (ТЗ, «Сжатие картинок при загрузке»).

Так же, как TinyPNG, но внутри контейнера и без внешних сервисов:
  * PNG — квантование палитры (pngquant, качество 70–90, прозрачность сохраняется), затем
    lossless-оптимизация oxipng;
  * JPEG — mozjpeg (quality 84, progressive, оптимизированные таблицы Хаффмана);
  * WebP, AVIF, GIF — не трогаем: уже сжаты или анимированы;
  * HEIC, BMP, TIFF — конвертация в JPEG (если есть прозрачность — в PNG), затем сжатие как выше:
    монтажки и Seedance открывают не все из них.

Правила: выигрыш меньше 10% — оставляем оригинал; поворот по EXIF применяется к пикселям, EXIF и GPS
уходят, цветовой профиль (ICC) сохраняется; разрешение не меняется.

Только чистые функции над файлами — ни БД, ни HTTP (как `media.py`). Результат пишется во временный
каталог, подмену файла и хранение оригинала делает `services/compression.py`.

Если на машине нет pngquant или mozjpeg (разработка, тесты), работает запасной путь на Pillow:
для JPEG — его кодировщик с теми же настройками, для PNG — только lossless-оптимизация без
квантования, чтобы качество не страдало. Что именно работает, видно в `/api/health`.
"""

import io
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageCms, ImageOps

from app import media
from app.config import Settings, get_settings
from app.media import MediaError

try:
    import oxipng
except ImportError:  # pragma: no cover - в образе oxipng есть, это страховка для чужой машины
    oxipng = None  # type: ignore[assignment]

MIN_GAIN = 0.10  # меньше — оставляем оригинал, чтобы не терять качество ради пары килобайт
JPEG_QUALITY = 84
PNGQUANT_QUALITY = "70-90"
OXIPNG_LEVEL = 4
OXIPNG_TIMEOUT_SEC = 120
TOOL_TIMEOUT_SEC = 300
PNGQUANT_SKIPPED = (98, 99)  # 98 — результат не меньше исходного, 99 — качество ниже 70

# Расширение исходного файла → что с ним делать. jfif и jpe до сюда не доходят: хранятся как jpg.
ROUTES = {
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "png": "png",
    "heic": "convert",
    "heif": "convert",
    "bmp": "convert",
    "tif": "convert",
    "tiff": "convert",
}
MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}


@dataclass(frozen=True, slots=True)
class Tools:
    """Что из кодировщиков есть на машине. `None`/`False` — работает запасной путь."""

    pngquant: str | None
    cjpeg: str | None
    oxipng: bool


def detect_tools(settings: Settings | None = None) -> Tools:
    s = settings or get_settings()
    return Tools(
        pngquant=shutil.which(s.pngquant_bin),
        cjpeg=shutil.which(s.cjpeg_bin),
        oxipng=oxipng is not None,
    )


@dataclass(frozen=True, slots=True)
class Result:
    state: str  # done | small_gain | skipped
    output: Path | None = None  # сжатый файл во временном каталоге (только при done)
    ext: str | None = None  # его расширение: jpg или png
    mime: str | None = None
    note: str = ""


def can_compress(ext: str) -> bool:
    return ext.lower() in ROUTES


# --- чтение ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class Decoded:
    image: Image.Image
    icc: bytes | None
    alpha: bool


def _srgb_conversion(image: Image.Image, icc: bytes | None) -> Image.Image:
    """CMYK → RGB. С профилем — через него (цвета не уезжают), без — как есть."""
    if icc:
        try:
            source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            target = ImageCms.createProfile("sRGB")
            return ImageCms.profileToProfile(image, source, target, outputMode="RGB")  # type: ignore[return-value]
        except Exception:  # битый профиль — обычная конвертация лучше, чем отказ
            pass
    return image.convert("RGB")


def decode(src: Path) -> Decoded:
    """Пиксели с применённым поворотом EXIF, в 8 бит, режим RGB/L (или RGBA/LA с прозрачностью)."""
    try:
        with Image.open(src) as raw:
            raw.load()  # у многостраничного TIFF и анимации берётся первый кадр
            icc = raw.info.get("icc_profile")
            transparent = "transparency" in raw.info
            image = media.to_8bit(ImageOps.exif_transpose(raw))
    except Exception as exc:
        raise MediaError(f"Не удалось открыть изображение: {exc}") from exc
    mode = image.mode
    if mode == "CMYK":
        return Decoded(_srgb_conversion(image, icc), None, False)
    if mode in ("RGBA", "LA"):
        return Decoded(image, icc, True)
    if mode in ("PA",) or (mode == "P" and transparent):
        return Decoded(image.convert("RGBA"), icc, True)
    if mode in ("RGB", "L"):
        return Decoded(image, icc, False)
    if mode == "1":
        return Decoded(image.convert("L"), icc, False)
    return Decoded(image.convert("RGB"), icc, False)  # P без прозрачности, YCbCr, LAB…


# --- JPEG -----------------------------------------------------------------------------------------


def _run(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=TOOL_TIMEOUT_SEC, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{Path(cmd[0]).name}: превышено время обработки") from exc
    except FileNotFoundError as exc:
        raise MediaError(f"{cmd[0]} не установлен") from exc


def _tail(process: subprocess.CompletedProcess[bytes]) -> str:
    lines = process.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
    return " | ".join(lines)


def encode_jpeg(decoded: Decoded, work: Path, tools: Tools) -> Path:
    """JPEG quality 84, progressive. EXIF не пишется, ICC — как был."""
    out = work / "result.jpg"
    image = decoded.image if decoded.image.mode in ("RGB", "L") else decoded.image.convert("RGB")
    if tools.cjpeg is None:
        image.save(
            out,
            "JPEG",
            quality=JPEG_QUALITY,
            optimize=True,
            progressive=True,
            icc_profile=decoded.icc,
        )
        return out
    pixels = work / "pixels.ppm"  # cjpeg читает PPM/PGM без лишних зависимостей
    image.save(pixels, "PPM")
    cmd = [tools.cjpeg, "-quality", str(JPEG_QUALITY), "-progressive", "-optimize"]
    if decoded.icc:
        profile = work / "profile.icc"
        profile.write_bytes(decoded.icc)
        cmd += ["-icc", str(profile)]
    cmd += ["-outfile", str(out), str(pixels)]
    try:
        process = _run(cmd)
    finally:
        pixels.unlink(missing_ok=True)
    if process.returncode != 0 or not out.exists():
        raise MediaError(f"cjpeg: {_tail(process) or 'ошибка'}")
    return out


# --- PNG ------------------------------------------------------------------------------------------


def png_facts(data: bytes) -> tuple[bool, int]:
    """(анимированный ли APNG, глубина цвета в битах) по заголовкам до первого IDAT."""
    animated, depth, pos = False, 8, 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        if kind == b"IHDR" and pos + 17 <= len(data):
            depth = data[pos + 16]
        elif kind == b"acTL":
            animated = True
        elif kind == b"IDAT":
            break
        pos += 12 + length
    return animated, depth


def _is_srgb(icc: bytes) -> bool:
    try:
        description = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc)))
    except Exception:
        return False
    return "srgb" in description.lower()


def _pngquant(data: bytes, work: Path, binary: str) -> bytes | None:
    source, out = work / "quant-in.png", work / "quant-out.png"
    source.write_bytes(data)
    out.unlink(missing_ok=True)
    cmd = [
        binary,
        f"--quality={PNGQUANT_QUALITY}",
        "--skip-if-larger",
        "--strip",
        "--force",
        "--output",
        str(out),
        "--",
        str(source),
    ]
    try:
        process = _run(cmd)
    finally:
        source.unlink(missing_ok=True)
    if process.returncode in PNGQUANT_SKIPPED:
        return None  # на таком качестве не вышло или стало не меньше: пойдёт только lossless
    if process.returncode != 0 or not out.exists():
        raise MediaError(f"pngquant: {_tail(process) or 'ошибка'}")
    try:
        return out.read_bytes()
    finally:
        out.unlink(missing_ok=True)


def _oxipng(data: bytes) -> bytes | None:
    if oxipng is None:
        return None
    try:
        return oxipng.optimize_from_memory(
            data,
            level=OXIPNG_LEVEL,
            strip=oxipng.StripChunks.safe(),  # iCCP и прочее, что влияет на показ, остаётся
            timeout=OXIPNG_TIMEOUT_SEC,
        )
    except Exception:  # битый или необычный PNG: оставляем, что есть
        return None


def optimize_png(data: bytes, work: Path, tools: Tools, icc: bytes | None) -> bytes:
    """Лучший из вариантов: квантование (если уместно) и затем lossless-оптимизация."""
    _, depth = png_facts(data)
    best = data
    # Квантование переводит картинку в 8 бит и в sRGB: для 16-битных и для снимков с «чужим»
    # профилем (Display P3, Adobe RGB) цвета поехали бы — им достаётся только lossless.
    quantize_ok = tools.pngquant is not None and depth <= 8 and (icc is None or _is_srgb(icc))
    if quantize_ok:
        quantized = _pngquant(data, work, tools.pngquant)  # type: ignore[arg-type]
        if quantized is not None and len(quantized) < len(best):
            best = quantized
    if tools.oxipng:
        optimized = _oxipng(best)
        if optimized is not None and len(optimized) < len(best):
            best = optimized
    return best


def _png_from_pixels(decoded: Decoded) -> bytes:
    buffer = io.BytesIO()
    image = decoded.image
    if image.mode not in ("RGB", "RGBA", "L", "LA"):
        image = image.convert("RGBA" if decoded.alpha else "RGB")
    image.save(buffer, "PNG", icc_profile=decoded.icc)
    return buffer.getvalue()


@dataclass(frozen=True, slots=True)
class Probe:
    mode: str
    icc: bytes | None
    rotated: bool  # в EXIF стоит поворот, который нужно применить к пикселям


def probe(src: Path) -> Probe:
    """Заголовок картинки без разбора пикселей. Битый файл — `MediaError`, не исключение Pillow."""
    try:
        with Image.open(src) as image:
            try:
                orientation = int(image.getexif().get(0x0112, 1) or 1)
            except Exception:
                orientation = 1
            return Probe(image.mode, image.info.get("icc_profile"), orientation != 1)
    except Exception as exc:
        raise MediaError(f"Не удалось открыть изображение: {exc}") from exc


# --- общий вход -----------------------------------------------------------------------------------


def compress(src: Path, ext: str, work: Path, tools: Tools | None = None) -> Result:
    """Сжимает `src` (расширение `ext`). Возвращает итог, сам файл не трогает.

    `MediaError` — файл не открылся или кодировщик упал; вызывающий оставит оригинал.
    """
    route = ROUTES.get(ext.lower())
    if route is None:
        return Result("skipped", note="формат не пережимается")
    tools = tools or detect_tools()
    work.mkdir(parents=True, exist_ok=True)
    before = src.stat().st_size

    if route == "convert":
        # Конвертация нужна для совместимости, а не ради веса: берём результат при любом размере.
        decoded = decode(src)
        if decoded.alpha:
            data = optimize_png(_png_from_pixels(decoded), work, tools, decoded.icc)
            out = work / "result.png"
            out.write_bytes(data)
            return Result("done", out, "png", MIME["png"], "конвертация в PNG")
        out = encode_jpeg(decoded, work, tools)
        return Result("done", out, "jpg", MIME["jpg"], "конвертация в JPEG")

    if route == "jpeg":
        if probe(src).mode in ("CMYK", "YCCK"):
            return Result("skipped", note="CMYK не пережимаем: цвета могут уехать")
        out = encode_jpeg(decode(src), work, tools)
        ext_out = "jpeg" if ext.lower() == "jpeg" else "jpg"  # имя файла не меняем
    else:  # png
        data = src.read_bytes()
        animated, _ = png_facts(data)
        if animated:
            return Result("skipped", note="анимированный PNG не трогаем")
        head = probe(src)
        if head.rotated:
            data = _png_from_pixels(decode(src))
        out = work / "result.png"
        out.write_bytes(optimize_png(data, work, tools, head.icc))
        ext_out = "png"

    after = out.stat().st_size
    if after > before * (1 - MIN_GAIN):
        out.unlink(missing_ok=True)
        return Result("small_gain", note=f"выигрыш меньше {int(MIN_GAIN * 100)}%")
    return Result("done", out, ext_out, MIME[ext_out], "сжато")
