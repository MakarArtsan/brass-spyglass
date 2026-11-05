"""Схема импорта сценария 1.0 (Pydantic). Описания полей по-русски: они идут в промпт для LLM."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

# Значения списков — ровно так их пишет LLM и проверяет сайт.
CHARACTER_KINDS = ("Персонаж", "Массовка", "Животное")
ASSET_TYPES = ("Реквизит", "Бутафория", "Транспорт", "Эффект / среда", "Стиль / лук")
SHOT_SIZES = ("Общий", "Средний", "Крупный", "Деталь", "POV", "Сплит")

CharacterKind = Literal["Персонаж", "Массовка", "Животное"]
AssetKind = Literal["Реквизит", "Бутафория", "Транспорт", "Эффект / среда", "Стиль / лук"]
ShotSizeName = Literal["Общий", "Средний", "Крупный", "Деталь", "POV", "Сплит"]

# Префикс кода по разделам (в PDF у транспорта VH, в данных фильма SH: принимаем оба).
CHARACTER_PREFIXES = {"Персонаж": ("CH",), "Массовка": ("CH",), "Животное": ("AN",)}
ASSET_PREFIXES = {
    "Реквизит": ("PR",),
    "Бутафория": ("PR",),
    "Транспорт": ("VH", "SH"),
    "Эффект / среда": ("EF",),
    "Стиль / лук": ("ST",),
}
LOCATION_PREFIXES = ("LC",)

Code = Annotated[
    str, Field(description="Код формата XX-01: CH персонажи и массовка, AN животные, LC локации")
]
Text = Annotated[str | None, Field(default=None)]


class _Model(BaseModel):
    # Лишние поля не ошибка: LLM любит добавлять своё. Они игнорируются, а проверка сообщит о них.
    model_config = ConfigDict(extra="ignore")


class State(_Model):
    name: str = Field(description="Название состояния: «день», «туман», «бег по городу»")
    description: str | None = Field(default=None, description="Чем состояние отличается внешне")


class Motif(_Model):
    name: str = Field(description="Название сквозного мотива")
    description: str | None = None


class Part(_Model):
    """Заполняется только когда ответ разбит на части (сценарий не влез в один ответ)."""

    index: int = Field(ge=1, description="Номер этой части, с 1")
    total: int = Field(ge=1, description="Сколько всего частей")
    scenes_from: int | None = Field(default=None, description="Номер первой сцены этой части")
    scenes_to: int | None = Field(default=None, description="Номер последней сцены этой части")


class Project(_Model):
    title: str = Field(min_length=1, description="Название фильма")
    title_en: str | None = Field(default=None, description="Название по-английски")
    logline: str | None = Field(default=None, description="Одно предложение о фильме")
    synopsis: str | None = Field(default=None, description="Краткое содержание")
    language: str = Field(default="en", description="Язык реплик в фильме: en, ru…")
    target_duration_sec: int | None = Field(
        default=None, ge=1, description="Целевой хронометраж, сек"
    )
    sides: list[str] = Field(
        default_factory=list, description="Стороны конфликта, если они есть в сценарии; иначе []"
    )
    motifs: list[Motif] = Field(default_factory=list, description="Сквозные мотивы")


class Character(_Model):
    code: Code
    name: str = Field(min_length=1)
    name_en: str | None = None
    kind: CharacterKind = Field(description="Персонаж, Массовка или Животное")
    side: str | None = Field(default=None, description="Сторона конфликта, если есть")
    description: str | None = Field(default=None, description="Кто это, характер")
    appearance: str | None = Field(
        default=None, description="Внешность. Нет в сценарии — null, не выдумывай"
    )
    states: list[State] = Field(
        default_factory=list, description="Состояния, если внешность меняется по ходу фильма"
    )


class Location(_Model):
    code: Code
    name: str = Field(min_length=1)
    description: str | None = None
    states: list[State] = Field(default_factory=list, description="Например: день, туман, рассвет")


class Asset(_Model):
    code: Code
    type: AssetKind = Field(
        description="Реквизит, Бутафория, Транспорт, Эффект / среда или Стиль / лук"
    )
    name: str = Field(min_length=1)
    description: str | None = None
    states: list[State] = Field(default_factory=list)


class DialogueLine(_Model):
    character: str | None = Field(
        default=None,
        description="Код говорящего (CH-01). Если говорят несколько — null и заполни speaker",
    )
    speaker: str | None = Field(
        default=None, description="Кто говорит, если нет одного персонажа («Оба дозорных»)"
    )
    text: str = Field(min_length=1, description="Реплика дословно, на языке фильма")
    translation: str | None = Field(default=None, description="Перевод на русский")


class Shot(_Model):
    description: str = Field(min_length=1, description="Что в кадре, одним-двумя предложениями")
    size: ShotSizeName | None = Field(
        default=None, description="Общий, Средний, Крупный, Деталь, POV или Сплит"
    )
    camera: str | None = Field(
        default=None, description="Движение камеры: статика, проводка, наезд…"
    )
    duration_sec: float = Field(gt=0, description="Длительность шота в секундах")
    asset_codes: list[str] = Field(
        default_factory=list,
        description="Коды всего, что видно в кадре: персонажи, локация, предметы",
    )
    asset_states: dict[str, str] = Field(
        default_factory=dict,
        description="Код ассета → название его состояния из списка states этого ассета",
    )
    dialogue: list[DialogueLine] = Field(default_factory=list)
    sfx: str | None = Field(default=None, description="Звук и шум в кадре")
    notes: str | None = Field(
        default=None, description="Заметки. Догадки — только с префиксом «ПРЕДПОЛОЖЕНИЕ:»"
    )


class Scene(_Model):
    number: int = Field(ge=1, description="Номер сцены")
    title: str = Field(min_length=1)
    location_codes: list[str] = Field(
        default_factory=list, description="Коды локаций сцены (LC-01)"
    )
    time_of_day: str | None = Field(default=None, description="Утро, день, ночь…")
    planned_sec: float = Field(gt=0, description="Плановая длительность сцены, сек")
    summary: str | None = Field(default=None, description="О чём сцена, одним предложением")
    meaning: str | None = Field(default=None, description="Зачем сцена нужна истории")
    side: str | None = None
    intensity: int | None = Field(default=None, ge=0, le=5, description="Накал сцены от 0 до 5")
    cut_notes: str | None = Field(default=None, description="Что нельзя резать и почему")
    source_ref: str | None = Field(default=None, description="Где это в сценарии: «стр. 3»")
    shots: list[Shot] = Field(default_factory=list)


class Setup(_Model):
    motif: str = Field(min_length=1, description="Что закладывается и стреляет")
    setup: list[str] = Field(
        default_factory=list, description='Где закладывается: шоты как "сцена.шот", например "3.3"'
    )
    payoff: list[str] = Field(
        default_factory=list, description='Где стреляет: шоты как "сцена.шот"'
    )
    takeaway: str | None = Field(default=None, description="Что должен понять зритель")
    risk: str | None = Field(default=None, description="Что может не сработать")


class OpenQuestion(_Model):
    question: str = Field(min_length=1, description="Дыра или противоречие в сценарии")
    related: list[str] = Field(default_factory=list, description="Коды, к которым вопрос относится")


class ScenarioDoc(_Model):
    schema_version: Literal["1.0"] = Field(description="Версия схемы: всегда 1.0")
    part: Part | None = Field(default=None, description="Только когда ответ разбит на части")
    project: Project
    characters: list[Character] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    setups: list[Setup] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)


def json_schema() -> dict:
    """JSON Schema файла импорта — для промпта."""
    return ScenarioDoc.model_json_schema()
