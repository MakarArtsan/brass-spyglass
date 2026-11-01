"""Подключение юзербота: причина сбоя понятна и видна на экране «Telegram», сессия чистится от мусора."""

import pytest
from telethon import errors

from app.auth import telegram as tg
from app.auth.tokens import LoginTokenStore
from app.config import Settings, get_settings
from tests.conftest import login

# --- причина по-русски --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "needle"),
    [
        (errors.AuthKeyDuplicatedError(request=None), "с двух мест одновременно"),
        (errors.AuthKeyUnregisteredError(request=None), "больше не принимает эту сессию"),
        (errors.SessionRevokedError(request=None), "больше не принимает эту сессию"),
        (errors.UserDeactivatedBanError(request=None), "заблокирован"),
        (errors.ApiIdInvalidError(request=None), "TG_API_ID"),
        (ValueError("Not a valid string"), "не похожа на сессию"),
        (TimeoutError("timed out"), "Нет связи с Telegram"),
        (RuntimeError("что-то новое"), "RuntimeError: что-то новое"),
    ],
)
def test_the_reason_says_what_to_do(exc, needle):
    assert needle in tg.explain_userbot_error(exc)


# --- сессия из переменной окружения -----------------------------------------------------------------


@pytest.mark.parametrize(
    "pasted",
    ['"1ABC"', "'1ABC'", " 1ABC ", "1ABC\n", "1A\nBC", '  "1A BC"\r\n'],
)
def test_the_session_is_cleaned_of_quotes_and_whitespace(pasted, monkeypatch):
    monkeypatch.setenv("TG_SESSION", pasted)
    assert Settings().tg_session == "1ABC"


# --- запуск сервиса с подставным клиентом --------------------------------------------------------------


class FakeClient:
    """Клиент без сети. `plan` — что делать при каждом подключении: исключение или авторизован ли."""

    plan: list = []
    created: list = []

    def __init__(self, session, *_args, **_kwargs):
        self.session = session
        self.disconnected = False
        FakeClient.created.append(self)

    async def start(self, **_kwargs):
        return self

    async def get_me(self):
        return type("Me", (), {"username": "brass_bot"})()

    def add_event_handler(self, *_args, **_kwargs):
        return None

    async def connect(self):
        step = FakeClient.plan.pop(0) if FakeClient.plan else True
        if isinstance(step, Exception):
            raise step
        self.authorized = step

    async def is_user_authorized(self):
        return self.authorized

    async def disconnect(self):
        self.disconnected = True


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "1")
    monkeypatch.setenv("TG_API_HASH", "hash")
    monkeypatch.setenv("TG_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TG_SESSION", "1ABCDEF")
    monkeypatch.setenv("TG_CHAT_ID", "-1001234567890")
    get_settings.cache_clear()
    monkeypatch.setattr(tg, "TelegramClient", FakeClient)
    monkeypatch.setattr(tg, "StringSession", lambda value="": value)
    monkeypatch.setattr(tg, "CONNECT_PAUSE_SEC", 0)
    FakeClient.plan, FakeClient.created = [], []
    yield tg.TelegramService(get_settings(), LoginTokenStore())
    get_settings.cache_clear()


async def start(service):
    await service.start()
    if service._recheck_task:
        service._recheck_task.cancel()


async def test_a_good_session_connects_and_leaves_no_error(service):
    await start(service)
    assert service.userbot is not None and service.userbot_error is None


async def test_an_unauthorized_session_is_reported_and_not_kept(service):
    FakeClient.plan = [False]
    await start(service)
    assert service.userbot is None
    assert "не принимает эту сессию" in service.userbot_error
    assert FakeClient.created[-1].disconnected is True


async def test_a_revoked_session_is_reported_without_retries(service):
    FakeClient.plan = [errors.AuthKeyDuplicatedError(request=None)]
    await start(service)
    assert service.userbot is None and "с двух мест" in service.userbot_error
    assert len([c for c in FakeClient.created if c.session == "1ABCDEF"]) == 1  # повтор не нужен


async def test_a_network_hiccup_at_start_is_retried(service):
    FakeClient.plan = [OSError("network unreachable"), TimeoutError("slow"), True]
    await start(service)
    assert service.userbot is not None and service.userbot_error is None


async def test_a_network_that_never_comes_back_gives_up_with_the_reason(service):
    FakeClient.plan = [OSError("down")] * 5
    await start(service)
    assert service.userbot is None and "Нет связи с Telegram" in service.userbot_error


# --- экран «Telegram» --------------------------------------------------------------------------------


def test_the_status_carries_the_reason(seeded_client):
    login(seeded_client, "owner", "Артём")
    seeded_client.app.state.tg.userbot_error = "Telegram не принимает эту сессию (TG_SESSION)"
    data = seeded_client.get("/api/tg/status").json()
    assert data["userbot_error"].startswith("Telegram не принимает")
    assert data["connected"] is False
