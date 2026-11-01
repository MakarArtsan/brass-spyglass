"""Справочники проекта: статусы, этапы, крупности, инструменты, типы.

Это единственный источник значений. По ним строятся CHECK-ограничения в БД.
`excel_label` — текст из Excel-трекера, по нему импорт сопоставляет значения.
Значения сверены с листом «Справочник» Excel-трекера (Krivoe_zerkalo_tracker.xlsx).
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


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


PRIORITY_EXCEL_LABELS: dict[Priority, str] = {
    Priority.HIGH: "Высокий",
    Priority.MEDIUM: "Средний",
    Priority.LOW: "Низкий",
}


class Stage(StrEnum):
    """Этап шота — колонки канбана."""

    STORYBOARD = "storyboard"
    BLOCKOUT = "blockout"
    PROMPT = "prompt"
    GENERATION = "generation"
    TAKE_SELECTION = "take_selection"
    IN_EDIT = "in_edit"
    FINAL = "final"


STAGE_EXCEL_LABELS: dict[Stage, str] = {
    Stage.STORYBOARD: "Раскадровка",
    Stage.BLOCKOUT: "Блокаут",
    Stage.PROMPT: "Промпт",
    Stage.GENERATION: "Генерация",
    Stage.TAKE_SELECTION: "Отбор дубля",
    Stage.IN_EDIT: "В монтаже",
    Stage.FINAL: "Финал",
}


class ShotSize(StrEnum):
    WIDE = "wide"
    MEDIUM = "medium"
    CLOSE = "close"
    DETAIL = "detail"
    POV_SPYGLASS = "pov_spyglass"
    SPLIT_MIRROR = "split_mirror"


SHOT_SIZE_EXCEL_LABELS: dict[ShotSize, str] = {
    ShotSize.WIDE: "Общий",
    ShotSize.MEDIUM: "Средний",
    ShotSize.CLOSE: "Крупный",
    ShotSize.DETAIL: "Деталь",
    ShotSize.POV_SPYGLASS: "POV трубы",
    ShotSize.SPLIT_MIRROR: "Сплит / зеркало",
}


class Tool(StrEnum):
    SEEDANCE = "seedance"
    OTHER_VIDEO = "other_video"
    AI_IMAGE = "ai_image"
    BLENDER_3D = "blender_3d"
    GRAPHICS = "graphics"
    LIVE_ACTION = "live_action"


TOOL_EXCEL_LABELS: dict[Tool, str] = {
    Tool.SEEDANCE: "Seedance",
    Tool.OTHER_VIDEO: "Другая AI-видео",
    Tool.AI_IMAGE: "AI-картинка (стоп-кадр)",
    Tool.BLENDER_3D: "Blender / 3D",
    Tool.GRAPHICS: "Графика / титры",
    Tool.LIVE_ACTION: "Live action",
}


class AssetType(StrEnum):
    CHARACTER = "character"
    CROWD = "crowd"
    ANIMAL = "animal"
    PROP = "prop"
    FAUX_PROP = "faux_prop"  # бутафория
    LOCATION = "location"
    SHIP = "ship"
    EFFECT = "effect"
    STYLE = "style"


ASSET_TYPE_EXCEL_LABELS: dict[AssetType, str] = {
    AssetType.CHARACTER: "Персонаж",
    AssetType.CROWD: "Массовка",
    AssetType.ANIMAL: "Животное",
    AssetType.PROP: "Реквизит",
    AssetType.FAUX_PROP: "Бутафория",
    AssetType.LOCATION: "Локация",
    AssetType.SHIP: "Корабль",
    AssetType.EFFECT: "Эффект / среда",
    AssetType.STYLE: "Стиль / лук",
}


class SoundType(StrEnum):
    DIALOGUE = "dialogue"
    SFX = "sfx"
    MUSIC = "music"
    SILENCE = "silence"
    AMBIENCE = "ambience"


SOUND_TYPE_EXCEL_LABELS: dict[SoundType, str] = {
    SoundType.DIALOGUE: "Реплика",
    SoundType.SFX: "SFX",
    SoundType.MUSIC: "Музыка",
    SoundType.SILENCE: "Тишина",
    SoundType.AMBIENCE: "Атмосфера",
}


class TaskBlock(StrEnum):
    CONTEST = "contest"
    PREPRODUCTION = "preproduction"
    GENERATION = "generation"
    EDITING = "editing"
    SOUND = "sound"
    DELIVERY = "delivery"


TASK_BLOCK_EXCEL_LABELS: dict[TaskBlock, str] = {
    TaskBlock.CONTEST: "Конкурс",
    TaskBlock.PREPRODUCTION: "Препродакшн",
    TaskBlock.GENERATION: "Генерация",
    TaskBlock.EDITING: "Монтаж",
    TaskBlock.SOUND: "Звук",
    TaskBlock.DELIVERY: "Сдача",
}


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


class NotificationKind(StrEnum):
    """Что произошло на карточке: комментарий, добавленный файл, новая версия файла."""

    COMMENT = "comment"
    FILE = "file"
    VERSION = "version"


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


def from_excel(enum_cls: type[StrEnum], labels: dict, text: str | None) -> StrEnum | None:
    """Значение справочника по тексту ячейки Excel; `None` для пустой или неизвестной ячейки."""
    if text is None or str(text).strip() == "":
        return None
    wanted = str(text).strip()
    for member, label in labels.items():
        if label == wanted and isinstance(member, enum_cls):
            return member
    return None
