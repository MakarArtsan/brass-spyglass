"""Точка входа: один процесс отдаёт API, SSE и собранный React-фронтенд."""

import asyncio
import logging
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app import db as database
from app import events, uploads
from app.api import animatic, dashboard, entities, health, me
from app.api import auth as auth_api
from app.api import events as events_api
from app.api import files as files_api
from app.api import telegram as telegram_api
from app.auth.telegram import TelegramService
from app.auth.tokens import LoginTokenStore
from app.config import Settings, get_settings
from app.migrate import upgrade_to_head
from app.permissions import PermissionDenied
from app.services import projects, seed
from app.services.core import ConflictError, NotFoundError, ValidationError
from app.tg import runtime as telegram_runtime
from app.tg.indexer import Indexer
from app.tg.telethon_gateway import TelethonGateway
from app.worker import JobRunner

log = logging.getLogger("app")

# Эти пути gzip не трогаем: SSE нельзя буферизовать, а куски видео (Range) и zip уже сжаты.
NO_GZIP_PREFIXES = (
    "/api/files/",
    "/api/uploads",
    "/api/auth/login-token",
    "/api/entities/",
    "/api/events",
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
    await app.state.tg.start()
    indexer = await _start_indexer(app, settings)
    try:
        yield
    finally:
        if indexer is not None:
            await indexer.stop()
        telegram_runtime.reset()
        await app.state.tg.stop()
        await app.state.jobs.stop()


async def _start_indexer(app: FastAPI, settings: Settings) -> Indexer | None:
    """Индексатор стартует, только если юзербот подключён и задан чат (TG_SESSION, TG_CHAT_ID)."""
    userbot, chat_id = app.state.tg.userbot, settings.tg_chat_id
    if userbot is None or chat_id is None:
        return None
    shutil.rmtree(settings.tg_tmp_dir, ignore_errors=True)  # недокачанное с прошлого запуска
    gateway = TelethonGateway(userbot, chat_id)
    indexer = Indexer(gateway, database.session_factory(), settings)
    telegram_runtime.gateway = gateway
    telegram_runtime.indexer = indexer
    telegram_runtime.loop = asyncio.get_running_loop()
    await indexer.start()
    return indexer


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
    app.include_router(health.router, prefix="/api")
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(me.router, prefix="/api")
    app.include_router(entities.router, prefix="/api")
    app.include_router(dashboard.router, prefix="/api")
    app.include_router(animatic.router, prefix="/api")
    app.include_router(telegram_api.router, prefix="/api")
    app.include_router(files_api.router, prefix="/api")
    app.include_router(events_api.router, prefix="/api")

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
