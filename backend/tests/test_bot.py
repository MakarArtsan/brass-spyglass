"""Хендлер /start бота входа — на подставных событиях, без сети."""

from types import SimpleNamespace

from app.auth import telegram as tg
from app.auth.tokens import LoginTokenStore
from app.config import get_settings
from tests.test_auth import FakeMembership


class FakeClient:
    async def download_profile_photo(self, sender, file):
        file.write(b"avatar")
        return "ok"


class FakeEvent:
    def __init__(self, text: str, tg_id: int = 5001, is_private: bool = True) -> None:
        self.raw_text = text
        self.is_private = is_private
        self.client = FakeClient()
        self.sent: list[str] = []
        self._sender = SimpleNamespace(
            id=tg_id, first_name="Петя", last_name="Иванов", username="petya"
        )

    async def get_sender(self):
        return self._sender

    async def respond(self, text: str) -> None:
        self.sent.append(text)


def _service(members: FakeMembership) -> tg.TelegramService:
    service = tg.TelegramService(get_settings(), LoginTokenStore())
    service.membership = members
    return service


async def test_start_with_valid_token_confirms_login(db):
    service = _service(FakeMembership({5001}))
    token = service.tokens.create()
    event = FakeEvent(f"/start {token}")
    await service._on_message(event)
    assert event.sent == [tg.MSG_OK.format(name="Петя Иванов")]
    assert await service.tokens.wait(token, 1) is not None


async def test_start_by_a_stranger_does_not_confirm(db):
    service = _service(FakeMembership({1}))
    token = service.tokens.create()
    event = FakeEvent(f"/start {token}")
    await service._on_message(event)
    assert event.sent == [tg.MSG_NOT_MEMBER]
    assert service.tokens.claim(token) is None


async def test_expired_or_unknown_token_asks_to_retry(db):
    service = _service(FakeMembership({5001}))
    event = FakeEvent("/start nope")
    await service._on_message(event)
    assert event.sent == [tg.MSG_EXPIRED]


async def test_bare_start_and_other_text_show_help(db):
    service = _service(FakeMembership({5001}))
    for text in ("/start", "привет"):
        event = FakeEvent(text)
        await service._on_message(event)
        assert event.sent == [tg.MSG_HELLO]


async def test_group_messages_are_ignored(db):
    service = _service(FakeMembership({5001}))
    event = FakeEvent("/start whatever", is_private=False)
    await service._on_message(event)
    assert event.sent == []


async def test_telegram_outage_says_so_and_keeps_token_usable(db):
    service = _service(FakeMembership(down=True))
    token = service.tokens.create()
    event = FakeEvent(f"/start {token}")
    await service._on_message(event)
    assert event.sent == [tg.MSG_UNAVAILABLE]
    assert service.tokens.get(token) is not None
