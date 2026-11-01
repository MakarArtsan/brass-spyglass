"""План экспорта в DaVinci Resolve и Premiere Pro: что и в каком порядке ложится на таймлайн.

Чистые функции без БД и файлов, поэтому порядок, длительности «с точностью до кадра»,
размещение звука и субтитров проверяются тестами (ТЗ: «pytest на metrics.py и экспорт»).

Правила (ТЗ, «Экспорт в DaVinci Resolve и Premiere Pro»):
- на таймлайн идут только готовые финальные файлы (статус «Готово» и выбран финальный файл);
- порядок — порядок сцен в трекере (`order`), номер сцены на порядок не влияет;
- неготовые пропускаются; с галочкой «Плейсхолдеры» вместо них ставится карточка-заглушка
  на плановую длительность, чтобы были видны дыры в хронометраже;
- «Уровень: шоты» — вместо сцен берутся готовые дубли шотов по порядку внутри сцен.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app import metrics
from app.constants import Status

FPS = 24
START_FRAME = 3600 * FPS  # старт секвенции 01:00:00:00
SAMPLE_RATE = 48_000

DONE = Status.DONE.value
CUT = Status.CUT.value


class Level(StrEnum):
    SCENES = "scenes"
    SHOTS = "shots"


@dataclass(frozen=True, slots=True)
class FileRef:
    """Файл, который кладётся в пакет: путь на диске относительно /data/files и имя для пакета."""

    id: int
    path: str | None
    name: str
    version_no: int
    duration_sec: float | None
    kind: str = "video"


@dataclass(frozen=True, slots=True)
class SceneX:
    id: int
    number: int
    title: str
    order: int
    status: str
    planned_sec: float
    final: FileRef | None


@dataclass(frozen=True, slots=True)
class ShotX:
    id: int
    scene_id: int
    code: str
    order: int
    status: str
    duration_sec: float
    final: FileRef | None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class Clip:
    kind: str  # "file" | "placeholder"
    name: str  # так клип называется на таймлайне
    package_path: str  # куда лежит в zip: Media/Scenes/S01_dva-zerkala_v3.mov
    scene_id: int
    scene_number: int
    scene_title: str
    shot_id: int | None
    status: str
    start_frame: int  # от начала секвенции (01:00:00:00 прибавляется при записи)
    frames: int
    layout_start: float  # где этот кусок стоит в трекере, сек — по нему ищется звук
    layout_end: float
    file: FileRef | None
    label: str  # подпись карточки-заглушки
    shot_code: str | None = None

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.frames


# --- имена ---------------------------------------------------------------------------------------

_TRANSLIT = {
    **dict(zip("абвгдезийклмнопрстуфыэ", "abvgdezijklmnoprstufye", strict=True)),
    "ё": "e", "ж": "zh", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ь": "", "ю": "yu", "я": "ya",
}  # fmt: skip


def slug(text: str, limit: int = 40) -> str:
    """«Два зеркала» → «dva-zerkala»: имена файлов в пакете латиницей,
    чтобы их не ломали ни Windows, ни Resolve."""
    out = "".join(_TRANSLIT.get(ch, ch) for ch in text.lower())
    out = re.sub(r"[^a-z0-9]+", "-", out).strip("-")
    return out[:limit].strip("-") or "scene"


def extension(name: str) -> str:
    match = re.search(r"\.([A-Za-z0-9]{1,8})$", name or "")
    return f".{match.group(1).lower()}" if match else ".mov"


def frames_of(seconds: float, fps: int = FPS) -> int:
    """Секунды → кадры, не меньше одного кадра."""
    return max(1, round(seconds * fps))


def scene_file_name(scene: SceneX, file: FileRef) -> str:
    return f"S{scene.number:02d}_{slug(scene.title)}_v{file.version_no}{extension(file.name)}"


def shot_file_name(scene: SceneX, shot: ShotX, file: FileRef) -> str:
    return f"S{scene.number:02d}_{shot.code}_v{file.version_no}{extension(file.name)}"


# --- план ---------------------------------------------------------------------------------------


def plan_timeline(
    scenes: Sequence[SceneX],
    shots: Sequence[ShotX],
    *,
    level: Level = Level.SCENES,
    placeholders: bool = False,
    fps: int = FPS,
) -> list[Clip]:
    layout = metrics.film_layout(
        [metrics.SceneIn(s.id, s.order, s.planned_sec, s.status) for s in scenes],
        [metrics.ShotLay(s.id, s.scene_id, s.order, s.duration_sec, s.status) for s in shots],
    )
    by_scene = {s.id: s for s in scenes}
    shot_by_id = {s.id: s for s in shots}
    clips: list[Clip] = []
    cursor = 0

    def add(
        scene: SceneX,
        *,
        shot: ShotX | None,
        file: FileRef | None,
        planned: float,
        span: tuple[float, float],
    ) -> None:
        nonlocal cursor
        ready = file is not None
        seconds = file.duration_sec if file is not None and file.duration_sec else planned
        frames = frames_of(seconds, fps)
        number = len(clips) + 1
        if shot is None:
            label = f"Сцена {scene.number} · {scene.title}"
            real = scene_file_name(scene, file) if file else ""
            placeholder = f"P{number:02d}_S{scene.number:02d}_{slug(scene.title)}.mov"
        else:
            label = f"Шот {shot.code}"
            real = shot_file_name(scene, shot, file) if file else ""
            placeholder = f"P{number:02d}_S{scene.number:02d}_{shot.code}.mov"
        folder = "Scenes" if shot is None else "Shots"
        clips.append(
            Clip(
                kind="file" if ready else "placeholder",
                name=real if ready else placeholder,
                package_path=f"Media/{folder}/{real}"
                if ready
                else f"Media/Placeholders/{placeholder}",
                scene_id=scene.id,
                scene_number=scene.number,
                scene_title=scene.title,
                shot_id=shot.id if shot else None,
                status=(shot.status if shot else scene.status),
                start_frame=cursor,
                frames=frames,
                layout_start=span[0],
                layout_end=span[1],
                file=file,
                label=label,
                shot_code=shot.code if shot else None,
            )
        )
        cursor += frames

    for span in layout:
        scene = by_scene[span.scene_id]
        if level is Level.SCENES:
            ready = scene.status == DONE and scene.final is not None
            if ready or placeholders:
                add(
                    scene,
                    shot=None,
                    file=scene.final if ready else None,
                    planned=scene.planned_sec,
                    span=(span.start_sec, span.end_sec),
                )
            continue
        for sp in span.shots:
            shot = shot_by_id[sp.shot_id]
            ready = shot.status == DONE and shot.final is not None
            if ready or placeholders:
                add(
                    scene,
                    shot=shot,
                    file=shot.final if ready else None,
                    planned=shot.duration_sec,
                    span=(sp.start_sec, sp.end_sec),
                )
    return clips


# --- звук и субтитры -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CueX:
    id: int
    code: str
    type: str
    who: str | None
    text_en: str | None
    scene_id: int | None
    shot_id: int | None
    offset_sec: float
    file: FileRef | None  # звуковой файл, если он есть


@dataclass(frozen=True, slots=True)
class Placement:
    cue: CueX
    lane: int  # 1 — реплики, 2 — звук, 3 — музыка
    start_frame: int
    frames: int


@dataclass(frozen=True, slots=True)
class Subtitle:
    index: int
    start_frame: int
    end_frame: int
    text: str


READ_CHARS_PER_SEC = 14.0
MIN_SUBTITLE_SEC = 1.5
MAX_SUBTITLE_SEC = 7.0


def subtitle_seconds(text: str, file_seconds: float | None) -> float:
    if file_seconds:
        return file_seconds
    return min(MAX_SUBTITLE_SEC, max(MIN_SUBTITLE_SEC, len(text) / READ_CHARS_PER_SEC))


def _layout_of(scenes: Sequence[SceneX], shots: Sequence[ShotX]) -> list[metrics.SceneSpan]:
    return metrics.film_layout(
        [metrics.SceneIn(s.id, s.order, s.planned_sec, s.status) for s in scenes],
        [metrics.ShotLay(s.id, s.scene_id, s.order, s.duration_sec, s.status) for s in shots],
    )


def _locate(clips: Sequence[Clip], layout_sec: float) -> Clip | None:
    for clip in clips:
        if clip.layout_start <= layout_sec < clip.layout_end:
            return clip
    return None


def place_cues(
    cues: Sequence[CueX],
    scenes: Sequence[SceneX],
    shots: Sequence[ShotX],
    clips: Sequence[Clip],
    fps: int = FPS,
) -> list[tuple[CueX, int, int, float]]:
    """Где реплика стоит на собранном таймлайне:
    (реплика, кадр начала, кадр конца, длительность сек).

    Положение внутри сцены сохраняется: если готовый файл сцены длиннее или короче плана, реплика
    остаётся на том же сдвиге от начала сцены, а не растягивается. Реплика, чей кусок не попал на
    таймлайн, пропускается (картинки нет — субтитры не нужны).
    """
    layout = _layout_of(scenes, shots)
    placed: list[tuple[CueX, int, int, float]] = []
    for cue in cues:
        span = metrics.cue_span(
            metrics.CueIn(
                cue.id,
                cue.scene_id,
                cue.shot_id,
                cue.offset_sec,
                cue.file.duration_sec if cue.file else None,
            ),
            layout,
        )
        if span is None:
            continue
        clip = _locate(clips, span[0])
        if clip is None:
            continue
        offset = round((span[0] - clip.layout_start) * fps)
        start = clip.start_frame + min(max(0, offset), clip.frames - 1)
        seconds = (
            subtitle_seconds(cue.text_en or "", cue.file.duration_sec if cue.file else None)
            if cue.type == "dialogue"
            else (
                cue.file.duration_sec if cue.file and cue.file.duration_sec else span[1] - span[0]
            )
        )
        end = min(start + frames_of(seconds, fps), clip.end_frame)
        if end <= start:
            continue
        placed.append((cue, start, end, seconds))
    return placed


def audio_placements(
    placed: Sequence[tuple[CueX, int, int, float]],
) -> list[Placement]:
    """Звуковые клипы на дорожки A1–A3: только те, у кого есть файл (и дорожка у типа есть)."""
    out: list[Placement] = []
    for cue, start, end, _ in placed:
        lane = metrics.SOUND_LANES.get(cue.type)
        if lane is None or cue.file is None:
            continue
        out.append(Placement(cue, lane, start, end - start))
    return out


def subtitles(placed: Sequence[tuple[CueX, int, int, float]]) -> list[Subtitle]:
    """Английские субтитры из реплик: таймкоды считаются по собранному таймлайну."""
    rows = sorted(
        (
            (start, end, cue)
            for cue, start, end, _ in placed
            if cue.type == "dialogue" and cue.text_en
        ),
        key=lambda r: (r[0], r[2].id),
    )
    return [
        Subtitle(i, start, end, (cue.text_en or "").strip())
        for i, (start, end, cue) in enumerate(rows, 1)
    ]


def _srt_time(frame: int, fps: int) -> str:
    total_ms = round(frame * 1000 / fps)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def format_srt(items: Sequence[Subtitle], fps: int = FPS) -> str:
    """SRT с временем от начала таймлайна (Resolve ставит субтитры от старта секвенции)."""
    blocks = [
        f"{s.index}\n{_srt_time(s.start_frame, fps)} --> {_srt_time(s.end_frame, fps)}\n{s.text}\n"
        for s in items
    ]
    return "\n".join(blocks)


def timecode(frame: int, fps: int = FPS) -> str:
    """Кадр от начала → «01:00:03:12» (с учётом старта секвенции)."""
    total = frame + 3600 * fps  # старт секвенции 01:00:00:00
    hours, rest = divmod(total, 3600 * fps)
    minutes, rest = divmod(rest, 60 * fps)
    seconds, frames = divmod(rest, fps)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"
