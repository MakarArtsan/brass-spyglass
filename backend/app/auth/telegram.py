"""Telethon: бот для входа и юзербот (StringSession) для проверки членства.

Бот и юзербот живут в том же процессе и event loop, что и FastAPI. На этапе 2 юзербот
получит индекс тем и медиа; сейчас он нужен только для списка участников чата.
"""

import asyncio
import contextlib
import io
import logging
import re
import struct
from datetime import timedelta
from pathlib import Path

from telethon import TelegramClient, errors, events
from telethon.sessions import StringSession

from app import db as database
from app import models
from app.auth import flow
from app.auth.membership import (
    DisabledMembership,
    MembershipChecker,
    MembershipUnavailable,
    TelethonMembership,
)
from app.auth.tokens import LoginTokenStore
from app.config import Settings
from app.services import users

log = logging.getLogger(__name__)

CONNECT_ATTEMPTS = 3
CONNECT_PAUSE_SEC = 3

START_RE = re.compile(r"^/start(?:@\w+)?(?:\s+(\S+))?\s*$")

MSG_HELLO = (
    "Это бот входа на сайт The Brass Spyglass. Откройте сайт и нажмите «Войти через Telegram»."
)
MSG_EXPIRED = (
    "Ссылка для входа устарела. Вернитесь на сайт и нажмите «Войти через Telegram» ещё раз."
)
MSG_NOT_MEMBER = "Доступ только для участников закрытого чата команды."
MSG_UNAVAILABLE = "Не удалось проверить участие в чате. Попробуйте ещё раз через минуту."
MSG_OK = "Готово, {name}! Вы вошли на сайт — вернитесь в браузер."


def explain_userbot_error(exc: BaseException) -> str:
    """Причина, по которой юзербот не подключился, — по-русски и с тем, что делать.
    Её видно на экране «Telegram», чтобы не лазить в логи."""
    name = exc.__class__.__name__
    if isinstance(exc, errors.AuthKeyDuplicatedError):
        return (
            "Одну и ту же сессию использовали с двух мест одновременно (например, на старой "
            "и новой копии приложения при деплое), и Telegram её аннулировал. Выпустите новую "
            "(make_session.py), задайте TG_SESSION и перезапустите приложение один раз."
        )
    if isinstance(
        exc,
        errors.AuthKeyUnregisteredError
        | errors.SessionRevokedError
        | errors.SessionExpiredError
        | errors.AuthKeyInvalidError,
    ):
        return (
            "Telegram больше не принимает эту сессию (её завершили или она устарела). "
            "Выпустите новую (make_session.py) и задайте TG_SESSION."
        )
    if isinstance(exc, errors.UserDeactivatedError | errors.UserDeactivatedBanError):
        return "Аккаунт юзербота заблокирован или удалён Telegram. Нужен другой аккаунт."
    if isinstance(exc, errors.ApiIdInvalidError):
        return "TG_API_ID и TG_API_HASH не подходят друг другу или неверны (my.telegram.org)."
    if isinstance(exc, ValueError | struct.error):
        return (
            "TG_SESSION не похожа на сессию: скопирована не полностью или с лишним. "
            "Это одна длинная строка (около 350 знаков, начинается с «1»), "
            "её make_session.py печатает целиком."
        )
    if isinstance(exc, OSError | TimeoutError):
        return f"Нет связи с Telegram ({name}: {exc}). Приложение попробовало несколько раз."
    return f"{name}: {exc}" if str(exc) else name


