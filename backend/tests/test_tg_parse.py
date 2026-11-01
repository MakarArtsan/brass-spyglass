"""Разбор сообщений Telegram: что попадает в индекс, какие имена получают файлы."""

from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest

from app.tg.limiter import MAX_FLOOD_SEC, FloodTooLong, RateLimiter
from app.tg.parse import import_name, parse_message
from app.tg.types import MediaInfo

WHEN = datetime(2026, 10, 30, 21, 40, tzinfo=UTC)


def msg(**kw):
    base = dict(id=77, date=WHEN, raw_text="", message="", grouped_id=None, sender=None, sender_id=None,
                photo=None, video=None, video_note=None, gif=None, voice=None, audio=None,
                document=None, sticker=None, file=None, web_preview=None)  # fmt: skip
    return NS(**{**base, **kw})


def file(mime=None, name=None, size=None, duration=None):
    return NS(mime_type=mime, name=name, size=size, duration=duration)


class TextUrl:
    def __init__(self, url):
        self.url = url


class Url:
    pass


TextUrl.__name__ = "MessageEntityTextUrl"
Url.__name__ = "MessageEntityUrl"


def test_photo_becomes_a_jpeg_image_with_author_and_caption():
    sender = NS(first_name="Петя", last_name="Иванов", username="petya")
    info = parse_message(
        msg(
            photo=object(),
            raw_text="Дозорный Севера",
            file=file(size=250_000),
            sender=sender,
            sender_id=42,
            grouped_id=9,
        ),
        topic_id=5,
    )
    assert (info.kind, info.mime, info.topic_id, info.message_id) == ("image", "image/jpeg", 5, 77)
    assert (info.caption, info.author_name, info.author_tg_id, info.grouped_id) == (
        "Дозорный Севера",
        "Петя Иванов",
        42,
        9,
    )
    assert info.size_bytes == 250_000 and info.posted_at == WHEN


def test_video_keeps_name_duration_and_size():
    info = parse_message(
        msg(video=object(), file=file("video/mp4", "shot_0104.mp4", 9_000_000, 12.5)), 5
    )
    assert (info.kind, info.file_name, info.duration_sec, info.size_bytes) == (
        "video",
        "shot_0104.mp4",
        12.5,
        9_000_000,
    )


@pytest.mark.parametrize("attr", ["video_note", "gif"])
def test_round_video_and_gif_are_videos(attr):
    assert parse_message(msg(**{attr: object()}, file=file("video/mp4")), 5).kind == "video"


@pytest.mark.parametrize("attr", ["voice", "audio"])
def test_voice_and_audio_are_audio(attr):
    assert (
        parse_message(msg(**{attr: object()}, file=file("audio/ogg", None, 40_000, 7)), 5).kind
        == "audio"
    )


def test_supported_documents_are_indexed_by_extension_or_mime():
    pdf = parse_message(msg(document=object(), file=file("application/pdf", "script.pdf")), 5)
    assert (pdf.kind, pdf.file_name) == ("document", "script.pdf")
    nameless = parse_message(msg(document=object(), file=file("application/pdf", None)), 5)
    assert nameless.kind == "document"
    image_as_file = parse_message(msg(document=object(), file=file("image/png", "ref.png")), 5)
    assert image_as_file.kind == "image"


@pytest.mark.parametrize(
    "name, mime",
    [
        ("archive.zip", "application/zip"),
        ("clip.mkv", "video/x-matroska"),
        ("app.exe", "application/x-msdownload"),
    ],
)
def test_unsupported_documents_are_not_indexed(name, mime):
    assert parse_message(msg(document=object(), file=file(mime, name)), 5) is None


def test_stickers_are_not_references():
    assert (
        parse_message(
            msg(document=object(), sticker=object(), file=file("image/webp", "sticker.webp")), 5
        )
        is None
    )


def test_text_with_a_link_becomes_a_link_entry():
    info = parse_message(msg(raw_text="Смотрите референс: https://example.com/ref?id=3."), 5)
    assert (info.kind, info.url) == ("link", "https://example.com/ref?id=3")
    assert info.caption.startswith("Смотрите референс")


def test_link_entities_win_over_plain_text_and_hidden_urls_are_found():
    entities = [(TextUrl("https://example.com/hidden"), "тут")]
    info = parse_message(msg(raw_text="тут", get_entities_text=lambda: entities), 5)
    assert info.url == "https://example.com/hidden"
    plain = [(Url(), "https://example.org/a")]
    assert (
        parse_message(msg(raw_text="x", get_entities_text=lambda: plain), 5).url
        == "https://example.org/a"
    )


