"""Справочники проекта: статусы, этапы, крупности, инструменты, типы.

Это единственный источник значений. По ним строятся CHECK-ограничения в БД.
`excel_label` — текст из Excel-трекера, по нему импорт сопоставляет значения.
Значения, помеченные TBD, нужно сверить с Krivoe_zerkalo_tracker.xlsx на этапе 1
(см. DECISIONS.md).
"""

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    DIRECTOR = "director"
    TEAM = "team"
    GUEST = "guest"


class Status(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    REWORK = "rework"
    DONE = "done"
    CUT = "cut"


STATUS_EXCEL_LABELS: dict[Status, str] = {
    Status.NOT_STARTED: "Не начато",
    Status.IN_PROGRESS: "В работе",
    Status.REVIEW: "На проверке",
    Status.REWORK: "Доработать",
    Status.DONE: "Готово",
    Status.CUT: "Вырезано",
}


class Priority(StrEnum):  # TBD
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


PRIORITY_EXCEL_LABELS: dict[Priority, str] = {
    Priority.HIGH: "Высокий",
    Priority.MEDIUM: "Средний",
    Priority.LOW: "Низкий",
}


class Stage(StrEnum):  # этапы шота, колонки канбана. TBD
    PROMPT = "prompt"
    GENERATION = "generation"
    SELECTION = "selection"
    POST = "post"
    FINAL = "final"


STAGE_EXCEL_LABELS: dict[Stage, str] = {
    Stage.PROMPT: "Промпт",
    Stage.GENERATION: "Генерация",
    Stage.SELECTION: "Отбор",
    Stage.POST: "Постобработка",
    Stage.FINAL: "Финал",
}


class ShotSize(StrEnum):  # крупности. TBD
    EXTREME_WIDE = "extreme_wide"
    WIDE = "wide"
    MEDIUM = "medium"
    CLOSE = "close"
    EXTREME_CLOSE = "extreme_close"
    INSERT = "insert"


SHOT_SIZE_EXCEL_LABELS: dict[ShotSize, str] = {
    ShotSize.EXTREME_WIDE: "Гранд-план",
    ShotSize.WIDE: "Общий",
    ShotSize.MEDIUM: "Средний",
    ShotSize.CLOSE: "Крупный",
    ShotSize.EXTREME_CLOSE: "Деталь",
    ShotSize.INSERT: "Вставка",
}


class Tool(StrEnum):  # инструмент генерации. TBD
    SEEDANCE = "seedance"
    KLING = "kling"
    VEO = "veo"
    RUNWAY = "runway"
    OTHER = "other"


TOOL_EXCEL_LABELS: dict[Tool, str] = {
    Tool.SEEDANCE: "Seedance",
    Tool.KLING: "Kling",
    Tool.VEO: "Veo",
    Tool.RUNWAY: "Runway",
    Tool.OTHER: "Другое",
}


class AssetType(StrEnum):  # TBD
    CHARACTER = "character"
    PROP = "prop"
    LOCATION = "location"
    OTHER = "other"


class SoundType(StrEnum):  # реплики, SFX, музыка
    DIALOGUE = "dialogue"
    SFX = "sfx"
    MUSIC = "music"


class Side(StrEnum):
    NORTH = "north"
    SOUTH = "south"


class FileKind(StrEnum):
    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    LINK = "link"


class FileSource(StrEnum):
    UPLOAD = "upload"
    TELEGRAM = "telegram"
    LINK = "link"


class Purpose(StrEnum):
    """Назначение вложения: референс, дубль, финал, блокаут, звук, музыка, субтитры, прочее."""

    REFERENCE = "reference"
    TAKE = "take"
    FINAL = "final"
    BLOCKOUT = "blockout"
    SOUND = "sound"
    MUSIC = "music"
    SUBTITLES = "subtitles"
    OTHER = "other"


class JobType(StrEnum):
    PREVIEW = "preview"
    PROXY = "proxy"
    WAVEFORM = "waveform"
    TG_IMPORT = "tg_import"
    EXPORT = "export"
    BACKUP = "backup"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ExportTarget(StrEnum):
    RESOLVE = "resolve"
    PREMIERE = "premiere"


# Сущности, к которым можно привязать файл, комментарий или задачу.
class EntityType(StrEnum):
    PROJECT = "project"
    USER = "user"
    SCENE = "scene"
    SHOT = "shot"
    ASSET = "asset"
    ASSET_STATE = "asset_state"
    SETUP_PAYOFF = "setup_payoff"
    SOUND_CUE = "sound_cue"
    TASK = "task"
    FILE = "file"
    COMMENT = "comment"


FPS_CHOICES = (24, 25)
DRUM_LEVEL_RANGE = (0, 5)

# Палитра для автоназначения цвета участникам (подобрана под тёмный фон `ink`).
USER_COLORS = (
    "#E8C979",
    "#5FA8B8",
    "#D9774B",
    "#9BB86B",
    "#B58CC9",
    "#6FA3D9",
    "#D98B9C",
    "#C9B28A",
)


def values(enum_cls: type[StrEnum]) -> tuple[str, ...]:
    return tuple(m.value for m in enum_cls)


def check_in(column: str, enum_cls: type[StrEnum]) -> str:
    """SQL-выражение для CHECK-ограничения `column IN (...)` по значениям справочника."""
    items = ", ".join(f"'{v}'" for v in values(enum_cls))
    return f"{column} IN ({items})"