class TelegramService:
    """Подключения к Telegram. Без ключей приложение работает, но войти нельзя."""

    def __init__(self, settings: Settings, tokens: LoginTokenStore) -> None:
        self.settings = settings
        self.tokens = tokens
        self.bot: TelegramClient | None = None
        self.userbot: TelegramClient | None = None
        self.membership: MembershipChecker = DisabledMembership()
        self.bot_username: str = settings.tg_bot_username.lstrip("@")
        self._recheck_task: asyncio.Task[None] | None = None
        self.userbot_error: str | None = None  # почему юзербот не подключён (для экрана «Telegram»)

    @property
    def login_available(self) -> bool:
        return self.bot is not None and bool(self.bot_username)

    async def start(self) -> None:
        s = self.settings
        if not s.telegram_configured:
            log.warning(
                "Telegram не настроен (TG_API_ID, TG_API_HASH, TG_BOT_TOKEN): вход отключён"
            )
            return
        assert s.tg_api_id is not None

        try:
            self.bot = TelegramClient(StringSession(), s.tg_api_id, s.tg_api_hash)
            await self.bot.start(bot_token=s.tg_bot_token)  # type: ignore[misc]
            me = await self.bot.get_me()
            self.bot_username = self.bot_username or (me.username or "")
            self.bot.add_event_handler(self._on_message, events.NewMessage(incoming=True))
        except Exception:
            log.exception("не удалось запустить бота входа")
            self.bot = None
            return

        if s.tg_session and s.tg_chat_id is not None:
            await self._connect_userbot(s.tg_api_id, s.tg_session, s.tg_chat_id)
        else:
            log.warning("TG_SESSION или TG_CHAT_ID не заданы: членство в чате не проверяется")

        self._recheck_task = asyncio.create_task(self._recheck_loop(), name="membership-recheck")

    async def _connect_userbot(self, api_id: int, session: str, chat_id: int) -> None:
        """Подключает юзербота. Сбои связи повторяются (на старте сеть бывает не готова),
        остальное сразу уходит в `userbot_error`: неверная сессия от повтора не исправится."""
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            client: TelegramClient | None = None
            try:
                client = TelegramClient(StringSession(session), api_id, self.settings.tg_api_hash)
                await client.connect()
                if not await client.is_user_authorized():
                    await client.disconnect()
                    self.userbot_error = (
                        "Telegram не принимает эту сессию (TG_SESSION): она не авторизована. "
                        "Выпустите новую (make_session.py) и задайте TG_SESSION."
                    )
                    log.error("сессия юзербота недействительна (TG_SESSION)")
                    return
                self.userbot = client
                self.membership = TelethonMembership(client, chat_id)
                self.userbot_error = None
                return
            except Exception as exc:
                transient = isinstance(exc, OSError | TimeoutError)
                self.userbot_error = explain_userbot_error(exc)
                log.error(
                    "не удалось подключить юзербота (попытка %s): %s", attempt, self.userbot_error
                )
                if client is not None:
                    with contextlib.suppress(Exception):
                        await client.disconnect()  # type: ignore[misc]
                if not transient or attempt == CONNECT_ATTEMPTS:
                    log.debug("подробности", exc_info=True)
                    return
                await asyncio.sleep(CONNECT_PAUSE_SEC * attempt)

    async def stop(self) -> None:
        if self._recheck_task:
            self._recheck_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recheck_task
        for client in (self.bot, self.userbot):
            if client is not None:
                await client.disconnect()  # type: ignore[misc]

    # --- бот -----------------------------------------------------------------------------

    async def _on_message(self, event: events.NewMessage.Event) -> None:
        if not event.is_private:
            return
        match = START_RE.match(event.raw_text or "")
        if match is None:
            await event.respond(MSG_HELLO)
            return
        token = match.group(1)
        if not token:
            await event.respond(MSG_HELLO)
            return
        if self.tokens.get(token) is None:
            await event.respond(MSG_EXPIRED)
            return

        sender = await event.get_sender()
        name = " ".join(p for p in (sender.first_name, sender.last_name) if p) or (
            sender.username or str(sender.id)
        )

        async def load_avatar() -> bytes | None:
            buf = io.BytesIO()
            result = await event.client.download_profile_photo(sender, file=buf)  # type: ignore[union-attr]
            return buf.getvalue() if result else None

        profile = flow.TgProfile(sender.id, sender.username, name, load_avatar)
        result = await flow.authenticate(profile, self.membership, self.settings)
        match result.outcome:
            case flow.LoginOutcome.NOT_MEMBER:
                await event.respond(MSG_NOT_MEMBER)
            case flow.LoginOutcome.UNAVAILABLE:
                await event.respond(MSG_UNAVAILABLE)
            case _:
                assert result.user_id is not None
                if self.tokens.confirm(token, result.user_id):
                    await event.respond(MSG_OK.format(name=result.name))
                else:
                    await event.respond(MSG_EXPIRED)

    async def send_to_owner(self, path: Path, caption: str) -> None:
        """Бот присылает файл владельцу (копия базы). Нужно, чтобы владелец когда-то нажал Start."""
        if self.bot is None or self.settings.owner_tg_id is None:
            raise RuntimeError("бот или OWNER_TG_ID не настроены")
        await self.bot.send_file(  # type: ignore[misc]
            self.settings.owner_tg_id, str(path), caption=caption, force_document=True
        )

    # --- ежедневная проверка членства ------------------------------------------------------

    async def _recheck_loop(self) -> None:
        """Каждый час проверяет тех, у кого проверка старше суток; вышедшим закрывает доступ."""
        max_age = timedelta(hours=self.settings.membership_recheck_hours)
        while True:
            try:
                await self.recheck_members(max_age)
            except Exception:
                log.exception("ошибка проверки членства")
            await asyncio.sleep(3600)

    async def recheck_members(self, max_age: timedelta) -> int:
        """Возвращает число закрытых доступов. Ошибки Telegram доступ не закрывают."""
        revoked = 0
        due = await asyncio.to_thread(self._due_ids, max_age)
        for user_id, tg_id in due:
            if self.settings.owner_tg_id is not None and tg_id == self.settings.owner_tg_id:
                keep = True
            else:
                try:
                    keep = await self.membership.is_member(tg_id)
                except MembershipUnavailable:
                    return revoked  # Telegram недоступен — попробуем в следующий час
            await asyncio.to_thread(self._apply_recheck, user_id, keep)
            revoked += 0 if keep else 1
        return revoked

    @staticmethod
    def _due_ids(max_age: timedelta) -> list[tuple[int, int]]:
        with database.session_factory()() as session:
            return [(u.id, u.tg_id) for u in users.due_for_recheck(session, max_age) if u.tg_id]

    @staticmethod
    def _apply_recheck(user_id: int, keep: bool) -> None:
        with database.session_factory()() as session:
            user = session.get(models.User, user_id)
            if user is None:
                return
            if keep:
                users.mark_membership_ok(session, user)
            else:
                users.revoke_access(session, user)
            session.commit()