def test_internal_and_malformed_links_are_skipped():
    for text in (
        "http://127.0.0.1:8000/api/me",
        "http://localhost/x",
        "см. file:///etc/passwd",
        "просто текст",
    ):
        assert parse_message(msg(raw_text=text), 5) is None
    # внутренняя ссылка не мешает найти следующую обычную
    both = parse_message(msg(raw_text="http://10.0.0.1/a и https://example.com/b"), 5)
    assert both.url == "https://example.com/b"


def test_media_message_is_not_turned_into_a_link_even_with_a_url_in_the_caption():
    info = parse_message(
        msg(photo=object(), raw_text="источник https://example.com/x", file=file()), 5
    )
    assert info.kind == "image" and info.url is None


def test_author_falls_back_to_title_then_username_then_nothing():
    channel = parse_message(
        msg(
            photo=object(),
            file=file(),
            sender=NS(title="Канал", first_name=None, last_name=None, username=None),
        ),
        5,
    )
    assert channel.author_name == "Канал"
    nick = parse_message(
        msg(
            photo=object(), file=file(), sender=NS(first_name=None, last_name=None, username="nick")
        ),
        5,
    )
    assert nick.author_name == "nick"
    assert parse_message(msg(photo=object(), file=file()), 5).author_name is None


def test_naive_dates_are_treated_as_utc():
    info = parse_message(msg(photo=object(), file=file(), date=datetime(2026, 10, 30, 21, 40)), 5)
    assert info.posted_at.tzinfo is UTC


@pytest.mark.parametrize(
    "info, expected",
    [
        (dict(file_name="shot_0104.mp4", mime="video/mp4"), "shot_0104.mp4"),
        (dict(file_name=None, mime="audio/ogg"), "tg_5_77.ogg"),
        (dict(file_name=None, mime="image/jpeg"), "tg_5_77.jpg"),
        (dict(file_name="noext", mime="application/pdf"), "tg_5_77.pdf"),
        (dict(file_name="weird.xyz", mime="video/quicktime"), "tg_5_77.mov"),
    ],
)
def test_import_name_keeps_a_supported_name_or_builds_one(info, expected):
    media = MediaInfo(message_id=77, topic_id=5, posted_at=WHEN, kind="video", **info)
    assert import_name(media) == expected


# --- ограничитель запросов ---------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FloodWaitError(Exception):
    def __init__(self, seconds):
        super().__init__(f"flood {seconds}")
        self.seconds = seconds


async def test_requests_are_spaced_at_least_a_second_apart():
    clock = Clock()
    limiter = RateLimiter(1.0, clock=clock, sleep=clock.sleep)
    await limiter.wait()  # первый — сразу
    await limiter.wait()
    await limiter.wait()
    assert clock.sleeps == [1.0, 1.0]


async def test_a_pause_longer_than_the_interval_needs_no_extra_wait():
    clock = Clock()
    limiter = RateLimiter(1.0, clock=clock, sleep=clock.sleep)
    await limiter.wait()
    clock.now += 5
    await limiter.wait()
    assert clock.sleeps == []


async def test_flood_wait_is_waited_out_and_retried():
    clock = Clock()
    limiter = RateLimiter(1.0, clock=clock, sleep=clock.sleep)
    attempts = []

    async def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise FloodWaitError(30)
        return "готово"

    assert await limiter.call(flaky) == "готово"
    assert len(attempts) == 3 and clock.sleeps.count(31) == 2  # секунд из ответа + 1


async def test_flood_wait_gives_up_after_the_retries():
    clock = Clock()
    limiter = RateLimiter(1.0, clock=clock, sleep=clock.sleep)

    async def always():
        raise FloodWaitError(2)

    with pytest.raises(FloodWaitError):
        await limiter.call(always)


async def test_an_absurd_flood_wait_is_not_slept_through():
    clock = Clock()
    limiter = RateLimiter(1.0, clock=clock, sleep=clock.sleep)

    async def huge():
        raise FloodWaitError(MAX_FLOOD_SEC + 1)

    with pytest.raises(FloodTooLong):
        await limiter.call(huge)
    assert max(clock.sleeps, default=0) < MAX_FLOOD_SEC


async def test_other_errors_are_not_retried():
    clock = Clock()
    limiter = RateLimiter(1.0, clock=clock, sleep=clock.sleep)
    calls = []

    async def broken():
        calls.append(1)
        raise ValueError("нет")

    with pytest.raises(ValueError):
        await limiter.call(broken)
    assert len(calls) == 1
