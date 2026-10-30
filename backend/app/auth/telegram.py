"""Telethon: бот для входа и юзербот (StringSession) для проверки членства.

Бот и юзербот живут в том же процессе и event loop, что и FastAPI. На этапе 2 юзербот
получит индекс тем и медиа; сейчас он нужен только для списка участников чата.
"""

import asyncio
import contextlib
import io
import logging
import re
from datetime import timedelta

from telethon import TelegramClient, events
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
            try:
                self.userbot = TelegramClient(
                    StringSession(s.tg_session), s.tg_api_id, s.tg_api_hash
                )
                await self.userbot.connect()
                if await self.userbot.is_user_authorized():
                    self.membership = TelethonMembership(self.userbot, s.tg_chat_id)
                else:
                    log.error("сессия юзербота недействительна (TG_SESSION)")
                    await self.userbot.disconnect()
                    self.userbot = None
            except Exception:
                log.exception("не удалось подключить юзербота")
                self.userbot = None
        else:
            log.warning("TG_SESSION или TG_CHAT_ID не заданы: членство в чате не проверяется")

        self._recheck_task = asyncio.create_task(self._recheck_loop(), name="membership-recheck")

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
