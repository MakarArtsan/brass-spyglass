"""Импорт сценария: промпт для LLM, пример, проверка файла с предпросмотром, создание.

Проверка ничего не пишет. Создание перепроверяет файл на сервере и идёт одной транзакцией запроса.
Права (владелец и режиссёр) и «только в пустой проект» проверяет сервис, не роутер.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app import models, scope
from app.api import serialize
from app.api.access import CtxDep
from app.api.entities import ActorDep, DbDep
from app.auth import session
from app.scenario import prompt
from app.services import scenario_import as svc

router = APIRouter(prefix="/import", dependencies=[Depends(session.same_origin)])

Text = Annotated[str, StringConstraints(max_length=svc.MAX_TEXT_CHARS)]


class ParamsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_min_sec: int | None = Field(default=None, ge=1, le=100_000)
    target_max_sec: int | None = Field(default=None, ge=1, le=100_000)
    max_shot_sec: float | None = Field(default=None, gt=0, le=3600)


class CheckIn(ParamsIn):
    texts: list[Text] = Field(min_length=1, max_length=svc.MAX_TEXTS)


class ApplyIn(CheckIn):
    exclude: list[Annotated[str, StringConstraints(max_length=32)]] = Field(
        default_factory=list, max_length=5000
    )
    names: list[Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=list, max_length=svc.MAX_TEXTS
    )


def _issues(result: Any) -> list[dict[str, str]]:
    return [{"level": i.level, "message": i.message, "where": i.where} for i in result.issues]


def _run(db: Any, run: models.ImportRun, people: dict[int, dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": run.id,
        "created_at": run.created_at,
        "created_by": people.get(run.created_by) if run.created_by else None,
        "filename": run.filename,
        "schema_version": run.schema_version,
        "parts": len(run.source),
        "created": run.created,
        "warnings": len(run.warnings),
    }


@router.get("/prompt")
def get_prompt(
    ctx: CtxDep,
    actor: ActorDep,
    target_min_sec: Annotated[int | None, Query(ge=1, le=100_000)] = None,
    target_max_sec: Annotated[int | None, Query(ge=1, le=100_000)] = None,
    max_shot_sec: Annotated[float | None, Query(gt=0, le=3600)] = None,
    language: Annotated[str, Query(max_length=8)] = "en",
) -> Response:
    """`import-prompt.md` с подставленными параметрами проекта."""
    svc.require_import(actor)
    params = svc.params_for(
        ctx.project,
        target_min_sec=target_min_sec,
        target_max_sec=target_max_sec,
        max_shot_sec=max_shot_sec,
    )
    return Response(
        svc.prompt_for(ctx.project, params, language),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=import-prompt.md"},
    )


@router.get("/example")
def get_example(actor: ActorDep) -> Response:
    """Готовый файл «Битвы при кривом зеркале»: как выглядит правильный ответ."""
    svc.require_import(actor)
    return Response(
        prompt.example_text(),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=project-example.json"},
    )


@router.post("/check")
def check(body: CheckIn, db: DbDep, ctx: CtxDep, actor: ActorDep) -> dict[str, Any]:
    params = svc.params_for(
        ctx.project,
        target_min_sec=body.target_min_sec,
        target_max_sec=body.target_max_sec,
        max_shot_sec=body.max_shot_sec,
    )
    checked = svc.check(db, actor, ctx.project, body.texts, params)
    result = checked.result
    return {
        "ok": result.ok,
        "can_apply": result.ok and checked.empty,
        "empty": checked.empty,
        "not_empty_reason": None if checked.empty else svc.NOT_EMPTY,
        "parts": result.parts,
        "issues": _issues(result),
        "errors": len(result.errors),
        "warnings": len(result.warnings),
        "fixes": len(result.fixes),
        "preview": checked.preview,
    }


@router.post("/apply", status_code=status.HTTP_201_CREATED)
def apply(body: ApplyIn, db: DbDep, ctx: CtxDep, actor: ActorDep) -> dict[str, Any]:
    params = svc.params_for(
        ctx.project,
        target_min_sec=body.target_min_sec,
        target_max_sec=body.target_max_sec,
        max_shot_sec=body.max_shot_sec,
    )
    run, report = svc.apply(
        db, actor, ctx.project, body.texts, params, exclude=body.exclude, names=body.names
    )
    return {
        "run": _run(db, run, serialize.authors(db, {run.created_by})),
        "created": dict(report.created),
        "warnings": len(run.warnings),
        "slug": db.info[scope.PROJECT_SLUG],
    }


@router.get("/runs")
def runs(db: DbDep, actor: ActorDep) -> list[dict[str, Any]]:
    rows = svc.runs(db, actor)
    people = serialize.authors(db, {r.created_by for r in rows})
    return [_run(db, r, people) for r in rows]


@router.get("/runs/{run_id}/source")
def run_source(run_id: int, db: DbDep, actor: ActorDep) -> Response:
    """Что именно пришло при импорте — как было отправлено, без разбора."""
    run = svc.get_run(db, actor, run_id)
    return Response(
        svc.source_text(run),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=import-{run.id}.txt"},
    )
