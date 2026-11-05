"""Импорт сценария в проект: проверка файла, предпросмотр, создание одной транзакцией.

Проверка ничего не пишет. Создание — только в пустой проект (в проекте ничего нет, даже удалённого
в корзину: импортёр ищет записи по кодам и восстановил бы или перезаписал чужое), одной транзакцией
сессии запроса: при любой ошибке не создаётся ничего. Файл перепроверяется на сервере, предпросмотр
клиента ему не указ. Автор всех записей — тот, кто импортировал; в журнале одна запись.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, permissions
from app.permissions import Actor
from app.scenario import check as checker
from app.scenario import convert, preview, prompt
from app.scenario import schema as S
from app.scenario.check import CheckResult, Params
from app.services import importing
from app.services.core import ConflictError, NotFoundError, ValidationError

MAX_TEXTS = 20
MAX_TEXT_CHARS = 3_000_000
MAX_TOTAL_CHARS = 8_000_000
MAX_FILENAME = 500
MAX_STORED_WARNINGS = 200
DEFAULT_MAX_SHOT_SEC = prompt.DEFAULT_MAX_SHOT_SEC

NOT_EMPTY = (
    "В проекте уже есть карточки (сцены, шоты, ассеты, звук или задачи, в том числе из корзины). "
    "Сценарий импортируется только в пустой проект: создайте новый. Повторный импорт новой версии "
    "сценария в существующий проект пока не поддерживается."
)

CONTENT_MODELS = (
    models.Scene,
    models.Shot,
    models.Asset,
    models.SetupPayoff,
    models.SoundCue,
    models.Task,
)


@dataclass(frozen=True, slots=True)
class Checked:
    result: CheckResult
    preview: dict[str, Any] | None
    empty: bool


def require_import(actor: Actor) -> None:
    permissions.require(
        permissions.can_import(actor), "Сценарий импортируют владелец и режиссёр проекта"
    )


def is_empty(db: Session, project_id: int) -> bool:
    return all(
        db.scalar(select(m.id).where(m.project_id == project_id).limit(1)) is None  # type: ignore[attr-defined]
        for m in CONTENT_MODELS
    )


def params_for(
    project: models.Project,
    *,
    target_min_sec: int | None = None,
    target_max_sec: int | None = None,
    max_shot_sec: float | None = None,
) -> Params:
    """Цели и лимит шота: что передали, иначе то, что записано в проекте."""
    low = target_min_sec if target_min_sec is not None else project.target_min_sec
    high = target_max_sec if target_max_sec is not None else project.target_max_sec
    if low > high:
        raise ValidationError("Хронометраж: минимум больше максимума")
    return Params(
        target_min_sec=low,
        target_max_sec=high,
        max_shot_sec=max_shot_sec if max_shot_sec is not None else DEFAULT_MAX_SHOT_SEC,
    )


def prompt_for(project: models.Project, params: Params, language: str) -> str:
    if language not in prompt.LANGUAGES:
        raise ValidationError(
            "Язык фильма: выберите из списка (" + ", ".join(sorted(prompt.LANGUAGES)) + ")"
        )
    return prompt.render(
        prompt.PromptParams(
            project_title=project.title,
            target_min_sec=params.target_min_sec or project.target_min_sec,
            target_max_sec=params.target_max_sec or project.target_max_sec,
            max_shot_sec=params.max_shot_sec,
            language=language,
        )
    )


def _limits(texts: list[str]) -> None:
    if not texts:
        raise ValidationError("Загрузите файл или вставьте ответ LLM")
    if len(texts) > MAX_TEXTS:
        raise ValidationError(f"Слишком много файлов: не больше {MAX_TEXTS}")
    if any(len(t) > MAX_TEXT_CHARS for t in texts) or sum(map(len, texts)) > MAX_TOTAL_CHARS:
        raise ValidationError("Файл слишком большой для сценария")


def check(
    db: Session, actor: Actor, project: models.Project, texts: list[str], params: Params
) -> Checked:
    """Проверка и предпросмотр без записи в базу."""
    require_import(actor)
    _limits(texts)
    result = checker.check_texts(texts, params)
    shown = preview.build(result.doc, params) if result.doc is not None else None
    return Checked(result, shown, is_empty(db, project.id))


def apply(
    db: Session,
    actor: Actor,
    project: models.Project,
    texts: list[str],
    params: Params,
    *,
    exclude: list[str] | None = None,
    names: list[str] | None = None,
) -> tuple[models.ImportRun, importing.ImportReport]:
    require_import(actor)
    _limits(texts)
    if not is_empty(db, project.id):
        raise ConflictError(NOT_EMPTY)
    result = checker.check_texts(texts, params)
    if result.doc is None or not result.ok:
        raise ValidationError(
            f"Сценарий не прошёл проверку ({len(result.errors)} ошибок): исправьте файл и "
            "проверьте его заново"
        )
    skip = set(exclude or [])
    declared = {c.code for c in (*result.doc.characters, *result.doc.locations, *result.doc.assets)}
    if skip - declared:
        raise ValidationError(
            "Нет такого кода в сценарии: "
            + ", ".join(sorted(skip - declared))
            + ". Проверьте файл заново"
        )
    doc = convert.exclude_codes(result.doc, skip)
    leftovers = [i for i in checker.check_references(doc) if i.level == "error"]
    if leftovers:  # исключили то, на что ссылается остальное, и это не удалось подчистить
        raise ValidationError("После исключения остались битые ссылки: " + leftovers[0].text())
    bundle = convert.to_bundle(doc)
    warnings = [i.text() for i in result.warnings] + list(bundle.warnings)
    run = models.ImportRun(
        project_id=project.id,
        kind="scenario",
        schema_version=S.SCHEMA_VERSION,
        filename=", ".join(n.strip() for n in (names or []) if n.strip())[:MAX_FILENAME] or None,
        source=list(texts),
        created={},
        warnings=warnings[:MAX_STORED_WARNINGS],
        created_by=actor.id,
    )
    db.add(run)
    db.flush()
    report = importing.apply_bundle(
        db,
        project.id,
        bundle,
        actor_id=actor.id,
        action="import_scenario",
        extra={
            "schema_version": S.SCHEMA_VERSION,
            "run_id": run.id,
            "excluded": sorted(skip),
        },
    )
    run.created = dict(report.created)
    db.flush()
    return run, report


def runs(db: Session, actor: Actor) -> list[models.ImportRun]:
    require_import(actor)
    return list(db.scalars(select(models.ImportRun).order_by(models.ImportRun.id.desc())))


def get_run(db: Session, actor: Actor, run_id: int) -> models.ImportRun:
    require_import(actor)
    run = db.scalar(select(models.ImportRun).where(models.ImportRun.id == run_id))
    if run is None:
        raise NotFoundError("Импорт не найден")
    return run


def source_text(run: models.ImportRun) -> str:
    """Что именно пришло: один файл как есть, части — друг за другом с заголовками."""
    if len(run.source) == 1:
        return run.source[0]
    return "\n\n".join(
        f"===== Файл {n} =====\n{text}" for n, text in enumerate(run.source, start=1)
    )
