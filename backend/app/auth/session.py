"""Сессия: подписанная httpOnly-cookie на 30 дней. Имя, @username и аватар — из Telegram."""

import logging
import secrets
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app import models
from app.config import Settings, get_settings
from app.constants import Role
from app.db import get_db
from app.permissions import Actor
from app.services import users

log = logging.getLogger(__name__)

COOKIE_NAME = "bs_session"
_SALT = "brass-spyglass-session"
_fallback_secret = secrets.token_urlsafe(32)


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    secret = settings.session_secret
    if not secret:
        # Без SESSION_SECRET сессии живут до перезапуска; /api/health сообщает об этом.
        secret = _fallback_secret
    return URLSafeTimedSerializer(secret, salt=_SALT)


def issue(response: Response, user_id: int, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    token = _serializer(settings).dumps({"uid": user_id})
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def read(token: str | None, settings: Settings | None = None) -> int | None:
    if not token:
        return None
    settings = settings or get_settings()
    try:
        data = _serializer(settings).loads(token, max_age=settings.session_days * 86400)
    except BadSignature:
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None


def current_user(
    db: Annotated[Session, Depends(get_db)],
    bs_session: Annotated[str | None, Cookie()] = None,
) -> models.User:
    uid = read(bs_session)
    user = db.get(models.User, uid) if uid is not None else None
    if user is None or user.access_revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход")
    users.touch_seen(db, user)
    return user


def actor_of(user: Annotated[models.User, Depends(current_user)]) -> Actor:
    return Actor(id=user.id, role=Role(user.role))


def same_origin(request: Request) -> None:
    """Защита от CSRF: запись только с нашего сайта (поверх SameSite=Lax)."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if not origin:
        return
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    if origin.split("://", 1)[-1] != host:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Чужой источник запроса")
