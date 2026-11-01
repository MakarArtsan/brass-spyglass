"""Шлюз на настоящих типах Telethon (без сети).

Подставной клиент в других тестах не замечает, что Telethon называет запросы и поля иначе, чем мы
написали (так и вышло с `GetForumTopicsRequest`: в 1.45 он в `messages` и принимает `peer`).
Здесь запросы и сообщения собираются из настоящих классов библиотеки, поэтому такие расхождения
видны до выката.
"""

from datetime import UTC, datetime

import pytest
from telethon import types
from telethon.tl import custom
from telethon.tl.functions import messages as fn_messages

from app.tg import parse
from app.tg.limiter import RateLimiter
from app.tg.telethon_gateway import TelethonGateway
from app.tg.types import GENERAL_TOPIC

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
CHAT = -1001234567890


# --- настоящие сообщения Telethon ----------------------------------------------------------------


def message(**fields) -> custom.Message:
    return custom.Message(id=fields.pop("id", 10), peer_id=types.PeerChannel(1), date=NOW, **fields)


def document(
    mime: str, *attributes: types.TypeDocumentAttribute, size: int = 1000
) -> types.Document:
    return types.Document(
        id=1, access_hash=1, file_reference=b"", date=NOW, mime_type=mime, size=size, dc_id=2,
        attributes=list(attributes),
    )  # fmt: skip


def photo() -> types.Photo:
    return types.Photo(
        id=1, access_hash=1, file_reference=b"", date=NOW, dc_id=2,
        sizes=[types.PhotoSize(type="m", w=320, h=240, size=100)],
    )  # fmt: skip


def test_a_photo_is_an_image():
    info = parse.parse_message(
        message(media=types.MessageMediaPhoto(photo=photo()), message="Свет"), 5
    )
    assert info is not None and info.kind == "image" and info.caption == "Свет"


def test_a_video_with_a_file_name_is_a_video():
    video = document(
        "video/mp4",
        types.DocumentAttributeVideo(duration=12.0, w=1920, h=1080),
        types.DocumentAttributeFilename(file_name="take.mp4"),
    )
    info = parse.parse_message(message(media=types.MessageMediaDocument(document=video)), 5)
    assert info is not None and info.kind == "video" and info.file_name == "take.mp4"
    assert info.duration_sec == 12


def test_a_voice_message_is_audio():
    voice = document("audio/ogg", types.DocumentAttributeAudio(duration=3, voice=True))
    info = parse.parse_message(message(media=types.MessageMediaDocument(document=voice)), 5)
    assert info is not None and info.kind == "audio"


def test_a_pdf_is_a_document():
    pdf = document("application/pdf", types.DocumentAttributeFilename(file_name="brief.pdf"))
    info = parse.parse_message(message(media=types.MessageMediaDocument(document=pdf)), 5)
    assert info is not None and info.kind == "document" and info.file_name == "brief.pdf"


def test_a_sticker_is_not_indexed():
    sticker = document(
        "image/webp",
        types.DocumentAttributeSticker(alt="🙂", stickerset=types.InputStickerSetEmpty()),
    )
    assert (
        parse.parse_message(message(media=types.MessageMediaDocument(document=sticker)), 5) is None
    )


def test_a_link_in_the_text_is_indexed():
    text = "Референс https://example.com/ref"
    entity = types.MessageEntityUrl(offset=9, length=23)
    info = parse.parse_message(message(message=text, entities=[entity]), 5)
    assert info is not None and info.kind == "link" and info.url == "https://example.com/ref"


def test_a_plain_message_has_nothing_to_import():
    assert parse.parse_message(message(message="просто разговор"), 5) is None


# --- тема сообщения и запрос тем ----------------------------------------------------------------


def test_the_topic_of_a_message_comes_from_its_reply_header():
    gateway = TelethonGateway(client=None, chat_id=CHAT)
    gateway._forum = True
    reply = types.MessageReplyHeader(forum_topic=True, reply_to_top_id=7, reply_to_msg_id=9)
    assert gateway._topic_of(message(reply_to=reply)) == 7
    plain = types.MessageReplyHeader(forum_topic=True, reply_to_msg_id=8)
    assert gateway._topic_of(message(reply_to=plain)) == 8  # сообщение — прямо в теме
    assert gateway._topic_of(message()) == GENERAL_TOPIC
    gateway._forum = False
    assert gateway._topic_of(message(reply_to=reply)) == GENERAL_TOPIC


class ForumTopic:  # Telethon отдаёт класс с таким именем; шлюз узнаёт его по имени
    def __init__(self, id: int, title: str, top_message: int) -> None:
        self.id, self.title, self.top_message = id, title, top_message


class FakeClient:
    """Клиент без сети: запоминает запрос и отвечает так, как ответил бы Telegram."""

    def __init__(self, forum: bool, topics: list[ForumTopic] | None = None) -> None:
        self.forum, self.topics, self.requests = forum, topics or [], []

    async def get_input_entity(self, chat):
        return types.InputPeerChannel(channel_id=1234567890, access_hash=1)

    async def get_entity(self, peer):
        return types.Channel(
            id=1234567890, title="Команда", photo=types.ChatPhotoEmpty(), date=NOW,
            forum=self.forum, megagroup=True,
        )  # fmt: skip

    async def __call__(self, request):
        self.requests.append(request)
        return types.messages.ForumTopics(
            count=len(self.topics), topics=self.topics, messages=[], chats=[], users=[], pts=0,
        )  # fmt: skip


async def test_the_topics_request_is_the_one_telethon_actually_has():
    client = FakeClient(True, [ForumTopic(5, "Персонажи", 50), ForumTopic(9, "Локации", 90)])
    gateway = TelethonGateway(client, CHAT, RateLimiter(interval=0))
    topics = await gateway.topics()
    assert [(t.topic_id, t.title) for t in topics] == [(5, "Персонажи"), (9, "Локации")]
    (request,) = client.requests
    assert isinstance(request, fn_messages.GetForumTopicsRequest)
    assert isinstance(request.peer, types.InputPeerChannel)
    assert bytes(request)  # запрос сериализуется: имена и типы параметров верны


async def test_a_chat_without_topics_is_one_general_topic():
    gateway = TelethonGateway(FakeClient(False), CHAT, RateLimiter(interval=0))
    topics = await gateway.topics()
    assert [(t.topic_id, t.title) for t in topics] == [(GENERAL_TOPIC, "Команда")]


def test_telethon_has_every_name_the_gateway_uses():
    """Имена, к которым шлюз обращается у клиента, должны быть у настоящего TelegramClient."""
    from telethon import TelegramClient, events

    for name in (
        "get_input_entity",
        "get_entity",
        "get_dialogs",
        "get_messages",
        "iter_messages",
        "download_media",
        "add_event_handler",
    ):
        assert callable(getattr(TelegramClient, name)), name
    assert callable(events.NewMessage)
    for prop in (
        "photo",
        "voice",
        "audio",
        "video",
        "video_note",
        "gif",
        "document",
        "sticker",
        "file",
    ):
        assert hasattr(custom.Message, prop), prop
    assert hasattr(custom.Message, "get_entities_text")


@pytest.mark.parametrize("name", ["ForumTopic", "ForumTopicDeleted"])
def test_telethon_still_calls_forum_topics_by_these_names(name):
    assert hasattr(types, name)
