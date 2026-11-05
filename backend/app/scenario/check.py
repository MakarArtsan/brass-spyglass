"""Проверка файла импорта: разбор, автопоправки, схема, ссылки, смысл. В базу ничего не пишет.

Три уровня (PDF «Мультипроекты и импорт сценария»):
- разбор: не JSON, лишний текст вокруг блока кода, запятая перед `}`, «умные» кавычки;
- схема: нет обязательного поля, чужое значение списка, необъявленный код, дубль, другая версия;
- смысл: хронометраж вне цели, шоты не сходятся со сценой, слишком длинный шот, ассет без шотов.
Ошибки мешают создать проект, предупреждения — нет, поправки сайт сделал сам и о них говорит.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from app.scenario import schema as S

Level = Literal["error", "warning", "fix"]
MAX_ISSUES = 60

CODE_RE = re.compile(r"^[A-Z]{2}-\d{2,3}$")
LOOSE_CODE_RE = re.compile(r"^\s*([A-Za-z]{2})[\s_-]?(\d{1,3})\s*$")
SHOT_REF_RE = re.compile(r"^\s*0*(\d+)\s*[.,]\s*0*(\d+)\s*$")
FENCE_RE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\r?\n(.*?)```", re.S)
GUESS_PREFIX = "ПРЕДПОЛОЖЕНИЕ"

SECTION_LABELS = {
    "characters": "Персонаж",
    "locations": "Локация",
    "assets": "Ассет",
    "scenes": "Сцена",
    "shots": "шот",
    "dialogue": "реплика",
    "states": "состояние",
    "setups": "Сетап",
    "open_questions": "Открытый вопрос",
    "motifs": "Мотив",
}
OBJECT_LABELS = {"project": "Проект", "part": "Часть"}


@dataclass(frozen=True, slots=True)
class Issue:
    level: Level
    message: str
    where: str = ""

    def text(self) -> str:
        return f"{self.where}: {self.message}" if self.where else self.message


@dataclass(frozen=True, slots=True)
class Params:
    """Параметры проекта, по которым проверяется смысл (не схема)."""

    target_min_sec: int | None = None
    target_max_sec: int | None = None
    max_shot_sec: float = 15.0


@dataclass
class CheckResult:
    doc: S.ScenarioDoc | None
    issues: list[Issue] = field(default_factory=list)
    parts: int = 1

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def fixes(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "fix"]

    @property
    def ok(self) -> bool:
        return self.doc is not None and not self.errors


class ParseError(Exception):
    """Текст не удалось превратить в JSON."""


# --- разбор текста -----------------------------------------------------------------------------

_JSON_ERRORS = (
    ("Expecting ',' delimiter", "ожидалась запятая"),
    ("Expecting ':' delimiter", "ожидалось двоеточие после имени поля"),
    ("Expecting property name enclosed in double quotes", "ожидалось имя поля в двойных кавычках"),
    ("Expecting value", "ожидалось значение"),
    ("Unterminated string", "не закрыта строка (нет закрывающей кавычки)"),
    ("Invalid control character", "в строке недопустимый перенос или управляющий символ"),
    ("Invalid \\escape", "недопустимая последовательность \\ в строке"),
    ("Extra data", "после JSON есть лишний текст"),
)


def _explain(exc: json.JSONDecodeError) -> str:
    reason = next((ru for en, ru in _JSON_ERRORS if exc.msg.startswith(en)), exc.msg)
    return f"Не удалось разобрать JSON: строка {exc.lineno}, символ {exc.colno}: {reason}."


def _repair(text: str) -> str:
    """Мелкие ошибки записи: «умные» кавычки и запятая перед закрывающей скобкой."""
    fixed = text.replace("“", '"').replace("”", '"').replace("„", '"')
    return re.sub(r",(\s*[}\]])", r"\1", fixed)


def extract_json(text: str) -> tuple[Any, list[Issue]]:
    """Достаёт JSON из ответа LLM (из блока кода или из текста) и возвращает ещё поправки."""
    body = text.lstrip("﻿").strip()
    if not body:
        raise ParseError("Файл пуст.")
    issues: list[Issue] = []
    blocks = FENCE_RE.findall(body)
    candidate = max(blocks, key=len) if blocks else body
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise ParseError("В ответе нет JSON: не нашли фигурные скобки { }. Нужен один объект JSON.")
    snippet = candidate[start : end + 1]
    if snippet.strip() != body:
        issues.append(Issue("fix", "вокруг JSON был лишний текст, он отброшен"))
    try:
        return json.loads(snippet), issues
    except json.JSONDecodeError as first:
        repaired = _repair(snippet)
        if repaired != snippet:
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError:
                pass
            else:
                issues.append(
                    Issue("fix", "поправили запись JSON: лишние запятые или «умные» кавычки")
                )
                return data, issues
        raise ParseError(_explain(first)) from None


# --- автопоправки ------------------------------------------------------------------------------

_ENUM_ALIASES: dict[str, dict[str, str]] = {
    "size": {
        "pov трубы": "POV",
        "сплит / зеркало": "Сплит",
        "сплит/зеркало": "Сплит",
        "зеркало": "Сплит",
    },
    "type": {
        "корабль": "Транспорт",
        "эффект": "Эффект / среда",
        "среда": "Эффект / среда",
        "эффект/среда": "Эффект / среда",
        "стиль": "Стиль / лук",
        "лук": "Стиль / лук",
        "стиль/лук": "Стиль / лук",
    },
    "kind": {},
}


def _squash(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _match_enum(value: Any, allowed: tuple[str, ...], aliases: dict[str, str]) -> Any:
    if not isinstance(value, str):
        return value
    key = _squash(value)
    for option in allowed:
        if _squash(option) == key:
            return option
    return aliases.get(key, value)


def _fix_code(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    match = LOOSE_CODE_RE.match(value)
    if match is None:
        return value
    return f"{match.group(1).upper()}-{int(match.group(2)):02d}"


def _fix_ref(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    match = SHOT_REF_RE.match(value)
    return f"{int(match.group(1))}.{int(match.group(2))}" if match else value


def normalize(raw: dict[str, Any]) -> tuple[dict[str, Any], list[Issue]]:
    """Исправляет однозначное: CH1 → CH-01, регистр и пробелы в значениях списков,
    «03.03» → «3.3». Что поправили — вернёт отдельно, чтобы человек видел."""
    data = json.loads(json.dumps(raw))  # копия: исходный ответ не трогаем
    changes: dict[str, str] = {}

    def apply(container: Any, key: Any, fn: Any) -> None:
        if not isinstance(container, (dict, list)):
            return
        old = container[key]
        new = fn(old)
        if new != old:
            container[key] = new
            changes[f"{old}"] = f"{new}"

    def each(items: Any) -> list[dict[str, Any]]:
        return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []

    for section, allowed, field_name, aliases in (
        ("characters", S.CHARACTER_KINDS, "kind", _ENUM_ALIASES["kind"]),
        ("assets", S.ASSET_TYPES, "type", _ENUM_ALIASES["type"]),
    ):
        for item in each(data.get(section)):
            if field_name in item:
                apply(item, field_name, lambda v, a=allowed, al=aliases: _match_enum(v, a, al))
    for section in ("characters", "locations", "assets"):
        for item in each(data.get(section)):
            if "code" in item:
                apply(item, "code", _fix_code)
    for scene in each(data.get("scenes")):
        codes = scene.get("location_codes")
        if isinstance(codes, list):
            for i in range(len(codes)):
                apply(codes, i, _fix_code)
        for shot in each(scene.get("shots")):
            if "size" in shot:
                apply(shot, "size", lambda v: _match_enum(v, S.SHOT_SIZES, _ENUM_ALIASES["size"]))
            codes = shot.get("asset_codes")
            if isinstance(codes, list):
                for i in range(len(codes)):
                    apply(codes, i, _fix_code)
            states = shot.get("asset_states")
            if isinstance(states, dict):
                for key in list(states):
                    fixed = _fix_code(key)
                    if fixed != key and fixed not in states:
                        states[fixed] = states.pop(key)
                        changes[key] = fixed
            for line in each(shot.get("dialogue")):
                if line.get("character"):
                    apply(line, "character", _fix_code)
    for setup in each(data.get("setups")):
        for key in ("setup", "payoff"):
            refs = setup.get(key)
            if isinstance(refs, list):
                for i in range(len(refs)):
                    apply(refs, i, _fix_ref)
    for question in each(data.get("open_questions")):
        related = question.get("related")
        if isinstance(related, list):
            for i in range(len(related)):
                apply(related, i, _fix_code)
    fixes = [
        Issue("fix", f"«{old}» → «{new}»", "Поправлено автоматически")
        for old, new in changes.items()
    ]
    return data, fixes


# --- лишние поля -------------------------------------------------------------------------------

_KNOWN: dict[str, type] = {
    "project": S.Project,
    "part": S.Part,
    "characters": S.Character,
    "locations": S.Location,
    "assets": S.Asset,
    "scenes": S.Scene,
    "setups": S.Setup,
    "open_questions": S.OpenQuestion,
}


def unknown_fields(raw: dict[str, Any]) -> list[Issue]:
    """Поля, которых нет в схеме: сайт их игнорирует, но говорит об этом."""
    found: dict[str, set[str]] = {}

    def look(model: type[S._Model], data: Any, where: str) -> None:
        if isinstance(data, dict):
            extra = set(data) - set(model.model_fields)
            if extra:
                found.setdefault(where, set()).update(extra)

    look(S.ScenarioDoc, raw, "в корне файла")
    for key, model in _KNOWN.items():
        value = raw.get(key)
        for item in value if isinstance(value, list) else [value]:
            look(model, item, f"«{key}»")
    for scene in raw.get("scenes") or []:
        for shot in (scene.get("shots") or []) if isinstance(scene, dict) else []:
            look(S.Shot, shot, "«shots»")
            for line in (shot.get("dialogue") or []) if isinstance(shot, dict) else []:
                look(S.DialogueLine, line, "«dialogue»")
    return [
        Issue("warning", f"лишние поля {', '.join(sorted(names))} игнорируются", where)
        for where, names in found.items()
    ]


# --- ошибки схемы по-русски --------------------------------------------------------------------


def _label(section: str, index: int, item: Any) -> str:
    base = SECTION_LABELS.get(section, section)
    if isinstance(item, dict):
        if section == "scenes" and isinstance(item.get("number"), int):
            return f"{base} {item['number']}"
        if section in ("characters", "locations", "assets") and item.get("code"):
            return f"{base} {item['code']}"
    return f"{base} {index + 1}"


def _where(loc: tuple[Any, ...], raw: Any) -> tuple[str, str]:
    """Человеческий адрес ошибки («Сцена 4, шот 3») и имя поля."""
    parts: list[str] = []
    node = raw
    path = list(loc)
    field_name = ""
    i = 0
    while i < len(path):
        key = path[i]
        if isinstance(key, str) and i + 1 < len(path) and isinstance(path[i + 1], int):
            items = node.get(key) if isinstance(node, dict) else None
            index = path[i + 1]
            item = items[index] if isinstance(items, list) and index < len(items) else None
            parts.append(_label(key, index, item))
            node = item
            i += 2
            continue
        if isinstance(key, str) and key in OBJECT_LABELS and i + 1 < len(path):
            parts.append(OBJECT_LABELS[key])
            node = node.get(key) if isinstance(node, dict) else None
            i += 1
            continue
        field_name = str(key)
        node = node.get(key) if isinstance(node, dict) else None
        i += 1
    return ", ".join(parts), field_name


def _message(err: dict[str, Any], name: str) -> str:
    kind = err["type"]
    ctx = err.get("ctx") or {}
    got = err.get("input")
    if kind == "missing":
        return f"не заполнено обязательное поле «{name}»"
    if kind == "literal_error":
        allowed = re.findall(r"'([^']+)'", str(ctx.get("expected", "")))
        return f"недопустимое значение «{got}» в поле «{name}»; допустимо: {', '.join(allowed)}"
    if kind in ("int_parsing", "int_type", "float_parsing", "float_type", "int_from_float"):
        return f"в поле «{name}» нужно число, а там «{got}»"
    if kind == "string_type":
        return f"в поле «{name}» нужен текст, а там «{got}»"
    if kind == "list_type":
        return f"в поле «{name}» нужен список [ ]"
    if kind in ("dict_type", "model_type"):
        return f"в поле «{name}» нужен объект {{ }}"
    if kind == "greater_than":
        return f"поле «{name}» должно быть больше {ctx.get('gt')}"
    if kind == "greater_than_equal":
        return f"поле «{name}» не может быть меньше {ctx.get('ge')}"
    if kind == "less_than_equal":
        return f"поле «{name}» не может быть больше {ctx.get('le')}"
    if kind in ("string_too_short", "too_short"):
        return f"поле «{name}» не может быть пустым"
    return f"поле «{name}»: {err.get('msg')}"


def validate_schema(raw: Any) -> tuple[S.ScenarioDoc | None, list[Issue]]:
    if not isinstance(raw, dict):
        return None, [
            Issue("error", "Ожидался один объект JSON { … }, а в файле список или значение.")
        ]
    version = raw.get("schema_version")
    if version != S.SCHEMA_VERSION:
        shown = "не указана" if version is None else f"«{version}» не поддерживается"
        return None, [
            Issue(
                "error",
                f"Версия схемы {shown}: нужна {S.SCHEMA_VERSION} (поле schema_version).",
            )
        ]
    try:
        return S.ScenarioDoc.model_validate(raw), []
    except ValidationError as exc:
        issues = []
        for err in exc.errors():
            where, name = _where(tuple(err["loc"]), raw)
            issues.append(Issue("error", _message(err, name), where))
        return None, issues


# --- ссылки и коды (ошибки) --------------------------------------------------------------------


def _declared(doc: S.ScenarioDoc) -> tuple[dict[str, str], list[Issue]]:
    """Код → описание объявления; дубли и неверный формат кода — ошибки."""
    issues: list[Issue] = []
    declared: dict[str, str] = {}
    for kind, items in (
        ("персонаж", doc.characters),
        ("локация", doc.locations),
        ("ассет", doc.assets),
    ):
        for item in items:
            title = f"{kind} «{item.name}»"
            if not CODE_RE.match(item.code):
                issues.append(
                    Issue("error", f"код «{item.code}» ({title}) не в формате XX-01", "Объявления")
                )
                continue
            if item.code in declared:
                issues.append(
                    Issue(
                        "error",
                        f"код {item.code} объявлен дважды: {declared[item.code]} и {title}",
                        "Объявления",
                    )
                )
                continue
            declared[item.code] = title
    return declared, issues


def _prefix_warnings(doc: S.ScenarioDoc) -> list[Issue]:
    out: list[Issue] = []
    for item in doc.characters:
        if CODE_RE.match(item.code) and item.code[:2] not in S.CHARACTER_PREFIXES[item.kind]:
            wanted = " или ".join(S.CHARACTER_PREFIXES[item.kind])
            out.append(
                Issue(
                    "warning",
                    f"у типа «{item.kind}» код обычно {wanted}-NN",
                    f"Персонаж {item.code}",
                )
            )
    for item in doc.locations:
        if CODE_RE.match(item.code) and item.code[:2] not in S.LOCATION_PREFIXES:
            out.append(Issue("warning", "у локации код обычно LC-NN", f"Локация {item.code}"))
    for item in doc.assets:
        if CODE_RE.match(item.code) and item.code[:2] not in S.ASSET_PREFIXES[item.type]:
            wanted = " или ".join(S.ASSET_PREFIXES[item.type])
            out.append(
                Issue(
                    "warning", f"у типа «{item.type}» код обычно {wanted}-NN", f"Ассет {item.code}"
                )
            )
    return out


def check_references(doc: S.ScenarioDoc) -> list[Issue]:
    declared, issues = _declared(doc)
    locations = {i.code for i in doc.locations}
    speakers = {i.code for i in doc.characters}
    states_of: dict[str, set[str]] = {
        item.code: {s.name for s in item.states}
        for item in (*doc.characters, *doc.locations, *doc.assets)
    }
    seen_numbers: dict[int, int] = {}
    for scene in doc.scenes:
        seen_numbers[scene.number] = seen_numbers.get(scene.number, 0) + 1
    for number, times in sorted(seen_numbers.items()):
        if times > 1:
            issues.append(
                Issue("error", f"номер сцены {number} встречается {times} раза", f"Сцена {number}")
            )
    for scene in doc.scenes:
        at = f"Сцена {scene.number}"
        for code in scene.location_codes:
            if code not in declared:
                issues.append(Issue("error", f"неизвестная локация {code}", at))
            elif code not in locations:
                issues.append(
                    Issue("error", f"{code} объявлен не как локация ({declared[code]})", at)
                )
        for number, shot in enumerate(scene.shots, start=1):
            where = f"{at}, шот {number}"
            for code in shot.asset_codes:
                if code not in declared:
                    issues.append(Issue("error", f"неизвестный ассет {code}", where))
            for code, state in shot.asset_states.items():
                if code not in declared:
                    issues.append(Issue("error", f"неизвестный ассет {code} в asset_states", where))
                elif state not in states_of[code]:
                    have = (
                        ", ".join(f"«{s}»" for s in sorted(states_of[code]))
                        or "состояний не объявлено"
                    )
                    issues.append(
                        Issue(
                            "error", f"у ассета {code} нет состояния «{state}»; есть: {have}", where
                        )
                    )
                elif code not in shot.asset_codes:
                    issues.append(
                        Issue(
                            "warning",
                            f"состояние задано ассету {code}, которого нет в asset_codes",
                            where,
                        )
                    )
            for line_no, line in enumerate(shot.dialogue, start=1):
                at_line = f"{where}, реплика {line_no}"
                if line.character is None and not line.speaker:
                    issues.append(
                        Issue(
                            "error",
                            "у реплики нет ни character, ни speaker: непонятно, кто говорит",
                            at_line,
                        )
                    )
                elif line.character is not None and line.character not in declared:
                    issues.append(Issue("error", f"неизвестный персонаж {line.character}", at_line))
                elif line.character is not None and line.character not in speakers:
                    issues.append(
                        Issue(
                            "error",
                            f"{line.character} объявлен не как персонаж "
                            f"({declared[line.character]})",
                            at_line,
                        )
                    )
    shots_in = {scene.number: len(scene.shots) for scene in doc.scenes}
    for number, setup in enumerate(doc.setups, start=1):
        where = f"Сетап {number} «{setup.motif}»"
        for ref in (*setup.setup, *setup.payoff):
            match = SHOT_REF_RE.match(ref)
            if match is None:
                issues.append(
                    Issue("error", f"ссылка «{ref}» на шот должна быть вида 3.3 (сцена.шот)", where)
                )
                continue
            scene_no, shot_no = int(match.group(1)), int(match.group(2))
            if scene_no not in shots_in:
                issues.append(
                    Issue(
                        "error", f"шот {scene_no}.{shot_no} не найден: сцены {scene_no} нет", where
                    )
                )
            elif not 1 <= shot_no <= shots_in[scene_no]:
                issues.append(
                    Issue(
                        "error",
                        f"шот {scene_no}.{shot_no} не найден: "
                        f"в сцене {scene_no} шотов {shots_in[scene_no]}",
                        where,
                    )
                )
    for number, question in enumerate(doc.open_questions, start=1):
        for code in question.related:
            if code not in declared:
                issues.append(
                    Issue("error", f"неизвестный код {code} в related", f"Открытый вопрос {number}")
                )
    return issues


# --- смысл (предупреждения) --------------------------------------------------------------------

SCENE_SUM_TOLERANCE_SEC = 2.0


def _seconds(value: float) -> str:
    return f"{value:g}"


def check_meaning(doc: S.ScenarioDoc, params: Params) -> list[Issue]:
    out: list[Issue] = []
    total = sum(scene.planned_sec for scene in doc.scenes)
    low, high = params.target_min_sec, params.target_max_sec
    if low is not None and high is not None and not low <= total <= high:
        out.append(
            Issue("warning", f"хронометраж {_seconds(total)} с вне цели {low}–{high} с", "Фильм")
        )
    numbers = sorted({scene.number for scene in doc.scenes})
    gaps = [n for n in range(numbers[0], numbers[-1] + 1) if n not in numbers] if numbers else []
    if gaps:
        out.append(Issue("warning", "пропущены номера сцен: " + ", ".join(map(str, gaps)), "Фильм"))
    used: set[str] = set()
    for scene in doc.scenes:
        at = f"Сцена {scene.number}"
        used.update(scene.location_codes)
        if not scene.shots:
            out.append(Issue("warning", "в сцене нет шотов", at))
        else:
            shots_sum = sum(shot.duration_sec for shot in scene.shots)
            if abs(shots_sum - scene.planned_sec) > SCENE_SUM_TOLERANCE_SEC:
                out.append(
                    Issue(
                        "warning",
                        f"сумма шотов {_seconds(shots_sum)} с, "
                        f"а в плане сцены {_seconds(scene.planned_sec)} с",
                        at,
                    )
                )
        if scene.side and doc.project.sides and scene.side not in doc.project.sides:
            out.append(Issue("warning", f"сторона «{scene.side}» не названа в project.sides", at))
        for number, shot in enumerate(scene.shots, start=1):
            where = f"{at}, шот {number}"
            used.update(shot.asset_codes)
            if shot.duration_sec > params.max_shot_sec:
                out.append(
                    Issue(
                        "warning",
                        f"шот {_seconds(shot.duration_sec)} с длиннее лимита "
                        f"{_seconds(params.max_shot_sec)} с",
                        where,
                    )
                )
            if shot.notes and shot.notes.strip().upper().startswith(GUESS_PREFIX):
                out.append(
                    Issue("warning", f"догадка LLM, проверьте: {shot.notes.strip()[:90]}", where)
                )
    for kind, items in (
        ("Персонаж", doc.characters),
        ("Локация", doc.locations),
        ("Ассет", doc.assets),
    ):
        for item in items:
            if item.code not in used:
                out.append(
                    Issue(
                        "warning",
                        f"«{item.name}» не встречается ни в одном шоте",
                        f"{kind} {item.code}",
                    )
                )
    return out


# --- части и общая проверка --------------------------------------------------------------------


def _merge(docs: list[S.ScenarioDoc], issues: list[Issue]) -> S.ScenarioDoc | None:
    total = docs[0].part.total if docs[0].part else 1
    if len(docs) == 1:
        part = docs[0].part
        if part is not None and part.total > 1:
            issues.append(
                Issue(
                    "error",
                    f"это часть {part.index} из {part.total}: "
                    "загрузите остальные части вместе с ней",
                )
            )
            return None
        return docs[0]
    if any(d.part is None for d in docs):
        issues.append(
            Issue(
                "error", "файлов несколько, а в каком-то нет поля part: непонятно, как их склеить"
            )
        )
        return None
    if len({d.part.total for d in docs if d.part}) > 1:
        issues.append(Issue("error", "в файлах разное число частей (part.total)"))
        return None
    indexes = [d.part.index for d in docs if d.part]
    for index in sorted({i for i in indexes if indexes.count(i) > 1}):
        issues.append(Issue("error", f"часть {index} загружена дважды"))
    missing = [n for n in range(1, total + 1) if n not in indexes]
    for n in missing:
        issues.append(Issue("error", f"не хватает части {n} из {total}"))
    if missing or any(i.level == "error" for i in issues):
        return None
    docs = sorted(docs, key=lambda d: d.part.index if d.part else 0)
    merged = docs[0].model_copy(deep=True)
    merged.part = None
    for other in docs[1:]:
        if other.project.title != merged.project.title:
            issues.append(
                Issue(
                    "warning",
                    f"название проекта в частях разное: «{merged.project.title}» и "
                    f"«{other.project.title}»; взято из части 1",
                    f"Часть {other.part.index if other.part else '?'}",
                )
            )
        for section in ("characters", "locations", "assets"):
            have = {item.code: item for item in getattr(merged, section)}
            for item in getattr(other, section):
                known = have.get(item.code)
                if known is None:
                    getattr(merged, section).append(item.model_copy(deep=True))
                elif known.name != item.name:
                    issues.append(
                        Issue(
                            "warning",
                            f"код {item.code} в частях назван по-разному: «{known.name}» и "
                            f"«{item.name}»; взято «{known.name}»",
                            f"Часть {other.part.index if other.part else '?'}",
                        )
                    )
        merged.scenes.extend(scene.model_copy(deep=True) for scene in other.scenes)
        seen = {(s.motif, tuple(s.setup), tuple(s.payoff)) for s in merged.setups}
        for setup in other.setups:
            if (setup.motif, tuple(setup.setup), tuple(setup.payoff)) not in seen:
                merged.setups.append(setup.model_copy(deep=True))
        asked = {q.question for q in merged.open_questions}
        merged.open_questions.extend(
            q.model_copy(deep=True) for q in other.open_questions if q.question not in asked
        )
    merged.scenes.sort(key=lambda scene: scene.number)
    return merged


def _cap(issues: list[Issue]) -> list[Issue]:
    if len(issues) <= MAX_ISSUES:
        return issues
    shown = issues[:MAX_ISSUES]
    shown.append(
        Issue(
            "warning", f"…и ещё {len(issues) - MAX_ISSUES}: исправьте найденное и проверьте снова"
        )
    )
    return shown


def check_texts(texts: list[str], params: Params | None = None) -> CheckResult:
    """Проверяет один или несколько файлов (части одного сценария). Ничего не пишет в базу."""
    params = params or Params()
    docs: list[S.ScenarioDoc] = []
    issues: list[Issue] = []
    for number, text in enumerate(texts, start=1):
        prefix = f"Файл {number}" if len(texts) > 1 else ""

        def tag(items: list[Issue], prefix: str = prefix) -> list[Issue]:
            if not prefix:
                return items
            return [
                Issue(i.level, i.message, f"{prefix}, {i.where}" if i.where else prefix)
                for i in items
            ]

        try:
            raw, found = extract_json(text)
        except ParseError as exc:
            issues.extend(tag([Issue("error", str(exc))]))
            continue
        issues.extend(tag(found))
        if isinstance(raw, dict):
            raw, fixes = normalize(raw)
            issues.extend(tag(fixes))
            issues.extend(tag(unknown_fields(raw)))
        doc, errors = validate_schema(raw)
        issues.extend(tag(errors))
        if doc is not None:
            docs.append(doc)
    if not texts:
        return CheckResult(None, [Issue("error", "Нечего проверять: нет ни файла, ни текста.")], 0)
    if len(docs) != len(texts):
        return CheckResult(None, _cap(issues), len(texts))
    merged = _merge(docs, issues)
    if merged is None:
        return CheckResult(None, _cap(issues), len(texts))
    if not merged.scenes:
        issues.append(Issue("error", "в файле нет ни одной сцены (scenes пуст)"))
    issues.extend(check_references(merged))
    issues.extend(_prefix_warnings(merged))
    issues.extend(check_meaning(merged, params))
    result = CheckResult(merged, _cap(issues), len(texts))
    if result.errors:
        result.doc = None
    return result
