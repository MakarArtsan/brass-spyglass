"""Обработка медиа: ffprobe/ffmpeg через subprocess, Pillow, pypdfium2. Только чистые функции
над файлами — ни БД, ни HTTP. Оригиналы не меняются: превью и прокси пишутся отдельно."""

import array
import io
import json
import math
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pillow_heif
import pypdfium2
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()

THUMB_PX = 400
PREVIEW_PX = 1600
POSTER_PX = 1280
WAVE_BUCKETS = 800
PROXY_HEIGHT = 720

PLAYABLE_PIX_FMTS = {"yuv420p", "yuvj420p"}


class MediaError(Exception):
    """Файл не удалось разобрать (повреждён, неподдерживаемый формат)."""


@dataclass(frozen=True, slots=True)
class MediaInfo:
    duration: float | None
    width: int | None
    height: int | None
    fps: float | None
    vcodec: str | None
    acodec: str | None
    pix_fmt: str | None
    container: str


def _run(cmd: list[str], timeout: float | None = 600) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout, check=True)
    except subprocess.CalledProcessError as exc:
        tail = exc.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise MediaError(" | ".join(tail) or f"{cmd[0]} завершился с ошибкой") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{cmd[0]}: превышено время обработки") from exc
    except FileNotFoundError as exc:
        raise MediaError(f"{cmd[0]} не установлен") from exc


def _fps(value: str | None) -> float | None:
    if not value or "/" not in value:
        return None
    num, _, den = value.partition("/")
    try:
        return round(float(num) / float(den), 3) if float(den) else None
    except ValueError:
        return None


