"""Сборка zip-пакета для DaVinci Resolve и Premiere Pro (ТЗ, «Экспорт»).

В пакете: `timeline_fcp7.xml` (основной), `timeline.otio` (запасной), `subtitles_en.srt`, сами файлы
в `Media/…` и `README.txt`. Файл проекта Resolve снаружи собрать нельзя, поэтому отдаётся таймлайн
плюс файлы: при импорте таймлайна обе программы сами заносят всё, на что он ссылается, в медиапул.

Модуль не знает про БД: он получает готовый план (`export_plan`) и пути файлов.
"""

import logging
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import opentimelineio as otio
from opentimelineio.opentime import RationalTime as RT
from opentimelineio.opentime import TimeRange as TR
from PIL import Image, ImageDraw, ImageFont

from app import export_plan as ep
from app import media
from app.export_plan import Clip, FileRef, Level, Placement, Subtitle

log = logging.getLogger(__name__)

STATUS_RU = {
    "not_started": "Не начато",
    "in_progress": "В работе",
    "review": "На проверке",
    "rework": "Доработать",
    "done": "Готово",
    "cut": "Вырезано",
}
TARGET_RU = {"resolve": "DaVinci Resolve", "premiere": "Adobe Premiere Pro"}

CARD_BACKGROUND = (20, 30, 50)
CARD_TEXT = (240, 220, 160)
CARD_SUBTEXT = (160, 170, 190)
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)


@dataclass(frozen=True, slots=True)
class Options:
    target: str = "resolve"  # resolve | premiere
    level: Level = Level.SCENES
    placeholders: bool = False
    references: bool = False
    media_root: str = ""  # папка у монтажёра, от которой XML пишет пути (D:/BrassSpyglass/)
    base_url: str = ""  # адрес сайта: ссылка на карточку в комментарии маркера


@dataclass(frozen=True, slots=True)
class Reference:
    file: FileRef
    package_path: str


@dataclass(slots=True)
class PackageSpec:
    project_title: str
    options: Options
    clips: list[Clip]
    placements: list[Placement]
    subtitles: list[Subtitle]
    references: list[Reference]
    skipped: list[str]
    files_dir: Path
    fps: int = ep.FPS
    width: int = 1920
    height: int = 1080
    font: Path | None = None


@dataclass(slots=True)
class PackageResult:
    size_bytes: int = 0
    clips: int = 0
    placeholders: int = 0
    audio: int = 0
    subtitles: int = 0
    references: int = 0
    frames: int = 0
    skipped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "size_bytes": self.size_bytes,
            "clips": self.clips,
            "placeholders": self.placeholders,
            "audio": self.audio,
            "subtitles": self.subtitles,
            "references": self.references,
            "frames": self.frames,
            "skipped": self.skipped,
        }


# --- пути ----------------------------------------------------------------------------------------


def media_url(root: str, package_path: str) -> str:
    """Путь клипа в XML: от папки, которую монтажёр указал у себя на диске.
    Без папки — относительный."""
    base = root.strip().replace("\\", "/").rstrip("/")
    full = f"{base}/{package_path}" if base else package_path
    quoted = quote(full, safe="/:")
    if re.match(r"^[A-Za-z]:", base):
        return f"file://localhost/{quoted}"
    if base.startswith("/"):
        return f"file://localhost{quoted}"
    return quoted


def find_font() -> Path | None:
    """Шрифт с кириллицей для карточек-заглушек. Нет шрифта — карточка с латинской подписью."""
    override = os.environ.get("EXPORT_FONT")
    for candidate in ([override] if override else []) + list(FONT_CANDIDATES):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


# --- карточки-заглушки ---------------------------------------------------------------------------


def _duration_text(frames: int, fps: int) -> str:
    seconds = frames / fps
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def card_lines(clip: Clip, fps: int, has_font: bool) -> tuple[str, str]:
    length = _duration_text(clip.frames, fps)
    if has_font:
        return clip.label, f"Нет файла · {length}"
    head = f"SHOT {clip.shot_code}" if clip.shot_code else f"SCENE {clip.scene_number}"
    return head, f"NO FILE · {length}"


