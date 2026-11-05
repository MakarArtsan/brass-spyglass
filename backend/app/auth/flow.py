"""Сценарий входа: профиль из Telegram → проверка членства → участник на сайте."""

import asyncio
import hashlib
import hmac
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from sqlalchemy import select

from app import db as database
from app import models
from app.auth.membership import MembershipChecker, MembershipUnavailable
from app.config import Settings
from app.services import users


class LoginOutcome(StrEnum):
    OK = "ok"
    NOT_MEMBER = "not_member"
    UNAVAILABLE = "unavailable"


@dataclass
class TgProfile:
    tg_id: int
    username: str | None
    name: str
    load_avatar: Callable[[], Awaitable[bytes | None]] | None = None


@dataclass
class LoginResult:
    outcome: LoginOutcome
    user_id: int | None = None
    name: str | None = None


@dataclass
class Decision:
    outcome: LoginOutcome
    # В каких чатах проектов состоит человек (чат → да/нет/неизвестно). None — Telegram не ответил,
    # членство неизвестно: проекты человека остаются как были.
    chats: dict[int, bool | None] | None = None


def _project_chats() -> set[int]:
    with database.session_factory()() as session:
        return {c for c in session.scalars(select(models.Project.tg_chat_id)) if c is not None}


def _confirmed_recently(tg_id: int, settings: Settings) -> bool:
    with database.session_factory()() as session:
        return users.confirmed_recently(
            session, tg_id, timedelta(hours=settings.members_fallback_hours)
        )


async def _decide(tg_id: int, membership: MembershipChecker, settings: Settings) -> Decision:
    """Входить может суперадмин (всегда: сайт доступен ещё до подключения юзербота).

    С самообслуживанием (по умолчанию) — любой пользователь Telegram: проектов у него может не
    быть, он создаст свой, а чаты проектов лишь привязывают его к уже существующим. Без него —
    только тот, кто состоит в чате хотя бы одного проекта; Telegram не отвечает — по последней
    проверке не старше `members_fallback_hours`: сбой связи не выбрасывает команду с сайта."""
    superadmin = settings.is_superadmin(tg_id)
    chat_ids = await asyncio.to_thread(_project_chats)
    try:
        chats = await membership.chats_of(tg_id, chat_ids)
    except MembershipUnavailable:
        chats = None
    if settings.self_service_projects:
        return Decision(LoginOutcome.OK, chats)
    if chats is not None:
        if superadmin or any(chats.values()):
            return Decision(LoginOutcome.OK, chats)
        if all(state is False for state in chats.values()):
            return Decision(LoginOutcome.NOT_MEMBER, chats)
        # ни в одном из прочитанных чатов человека нет, но часть чатов не прочиталась
    if superadmin or await asyncio.to_thread(_confirmed_recently, tg_id, settings):
        return Decision(LoginOutcome.OK, None)
    return Decision(LoginOutcome.UNAVAILABLE)


def _write_avatar(settings: Settings, tg_id: int, data: bytes) -> str:
    rel = f"avatars/{tg_id}.jpg"
    path = settings.cache_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel


def _upsert(
    settings: Settings,
    profile: TgProfile,
    avatar_path: str | None,
    chats: dict[int, bool | None] | None,
) -> tuple[int, str]:
    with database.session_factory()() as session:
        user = users.upsert_from_telegram(
            session,
            tg_id=profile.tg_id,
            username=profile.username,
            name=profile.name,
            avatar_path=avatar_path,
            owner_tg_id=settings.owner_tg_id,
            chats=chats,
        )
        session.commit()
        return user.id, user.name


async def authenticate(
    profile: TgProfile, membership: MembershipChecker, settings: Settings
) -> LoginResult:
    """Общая часть входа через бота и через Login Widget."""
    decision = await _decide(profile.tg_id, membership, settings)
    if decision.outcome is not LoginOutcome.OK:
        return LoginResult(decision.outcome)

    avatar_path: str | None = None
    if profile.load_avatar is not None:
        try:
            data = await profile.load_avatar()
        except Exception:  # аватар — украшение, вход из-за него не срываем
            data = None
        if data:
            avatar_path = await asyncio.to_thread(_write_avatar, settings, profile.tg_id, data)

    user_id, name = await asyncio.to_thread(_upsert, settings, profile, avatar_path, decision.chats)
    return LoginResult(LoginOutcome.OK, user_id, name)


# --- Telegram Login Widget: запасной вариант входа -------------------------------------------

WIDGET_MAX_AGE_SEC = 300


def verify_widget(data: dict[str, str], bot_token: str, now: float | None = None) -> bool:
    """Проверка подписи Telegram Login Widget (https://core.telegram.org/widgets/login)."""
    received = data.get("hash", "")
    fields = {k: v for k, v in data.items() if k != "hash"}
    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return False
    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError:
        return False
    return (now if now is not None else time.time()) - auth_date <= WIDGET_MAX_AGE_SEC