def probe(path: Path) -> MediaInfo:
    out = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=120,
    )
    data = json.loads(out.stdout or b"{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    try:
        duration = float(fmt["duration"]) if fmt.get("duration") not in (None, "N/A") else None
    except (KeyError, ValueError):
        duration = None
    return MediaInfo(
        duration=duration,
        width=video.get("width") if video else None,
        height=video.get("height") if video else None,
        fps=_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")) if video else None,
        vcodec=video.get("codec_name") if video else None,
        acodec=audio.get("codec_name") if audio else None,
        pix_fmt=video.get("pix_fmt") if video else None,
        container=fmt.get("format_name", ""),
    )


def browser_playable(info: MediaInfo) -> bool:
    """Играется ли исходник в браузере; иначе нужен прокси H.264 720p (ProRes, 4:2:2 и т. п.)."""
    if info.vcodec is None:
        return False
    containers = info.container.split(",")
    if info.vcodec == "h264" and info.pix_fmt in PLAYABLE_PIX_FMTS:
        return "mp4" in containers or "mov" in containers
    if info.vcodec in {"vp8", "vp9", "av1"}:
        return "webm" in containers
    return False


def _save_jpeg(image: Image.Image, dest: Path, max_side: int) -> None:
    copy = image.copy()
    copy.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    copy.save(dest, "JPEG", quality=85, optimize=True)


def _open_rgb(path: Path) -> Image.Image:
    try:
        with Image.open(path) as raw:
            raw.load()
            return ImageOps.exif_transpose(raw).convert("RGB")
    except Exception as exc:  # битый файл, неизвестный формат
        raise MediaError(f"Не удалось открыть изображение: {exc}") from exc


def image_variants(src: Path, out_dir: Path) -> tuple[int, int]:
    """Превью 400 и 1600 px (HEIC → JPG). Возвращает размеры исходной картинки."""
    image = _open_rgb(src)
    _save_jpeg(image, out_dir / "preview.jpg", PREVIEW_PX)
    _save_jpeg(image, out_dir / "thumb.jpg", THUMB_PX)
    return image.size


def pdf_first_page(src: Path, out_dir: Path) -> tuple[int, int]:
    try:
        document = pypdfium2.PdfDocument(str(src))
        page = document[0]
        image = page.render(scale=1.5).to_pil().convert("RGB")
    except Exception as exc:
        raise MediaError(f"Не удалось открыть PDF: {exc}") from exc
    _save_jpeg(image, out_dir / "preview.jpg", PREVIEW_PX)
    _save_jpeg(image, out_dir / "thumb.jpg", THUMB_PX)
    return image.size


def video_poster(src: Path, out_dir: Path, duration: float | None) -> None:
    """Постер-кадр (1280 px) и превью 400 px. Кадр берём чуть после начала: вдруг там чёрный."""
    out_dir.mkdir(parents=True, exist_ok=True)
    poster = out_dir / "poster.jpg"
    moments = [min(1.0, (duration or 0) / 2), 0.0]
    for at in moments:
        try:
            _run(
                [
                    "ffmpeg", "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(src),
                    "-frames:v", "1",
                    "-vf", f"scale='min({POSTER_PX},iw)':-2", "-q:v", "3", str(poster),
                ],
                timeout=120,
            )  # fmt: skip
        except MediaError:
            continue
        if poster.exists() and poster.stat().st_size > 0:
            break
    else:
        raise MediaError("Не удалось получить кадр из видео")
    with Image.open(poster) as image:
        _save_jpeg(image.convert("RGB"), out_dir / "thumb.jpg", THUMB_PX)


def make_proxy(
    src: Path,
    dest: Path,
    duration: float | None,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """Прокси H.264 720p для исходников, которые браузер не играет."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part.mp4")
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-nostats", "-progress", "pipe:1", "-i", str(src),
        "-vf", f"scale=-2:'min({PROXY_HEIGHT},ih)'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp),
    ]  # fmt: skip
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        match = re.match(r"out_time_(?:us|ms)=(\d+)", line)
        if match and duration and on_progress:
            seconds = int(match.group(1)) / 1_000_000
            on_progress(min(0.99, seconds / duration))
    code = process.wait()
    if code != 0 or not tmp.exists():
        stderr = (process.stderr.read() if process.stderr else "").strip().splitlines()[-2:]
        tmp.unlink(missing_ok=True)
        raise MediaError(" | ".join(stderr) or "ffmpeg не смог сделать прокси")
    tmp.replace(dest)


def make_card_video(
    card_png: Path, dest: Path, seconds: float, fps: int = 24, sample_rate: int = 48_000
) -> None:
    """Карточка-заглушка для экспорта: статичная картинка на `seconds` секунд, H.264 + тихая дорожка
    звука (многие монтажки ждут звук у каждого клипа). Длина — ровно в кадры,
    чтобы таймлайн сошёлся."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, round(seconds * fps))
    tmp = dest.with_suffix(".part.mov")
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-nostats",
        "-loop", "1", "-framerate", str(fps), "-i", str(card_png),
        "-f", "lavfi", "-i", f"anullsrc=r={sample_rate}:cl=stereo",
        "-frames:v", str(frames), "-t", f"{frames / fps:.4f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-r", str(fps), "-c:a", "aac", "-b:a", "64k", "-shortest", str(tmp),
    ]  # fmt: skip
    _run(cmd, timeout=300)
    if not tmp.exists():
        raise MediaError("ffmpeg не сделал карточку-заглушку")
    tmp.replace(dest)


def waveform(src: Path, duration: float | None, buckets: int = WAVE_BUCKETS) -> list[float]:
    """Огибающая громкости для плеера: `buckets` значений 0…1. Читает поток ffmpeg кусками,
    поэтому длинные файлы не копятся в памяти."""
    rate = 8000
    total = int((duration or 0) * rate)
    per_bucket = max(1, math.ceil(total / buckets)) if total else rate // 10
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(src), "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    peaks: list[int] = []
    current = 0
    count = 0
    leftover = b""
    while chunk := process.stdout.read(1 << 16):
        samples = array.array("h")
        data = leftover + chunk
        usable = len(data) - (len(data) % 2)
        samples.frombytes(data[:usable])
        leftover = data[usable:]
        for value in samples:
            current = max(current, abs(value))
            count += 1
            if count == per_bucket:
                peaks.append(current)
                current = count = 0
    if count:
        peaks.append(current)
    if process.wait() != 0:
        raise MediaError("ffmpeg не смог прочитать звук")
    top = max(peaks, default=0) or 1
    return [round(p / top, 3) for p in peaks]


def thumb_from_bytes(data: bytes, dest: Path) -> None:
    """Превью 400 px из байтов (миниатюра Telegram); перекодируется, чужие байты не остаются."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except Exception as exc:
        raise MediaError(f"Не удалось прочитать миниатюру: {exc}") from exc
    _save_jpeg(image, dest, THUMB_PX)
