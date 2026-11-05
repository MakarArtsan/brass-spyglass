"""Telethon: бот для входа и юзербот (StringSession) для проверки членства.

Бот и юзербот живут в том же процессе и event loop, что и FastAPI. Юзербот читает списки участников
чатов проектов (вход и синхронизация `project_member`) и индекс тем и медиа.
"""

import asyncio
import contextlib
import io
import logging
import re
import struct
from pathlib import Path

from sqlalchemy import select
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
from app.services import members, users

log = logging.getLogger(__name__)

CONNECT_ATTEMPTS = 3
CONNECT_PAUSE_SEC = 3
SYNC_RETRY_SEC = 600  # не все чаты прочитались — повторить раньше планового срока
EVENT_DEBOUNCE_SEC = 5.0  # несколько вступлений подряд — одно чтение списка

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
        self._sync_task: asyncio.Task[None] | None = None
        self._event_tasks: dict[int, asyncio.Task[None]] = {}
        self.userbot_account: dict[str, str | None] | None = None  # кого добавлять в чат проекта
        self.sync_pause_sec = 1.0  # между чатами: не упираться во FloodWait
        self.event_debounce_sec = EVENT_DEBOUNCE_SEC
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

        if s.tg_session:
            await self._connect_userbot(s.tg_api_id, s.tg_session)
        else:
            log.warning("TG_SESSION не задана: членство в чатах проектов не проверяется")
        if self.userbot is not None:
            self._sync_task = asyncio.create_task(self._sync_loop(), name="members-sync")

    async def _connect_userbot(self, api_id: int, session: str) -> None:
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
                self.userbot_account = await self._account_of(client)
                self.membership = TelethonMembership(client)
                client.add_event_handler(self._on_chat_action, events.ChatAction)
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

    @staticmethod
    async def _account_of(client: TelegramClient) -> dict[str, str | None] | None:
        """Имя и @username юзербота: человек должен знать, кого добавить в чат своего проекта."""
        try:
            me = await client.get_me()
        except Exception:
            log.warning("не удалось узнать аккаунт юзербота", exc_info=True)
            return None
        name = " ".join(
            p for p in (getattr(me, "first_name", None), getattr(me, "last_name", None)) if p
        )
        return {"username": getattr(me, "username", None), "name": name or None}

    async def stop(self) -> None:
        tasks = [t for t in (self._sync_task, *self._event_tasks.values()) if t is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
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

    # --- участники проектов = участники их чатов -------------------------------------------

    async def _sync_loop(self) -> None:
        """Раз в `members_sync_hours` приводит участников каждого проекта к списку его чата.
        Если какой-то чат не прочитался, повторяет через несколько минут, а не через 6 часов."""
        interval = self.settings.members_sync_hours * 3600
        while True:
            try:
                ok = await self.sync_members()
            except Exception:
                log.exception("ошибка синхронизации участников проектов")
                ok = False
            await asyncio.sleep(interval if ok else min(interval, SYNC_RETRY_SEC))

    async def sync_members(self) -> bool:
        """Чаты всех проектов → `project_member`. True — все чаты прочитаны. Ошибки Telegram никого
        не выгоняют: чат, который не прочитался, остаётся как был."""
        chats = await asyncio.to_thread(self._project_chats)
        ok = True
        for index, (project_id, chat_id) in enumerate(chats):
            if index:
                await asyncio.sleep(self.sync_pause_sec)
            ok = await self._sync_chat(project_id, chat_id) and ok
        await asyncio.to_thread(self._revoke_orphans)
        return ok

    async def sync_project(self, project_id: int, chat_id: int) -> bool:
        """Прочитать чат нового проекта сразу, не дожидаясь планового срока."""
        return await self._sync_chat(project_id, chat_id)

    async def _sync_chat(self, project_id: int, chat_id: int) -> bool:
        try:
            ids = await self.membership.participants(chat_id)
        except MembershipUnavailable:
            log.warning(
                "чат %s проекта %s не прочитан: участники остаются как были", chat_id, project_id
            )
            return False
        if not ids:
            # В живом чате всегда есть хотя бы сам юзербот: пустой список — сбой чтения, а не «все
            # вышли». Выгонять по нему нельзя.
            log.warning("чат %s вернул пустой список участников: пропускаем", chat_id)
            return False
        joined, left = await asyncio.to_thread(self._apply_sync, project_id, ids)
        if joined or left:
            log.info("проект %s: вступили %s, вышли %s", project_id, joined, left)
        return True

    # --- события чата: вступил/вышел — не ждать 6 часов ---------------------------------------

    async def _on_chat_action(self, event: events.ChatAction.Event) -> None:
        if not (event.user_joined or event.user_added or event.user_left or event.user_kicked):
            return
        chat_id = event.chat_id
        for project_id, project_chat in await asyncio.to_thread(self._project_chats):
            if project_chat == chat_id:
                self.membership.forget(chat_id)  # следующий вход прочтёт список заново
                self._schedule_chat_sync(project_id, chat_id)
                return

    def _schedule_chat_sync(self, project_id: int, chat_id: int) -> None:
        task = self._event_tasks.get(chat_id)
        if task is not None and not task.done():
            return  # уже ждём: прочтём список один раз за все события
        self._event_tasks[chat_id] = asyncio.create_task(self._sync_chat_later(project_id, chat_id))

    async def _sync_chat_later(self, project_id: int, chat_id: int) -> None:
        await asyncio.sleep(self.event_debounce_sec)
        try:
            await self._sync_chat(project_id, chat_id)
            await asyncio.to_thread(self._revoke_orphans)
        except Exception:
            log.exception("ошибка синхронизации чата %s по событию", chat_id)

    # --- работа с БД в потоке ------------------------------------------------------------------

    @staticmethod
    def _project_chats() -> list[tuple[int, int]]:
        with database.session_factory()() as session:
            rows = session.execute(
                select(models.Project.id, models.Project.tg_chat_id)
                .where(models.Project.tg_chat_id.is_not(None))
                .order_by(models.Project.id)
            )
            return [(project_id, chat_id) for project_id, chat_id in rows]

    def _apply_sync(self, project_id: int, tg_ids: set[int]) -> tuple[int, int]:
        with database.session_factory()() as session:
            project = session.get(models.Project, project_id)
            if project is None:
                return 0, 0
            result = members.sync_chat(session, project, tg_ids, self.settings)
            session.commit()
            return result

    def _revoke_orphans(self) -> int:
        if self.settings.self_service_projects:
            return 0  # войти может любой, а без проектов человек просто видит пустой экран
        with database.session_factory()() as session:
            closed = users.revoke_orphans(session, self.settings)
            session.commit()
            return closed
