"""Точка входа: один процесс отдаёт API, SSE и собранный React-фронтенд."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app import approvals, backup, events, models, uploads
from app import db as database
from app.api import access, animatic, dashboard, entities, health, me
from app.api import auth as auth_api
from app.api import events as events_api
from app.api import exports as exports_api
from app.api import files as files_api
from app.api import notifications as notifications_api
from app.api import projects as projects_api
from app.api import scenario_import as scenario_import_api
from app.api import telegram as telegram_api
from app.auth.telegram import TelegramService
from app.auth.tokens import LoginTokenStore
from app.config import Settings, get_settings
from app.maintenance import Maintenance
from app.migrate import upgrade_to_head
from app.permissions import PermissionDenied
from app.services import projects, seed
from app.services.core import ConflictError, NotFoundError, ValidationError
from app.tg import runtime as telegram_runtime
from app.tg.pool import IndexerPool
from app.worker import JobRunner

log = logging.getLogger("app")

# Эти пути gzip не трогаем: SSE нельзя буферизовать, а куски видео (Range) и zip уже сжаты.
NO_GZIP_PREFIXES = (
    "/api/files/",
    "/api/uploads",
    "/api/auth/login-token",
    "/api/entities/",
    "/api/events",
    "/api/exports/",
    "/api/tg/media",
)


class SelectiveGZip:
    """Сжимает JSON и статику (на медленной сети это пол-секунды), но не файлы и не SSE."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1000)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not scope["path"].startswith(NO_GZIP_PREFIXES):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)


class ImmutableStaticFiles(StaticFiles):
    """Файлы /assets имеют хэш в имени и не меняются — браузер кэширует их на год."""

    def file_response(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


DEFAULT_STATIC = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.ensure_dirs()
    database.init_engine()
    upgrade_to_head()
    with database.session_factory()() as db:
        project = projects.ensure_default_project(db)
        db.commit()
        try:
            seed.seed_if_empty(db, project.id, settings.seed_path)
            db.commit()
        except Exception:  # сайт должен подняться и без стартовых данных
            log.exception("не удалось загрузить стартовые данные из Excel")
            db.rollback()
    if not settings.session_secret:
        log.warning("SESSION_SECRET не задан: сессии пропадут при перезапуске")

    events.bus.bind(asyncio.get_running_loop())
    uploads.cleanup_stale(settings)
    app.state.upload_locks = {}
    app.state.jobs = JobRunner()
    await app.state.jobs.start()

    app.state.tokens = LoginTokenStore(settings.login_token_ttl_sec)
    app.state.tg = TelegramService(settings, app.state.tokens)
    app.state.tg.on_decision = lambda action, project_id, user_id: approvals.decide(
        app,
        action,
        project_id,
        user_id,  # type: ignore[arg-type]
    )
    await app.state.tg.start()
    pool = await _start_indexers(app, settings)
    app.state.indexer_pool = pool  # новому проекту индексатор запускается на лету
    backup.loop = asyncio.get_running_loop()
    backup.sender = app.state.tg.send_to_owner if app.state.tg.bot is not None else None
    maintenance = Maintenance(settings, app.state.jobs.wake)
    await maintenance.start()
    try:
        yield
    finally:
        await maintenance.stop()
        backup.sender = None
        if pool is not None:
            await pool.stop()
        telegram_runtime.reset()
        await app.state.tg.stop()
        await app.state.jobs.stop()


async def _start_indexers(app: FastAPI, settings: Settings) -> IndexerPool | None:
    """По индексатору на чат каждого проекта; чат собирает юзербот (TG_SESSION) или бот проекта."""
    userbot, bot = app.state.tg.userbot, app.state.tg.bot
    if userbot is None and bot is None:
        return None
    with database.session_factory()() as db:
        chats = [
            c
            for c in db.scalars(
                select(models.Project.tg_chat_id).where(
                    models.Project.approved_at.is_not(None), models.Project.archived_at.is_(None)
                )
            )
            if c is not None
        ]  # чат неподтверждённого проекта не индексируем: сбор медиа — тоже «загрузка»
    pool = IndexerPool(userbot, database.session_factory(), settings, bot=bot)
    await pool.start(chats)
    return pool


def create_app() -> FastAPI:
    app = FastAPI(title="The Brass Spyglass", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.exception_handler(PermissionDenied)
    async def _forbidden(_: Request, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValidationError)
    async def _invalid(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(ConflictError)
    async def _conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    app.add_middleware(SelectiveGZip)
    # Вне проектов: здоровье, вход, кто я и мои проекты.
    app.include_router(health.router, prefix="/api")
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(me.router, prefix="/api")
    app.include_router(projects_api.router, prefix="/api")
    # Внутри проекта: `/api/p/<slug>/…`. Общий обработчик проверяет членство и выбирает проект,
    # после чего запросы к данным проекта фильтруются сами (`scope.py`); чужое и нет проекта — 404.
    inside = {"prefix": "/api/p/{slug}", "dependencies": [Depends(access.project_access)]}
    for router in (
        me.project_router,
        entities.router,
        dashboard.router,
        animatic.router,
        exports_api.router,
        scenario_import_api.router,
        notifications_api.router,
        telegram_api.router,
        files_api.router,
    ):
        app.include_router(router, **inside)
    # Поток событий проверяет доступ сам и держит базу занятой только на проверку.
    app.include_router(events_api.router, prefix="/api/p/{slug}")

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def _api_not_found(rest: str) -> JSONResponse:
        return JSONResponse({"detail": "Не найдено"}, status_code=404)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Собранный React: статика из /assets и index.html для всех клиентских маршрутов."""
    static = Path(get_settings().frontend_dir or DEFAULT_STATIC)
    index = static / "index.html"
    if not index.is_file():
        log.warning("фронтенд не собран (%s): отдаём только API", static)
        return
    app.mount("/assets", ImmutableStaticFiles(directory=static / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def _spa(path: str) -> FileResponse:  # sync: проверка путей идёт в пуле потоков
        candidate = (static / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(static.resolve()):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
