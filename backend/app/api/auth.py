"""Вход через Telegram: токен → бот подтверждает → сайт ждёт по SSE → сессия в cookie."""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import db as database
from app import models
from app.auth import flow, session
from app.config import get_settings
from app.db import get_db
from app.schemas import AuthConfigOut, LoginTokenOut, UserOut

router = APIRouter(prefix="/auth", dependencies=[Depends(session.same_origin)])

KEEPALIVE_SEC = 15


def _load_user_out(user_id: int) -> UserOut:
    with database.session_factory()() as db:
        user = db.get(models.User, user_id)
        assert user is not None
        return _user_out(user)


def _user_out(user: models.User) -> UserOut:
    out = UserOut.model_validate(user)
    out.has_avatar = bool(user.avatar_path)
    return out


@router.get("/config", response_model=AuthConfigOut)
def auth_config(request: Request) -> AuthConfigOut:
    tg = request.app.state.tg
    return AuthConfigOut(login_available=tg.login_available, bot_username=tg.bot_username)


@router.post("/login-token", response_model=LoginTokenOut)
async def create_login_token(request: Request) -> LoginTokenOut:
    tg = request.app.state.tg
    if not tg.login_available:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Вход через Telegram не настроен")
    tokens = request.app.state.tokens
    token = tokens.create()
    if token is None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток входа")
    return LoginTokenOut(
        token=token,
        bot_url=f"https://t.me/{tg.bot_username}?start={token}",
        expires_in=tokens.ttl,
    )


@router.get("/login-token/{token}/events")
async def login_events(token: str, request: Request) -> StreamingResponse:
    """SSE: ждём, пока бот подтвердит токен. События: `confirmed` или `expired`."""
    tokens = request.app.state.tokens
    if tokens.get(token) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ссылка устарела")

    async def stream() -> AsyncIterator[str]:
        yield "retry: 3000\n\n"
        while True:
            if await request.is_disconnected():
                return
            item = tokens.get(token)
            if item is None:
                yield "event: expired\ndata: {}\n\n"
                return
            try:
                await asyncio.wait_for(item.confirmed.wait(), KEEPALIVE_SEC)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield "event: confirmed\ndata: {}\n\n"
            return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/login-token/{token}/claim", response_model=UserOut)
def claim_login(
    token: str,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    """Сайт забирает подтверждённый вход и получает cookie. Токен одноразовый."""
    user_id = request.app.state.tokens.claim(token)
    user = db.get(models.User, user_id) if user_id is not None else None
    if user is None or user.access_revoked_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вход не подтверждён или ссылка устарела")
    session.issue(response, user.id)
    return _user_out(user)


@router.post("/widget", response_model=UserOut)
async def widget_login(data: dict[str, Any], request: Request, response: Response) -> UserOut:
    """Запасной вход через Telegram Login Widget (подпись проверяется токеном бота)."""
    settings = get_settings()
    fields = {k: str(v) for k, v in data.items()}
    if not settings.tg_bot_token or not flow.verify_widget(fields, settings.tg_bot_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Подпись Telegram не прошла проверку")
    try:
        tg_id = int(fields["id"])
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет id пользователя") from None
    name = " ".join(p for p in (fields.get("first_name"), fields.get("last_name")) if p)
    profile = flow.TgProfile(
        tg_id, fields.get("username"), name or fields.get("username") or str(tg_id)
    )
    result = await flow.authenticate(profile, request.app.state.tg.membership, settings)
    if result.outcome is flow.LoginOutcome.NOT_MEMBER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступ только для участников чата команды")
    if result.outcome is flow.LoginOutcome.UNAVAILABLE or result.user_id is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Не удалось проверить участие")
    session.issue(response, result.user_id)
    return await asyncio.to_thread(_load_user_out, result.user_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    session.clear(response)
