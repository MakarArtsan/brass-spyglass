"""Сценарий входа: профиль из Telegram → проверка членства → участник на сайте."""

import asyncio
import hashlib
import hmac
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from app import db as database
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


async def _is_allowed(
    tg_id: int, membership: MembershipChecker, settings: Settings
) -> LoginOutcome:
    # Владелец входит всегда: так сайт доступен ещё до подключения юзербота.
    if settings.owner_tg_id is not None and tg_id == settings.owner_tg_id:
        return LoginOutcome.OK
    try:
        return LoginOutcome.OK if await membership.is_member(tg_id) else LoginOutcome.NOT_MEMBER
    except MembershipUnavailable:
        return LoginOutcome.UNAVAILABLE


def _write_avatar(settings: Settings, tg_id: int, data: bytes) -> str:
    rel = f"avatars/{tg_id}.jpg"
    path = settings.cache_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel


def _upsert(settings: Settings, profile: TgProfile, avatar_path: str | None) -> tuple[int, str]:
    with database.session_factory()() as session:
        user = users.upsert_from_telegram(
            session,
            tg_id=profile.tg_id,
            username=profile.username,
            name=profile.name,
            avatar_path=avatar_path,
            owner_tg_id=settings.owner_tg_id,
        )
        session.commit()
        return user.id, user.name


async def authenticate(
    profile: TgProfile, membership: MembershipChecker, settings: Settings
) -> LoginResult:
    """Общая часть входа через бота и через Login Widget."""
    outcome = await _is_allowed(profile.tg_id, membership, settings)
    if outcome is not LoginOutcome.OK:
        return LoginResult(outcome)

    avatar_path: str | None = None
    if profile.load_avatar is not None:
        try:
            data = await profile.load_avatar()
        except Exception:  # аватар — украшение, вход из-за него не срываем
            data = None
        if data:
            avatar_path = await asyncio.to_thread(_write_avatar, settings, profile.tg_id, data)

    user_id, name = await asyncio.to_thread(_upsert, settings, profile, avatar_path)
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
