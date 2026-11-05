"""Промпт для LLM: шаблон + параметры проекта + актуальная JSON Schema + пример.

Сайт сценарий никуда не отправляет: человек скачивает этот файл, отдаёт его вместе со сценарием в
любую LLM (Claude, ChatGPT, Gemini, DeepSeek) и загружает ответ. Схема в промпт попадает из тех же
Pydantic-моделей, по которым проверяется файл, поэтому промпт и проверка не расходятся.
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from app.scenario import schema as S
from app.scenario.convert import example_fragment

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "import-prompt.md"
EXAMPLE = HERE / "example-brass-spyglass.json"

LANGUAGES = {
    "en": "английский",
    "ru": "русский",
    "de": "немецкий",
    "fr": "французский",
    "es": "испанский",
}
DEFAULT_MAX_SHOT_SEC = 15


@dataclass(frozen=True, slots=True)
class PromptParams:
    project_title: str
    target_min_sec: int = 300
    target_max_sec: int = 420
    max_shot_sec: float = DEFAULT_MAX_SHOT_SEC
    language: str = "en"


def _strip_titles(node: Any) -> Any:
    """Pydantic дописывает каждому полю `title` из его имени: для LLM это шум, он удлиняет схему."""
    if isinstance(node, dict):
        return {
            k: _strip_titles(v)
            for k, v in node.items()
            if not (k == "title" and isinstance(v, str))
        }
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


def schema_text() -> str:
    return json.dumps(_strip_titles(S.json_schema()), ensure_ascii=False, indent=1)


@cache
def example_document() -> S.ScenarioDoc:
    """Полный пример — файл фильма «Битва при кривом зеркале», собранный из Excel-трекера."""
    return S.ScenarioDoc.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))


def example_text() -> str:
    return EXAMPLE.read_text(encoding="utf-8")


def fragment_text() -> str:
    fragment = example_fragment(example_document(), scenes=2)
    return json.dumps(fragment.model_dump(mode="json"), ensure_ascii=False, indent=1)


def _number(value: float) -> str:
    return f"{value:g}"


def render(params: PromptParams) -> str:
    """Готовый `import-prompt.md` для проекта."""
    values = {
        "project_title": params.project_title,
        "target_min_sec": str(params.target_min_sec),
        "target_max_sec": str(params.target_max_sec),
        "max_shot_sec": _number(params.max_shot_sec),
        "film_language": LANGUAGES.get(params.language, params.language),
        "schema_version": S.SCHEMA_VERSION,
        "json_schema": schema_text(),
        "example_json": fragment_text(),
    }
    text = TEMPLATE.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text