def render_card(clip: Clip, dest: Path, spec: PackageSpec) -> None:
    image = Image.new("RGB", (spec.width, spec.height), CARD_BACKGROUND)
    draw = ImageDraw.Draw(image)
    first, second = card_lines(clip, spec.fps, spec.font is not None)
    if spec.font is not None:
        big = ImageFont.truetype(str(spec.font), size=spec.height // 12)
        small = ImageFont.truetype(str(spec.font), size=spec.height // 20)
    else:
        big = ImageFont.load_default(size=spec.height // 12)
        small = ImageFont.load_default(size=spec.height // 20)
    for text, font, color, y in (
        (first, big, CARD_TEXT, spec.height * 0.42),
        (second, small, CARD_SUBTEXT, spec.height * 0.58),
    ):
        width = draw.textlength(text, font=font)
        draw.text(((spec.width - width) / 2, y), text, font=font, fill=color)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, format="PNG")


# --- OpenTimelineIO ------------------------------------------------------------------------------


def _marker_color(clip: Clip) -> otio.schema.MarkerColor:
    if clip.kind == "placeholder":
        return otio.schema.MarkerColor.RED
    return (
        otio.schema.MarkerColor.GREEN if clip.status == "done" else otio.schema.MarkerColor.YELLOW
    )


def marker_comment(clip: Clip, base_url: str) -> str:
    status = STATUS_RU.get(clip.status, clip.status)
    note = f"Статус: {status}" + (" · нет файла, заглушка" if clip.kind == "placeholder" else "")
    if base_url:
        path = f"/shots?shot={clip.shot_id}" if clip.shot_id else f"/scenes/{clip.scene_id}"
        note += f" · {base_url.rstrip('/')}{path}"
    return note


def pack_lane(items: list[Placement]) -> list[list[Placement]]:
    """Звуки одной дорожки: накладывающиеся уходят на следующую дорожку той же группы."""
    tracks: list[list[Placement]] = []
    ends: list[int] = []
    for item in sorted(items, key=lambda p: (p.start_frame, p.cue.id)):
        for i, end in enumerate(ends):
            if item.start_frame >= end:
                tracks[i].append(item)
                ends[i] = item.start_frame + item.frames
                break
        else:
            tracks.append([item])
            ends.append(item.start_frame + item.frames)
    return tracks


def audio_package_path(placement: Placement) -> str:
    file = placement.cue.file
    assert file is not None
    return f"Media/Sound/{placement.cue.code}_v{file.version_no}{ep.extension(file.name)}"


def build_timeline(spec: PackageSpec) -> tuple[otio.schema.Timeline, dict[str, str]]:
    """Секвенция из настроек проекта; V1 — сцены встык, A1–A3 — звук из листа «Звук».
    Возвращает таймлайн и комментарии маркеров (OTIO-адаптер FCP7 их не пишет, дописываем в XML)."""
    rate = spec.fps
    timeline = otio.schema.Timeline(
        name=spec.project_title, global_start_time=RT(ep.START_FRAME, rate)
    )
    video = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    comments: dict[str, str] = {}
    seen_scenes: set[int] = set()
    for clip in spec.clips:
        full = TR(RT(0, rate), RT(clip.frames, rate))
        reference = otio.schema.ExternalReference(
            target_url=media_url(spec.options.media_root, clip.package_path), available_range=full
        )
        item = otio.schema.Clip(name=clip.name, media_reference=reference, source_range=full)
        if clip.scene_id not in seen_scenes:  # маркер на каждой сцене: номер и название
            seen_scenes.add(clip.scene_id)
            name = f"{clip.scene_number} · {clip.scene_title}"
            comment = marker_comment(clip, spec.options.base_url)
            comments[name] = comment
            item.markers.append(
                otio.schema.Marker(
                    name=name,
                    marked_range=TR(RT(0, rate), RT(1, rate)),
                    color=_marker_color(clip),
                    comment=comment,
                )
            )
        video.append(item)
    timeline.tracks.append(video)

    for lane in (1, 2, 3):
        group = [p for p in spec.placements if p.lane == lane]
        for number, items in enumerate(pack_lane(group), 1):
            track = otio.schema.Track(
                name=f"A{lane}" if number == 1 else f"A{lane}.{number}",
                kind=otio.schema.TrackKind.Audio,
            )
            cursor = 0
            for placement in items:
                if placement.start_frame > cursor:
                    gap = TR(RT(0, rate), RT(placement.start_frame - cursor, rate))
                    track.append(otio.schema.Gap(source_range=gap))
                file = placement.cue.file
                assert file is not None
                available = TR(
                    RT(0, rate),
                    RT(max(placement.frames, ep.frames_of(file.duration_sec or 0, rate)), rate),
                )
                audio = otio.schema.Clip(
                    name=f"{placement.cue.code}"
                    + (f" · {placement.cue.who}" if placement.cue.who else ""),
                    media_reference=otio.schema.ExternalReference(
                        target_url=media_url(
                            spec.options.media_root, audio_package_path(placement)
                        ),
                        available_range=available,
                    ),
                    source_range=TR(RT(0, rate), RT(placement.frames, rate)),
                )
                track.append(audio)
                cursor = placement.start_frame + placement.frames
            timeline.tracks.append(track)
    return timeline, comments


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    element = ET.SubElement(parent, tag)
    if text is not None:
        element.text = text
    return element


def finish_fcp_xml(path: Path, spec: PackageSpec, comments: dict[str, str]) -> None:
    """Дописывает в XML то, что OTIO-адаптер оставляет пустым и без чего Resolve и Premiere
    теряют настройки секвенции: размер кадра, параметры звука, комментарии маркеров."""
    tree = ET.parse(path)
    root = tree.getroot()
    rate = str(spec.fps)
    for sequence in root.iter("sequence"):
        media_node = sequence.find("media")
        if media_node is None:
            continue
        video = media_node.find("video")
        if video is not None:
            old = video.find("format")
            if old is not None:
                video.remove(old)
            fmt = ET.Element("format")
            sc = _sub(fmt, "samplecharacteristics")
            r = _sub(sc, "rate")
            _sub(r, "timebase", rate)
            _sub(r, "ntsc", "FALSE")
            _sub(sc, "width", str(spec.width))
            _sub(sc, "height", str(spec.height))
            _sub(sc, "anamorphic", "FALSE")
            _sub(sc, "pixelaspectratio", "square")
            _sub(sc, "fielddominance", "none")
            _sub(sc, "colordepth", "24")
            video.insert(0, fmt)
        audio = media_node.find("audio")
        if audio is not None:
            fmt = ET.Element("format")
            sc = _sub(fmt, "samplecharacteristics")
            _sub(sc, "depth", "16")
            _sub(sc, "samplerate", str(ep.SAMPLE_RATE))
            audio.insert(0, fmt)
    for marker in root.iter("marker"):
        name = marker.findtext("name") or ""
        if name in comments and marker.find("comment") is None:
            comment = ET.Element("comment")
            comment.text = comments[name]
            marker.insert(1, comment)
    ET.indent(tree, space="    ")
    body = ET.tostring(root, encoding="unicode")
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body + "\n", encoding="utf-8"
    )


# --- README --------------------------------------------------------------------------------------


def readme(spec: PackageSpec, result: PackageResult) -> str:
    o = spec.options
    root = o.media_root.strip() or "(папка не указана: пути в XML относительные)"
    lines = [
        f"The Brass Spyglass — пакет для {TARGET_RU.get(o.target, o.target)}",
        "=" * 60,
        "",
        f"Секвенция: {spec.width}×{spec.height}, {spec.fps} к/с, звук 48 кГц, старт 01:00:00:00.",
        f"Уровень: {'сцены' if o.level is Level.SCENES else 'шоты'}. "
        f"Клипов на V1: {result.clips} (заглушек: {result.placeholders}), "
        f"звуковых клипов: {result.audio}, реплик в субтитрах: {result.subtitles}.",
        f"Папка у монтажёра, от которой XML пишет пути: {root}",
        "",
        "ЧТО В ПАКЕТЕ",
        "  timeline_fcp7.xml   основной таймлайн (Final Cut Pro 7 XML): Resolve и Premiere",
        "  timeline.otio       запасной (Resolve 18.5+, новые Premiere; Adobe переносит не всё)",
        "  subtitles_en.srt    английские субтитры из листа «Звук», время — от начала таймлайна",
        "  Media/              готовые файлы: Scenes/ или Shots/, Sound/, Placeholders/"
        + (", References/" if o.references else ""),
        "",
        "КАК ОТКРЫТЬ",
        "  1. Распакуйте архив целиком в папку: "
        + (o.media_root.strip() or "любую (потом перелинкуйте)"),
        "     Структура Media/… должна остаться как в архиве.",
    ]
    if o.target == "resolve":
        lines += [
            "  2. DaVinci Resolve: File → Import → Timeline… → timeline_fcp7.xml.",
            "     Файлы сами попадут в медиапул. Не открылось — timeline.otio (Resolve 18.5+).",
            "  3. Субтитры: File → Import → Subtitle… → subtitles_en.srt.",
        ]
    else:
        lines += [
            "  2. Premiere Pro: File → Import… → timeline_fcp7.xml. Папки (bins) создаст Premiere.",
            "  3. Субтитры: File → Import… → subtitles_en.srt (появятся как титры/captions).",
        ]
    lines += [
        "",
        "ФАЙЛЫ НЕ НАШЛИСЬ?",
        "  Распаковали не туда, где указано в окне экспорта — перелинкуйте одной командой:",
        "  Resolve: правый клик по клипам в медиапуле → Relink Selected Clips…",
        "  Premiere: правый клик по клипу → Link Media… (имена файлов уникальны).",
        "",
        "ПОРЯДОК И ХРОНОМЕТРАЖ",
        "  Клипы стоят в порядке сцен в трекере (номер сцены на порядок не влияет),",
        "  встык, длительность каждого — в кадрах по самому файлу. На каждой сцене стоит маркер:",
        "  номер и название, в комментарии — статус и ссылка на карточку.",
        "",
        "ТАЙМЛАЙН",
    ]
    for clip in spec.clips:
        mark = " [заглушка]" if clip.kind == "placeholder" else ""
        lines.append(
            f"  {ep.timecode(clip.start_frame, spec.fps)}  {clip.frames:>5} к.  {clip.name}{mark}"
        )
    if result.skipped:
        lines += ["", "НЕ ВОШЛО В ТАЙМЛАЙН (не готово или нет финального файла)"]
        lines += [f"  {text}" for text in result.skipped]
    return "\n".join(lines) + "\n"


# --- сборка --------------------------------------------------------------------------------------


class MissingSource(media.MediaError):
    """Файл есть в базе, а на диске его нет."""


def source_files(spec: PackageSpec) -> list[tuple[Path, str]]:
    """Что кладётся в zip: (путь на диске, путь в архиве). Каждый файл один раз."""
    seen: set[str] = set()
    out: list[tuple[Path, str]] = []

    def add(file: FileRef | None, arcname: str) -> None:
        if file is None or arcname in seen:
            return
        seen.add(arcname)
        if not file.path or not (spec.files_dir / file.path).is_file():
            raise MissingSource(f"Файла нет на диске: {file.name}")
        out.append((spec.files_dir / file.path, arcname))

    for clip in spec.clips:
        if clip.kind == "file":
            add(clip.file, clip.package_path)
    for placement in spec.placements:
        add(placement.cue.file, audio_package_path(placement))
    for reference in spec.references:
        add(reference.file, reference.package_path)
    return out


def build_package(
    spec: PackageSpec, dest: Path, on_progress: Callable[[float], None] | None = None
) -> PackageResult:
    """Собирает zip по плану. Оригиналы только читаются; заглушки делает ffmpeg."""
    progress = on_progress or (lambda _value: None)
    sources = source_files(spec)  # ошибка — до долгой работы
    work = Path(tempfile.mkdtemp(prefix="export-", dir=dest.parent))
    try:
        placeholders = [c for c in spec.clips if c.kind == "placeholder"]
        for i, clip in enumerate(placeholders):
            card = work / "cards" / f"{i}.png"
            render_card(clip, card, spec)
            media.make_card_video(card, work / clip.package_path, clip.frames / spec.fps, spec.fps)
            progress(0.2 * (i + 1) / len(placeholders))

        timeline, comments = build_timeline(spec)
        otio.adapters.write_to_file(timeline, str(work / "timeline.otio"), adapter_name="otio_json")
        xml_path = work / "timeline_fcp7.xml"
        otio.adapters.write_to_file(timeline, str(xml_path), adapter_name="fcp_xml")
        finish_fcp_xml(xml_path, spec, comments)
        (work / "subtitles_en.srt").write_text(
            ep.format_srt(spec.subtitles, spec.fps), encoding="utf-8"
        )

        result = PackageResult(
            clips=len(spec.clips),
            placeholders=len(placeholders),
            audio=len(spec.placements),
            subtitles=len(spec.subtitles),
            references=len(spec.references),
            frames=sum(c.frames for c in spec.clips),
            skipped=list(spec.skipped),
        )
        (work / "README.txt").write_text(readme(spec, result), encoding="utf-8")
        progress(0.25)

        part = dest.with_suffix(".part")
        total = sum(path.stat().st_size for path, _ in sources) or 1
        done = 0
        with zipfile.ZipFile(part, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
            for name in ("timeline_fcp7.xml", "timeline.otio", "subtitles_en.srt", "README.txt"):
                archive.write(work / name, arcname=name, compress_type=zipfile.ZIP_DEFLATED)
            for clip in placeholders:
                archive.write(work / clip.package_path, arcname=clip.package_path)
            for path, arcname in sources:
                archive.write(path, arcname=arcname)
                done += path.stat().st_size
                progress(0.25 + 0.74 * done / total)
        part.replace(dest)
        result.size_bytes = dest.stat().st_size
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)
