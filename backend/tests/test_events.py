"""Живые обновления: события уходят только после коммита, откат их не рассылает."""

import asyncio
import json
import threading

import pytest
from sqlalchemy.orm import Session

from app import events
from app.constants import JobType
from app.events import EventBus
from app.services import jobs
from app.services.core import log_activity
from tests.factories import make_user


@pytest.fixture
async def bus(monkeypatch: pytest.MonkeyPatch) -> EventBus:
    """Свежая шина, привязанная к циклу теста; глобальная подменяется, чтобы слушатели SQLAlchemy
    публиковали сюда."""
    fresh = EventBus()
    fresh.bind(asyncio.get_running_loop())
    monkeypatch.setattr(events, "bus", fresh)
    return fresh


async def _next(queue: asyncio.Queue[dict]) -> dict:
    async with asyncio.timeout(1):
        return await queue.get()


@pytest.fixture
def actor(db: Session) -> int:
    """Настоящий участник: журнал и задачи ссылаются на пользователя внешним ключом."""
    user = make_user(db)
    db.commit()
    return user.id


async def test_publish_from_another_thread_reaches_subscriber(bus: EventBus):
    with bus.subscribe() as queue:
        threading.Thread(target=lambda: bus.publish({"type": "x"})).start()
        assert await _next(queue) == {"type": "x"}


async def test_event_is_sent_only_after_commit(bus: EventBus, db: Session, actor: int):
    with bus.subscribe() as queue:
        log_activity(db, actor, "update", "shot", 7, {"status": "done"})
        db.flush()
        await asyncio.sleep(0.05)
        assert queue.empty(), "до коммита клиент не должен ничего получить"

        db.commit()
        event = await _next(queue)
        assert event == {
            "type": "activity",
            "action": "update",
            "entity_type": "shot",
            "entity_id": 7,
            "actor_id": actor,
        }


async def test_rollback_drops_events(bus: EventBus, db: Session, actor: int):
    with bus.subscribe() as queue:
        log_activity(db, actor, "update", "shot", 7)
        db.rollback()
        db.commit()
        await asyncio.sleep(0.05)
        assert queue.empty()
        assert not db.info.get(events.PENDING)


async def test_identical_events_in_one_commit_are_sent_once(bus: EventBus, db: Session, actor: int):
    with bus.subscribe() as queue:
        for _ in range(5):
            log_activity(db, actor, "update", "shot", 7)
        log_activity(db, actor, "update", "shot", 8)
        db.commit()
        got = [await _next(queue), await _next(queue)]
        await asyncio.sleep(0.05)
        assert queue.empty()
        assert {e["entity_id"] for e in got} == {7, 8}


async def test_huge_batch_collapses_into_a_single_resync(bus: EventBus, db: Session, actor: int):
    with bus.subscribe() as queue:
        for i in range(events.MAX_EVENTS_PER_COMMIT + 1):
            log_activity(db, actor, "create", "shot", i)
        db.commit()
        assert await _next(queue) == {"type": "resync"}
        await asyncio.sleep(0.05)
        assert queue.empty()


async def test_slow_subscriber_gets_resync_instead_of_growing_memory(bus: EventBus):
    with bus.subscribe() as queue:
        for i in range(events.QUEUE_SIZE + 10):
            bus._deliver({"type": "n", "i": i})
        # Очередь переполнилась на 257-м событии: старое сброшено, первым стоит resync,
        # а последние девять событий уже после него дошли как обычно.
        assert queue.qsize() == 10
        assert await _next(queue) == {"type": "resync"}
        assert (await _next(queue))["i"] == events.QUEUE_SIZE + 1


async def test_job_events_carry_file_and_throttle_progress(bus: EventBus, db: Session, actor: int):
    with bus.subscribe() as queue:
        job = jobs.enqueue(db, JobType.PREVIEW, {"file_id": 42}, created_by=actor)
        db.commit()
        queued = await _next(queue)
        assert (queued["type"], queued["status"], queued["file_id"], queued["created_by"]) == (
            "job",
            "queued",
            42,
            actor,
        )

        for value in (0.01, 0.02, 0.03, 0.04):  # меньше шага — клиенту незачем
            jobs.set_progress(db, job.id, value)
        db.commit()
        await asyncio.sleep(0.05)
        assert queue.empty()

        jobs.set_progress(db, job.id, 0.5)
        db.commit()
        assert (await _next(queue))["progress"] == 0.5

        jobs.finish(db, job.id)
        db.commit()
        done = await _next(queue)
        assert (done["status"], done["progress"]) == ("done", 1.0)


async def test_stream_sends_hello_events_and_keepalive(bus: EventBus):
    stream = events.sse_stream(bus, keepalive=0.05)
    assert await anext(stream) == "retry: 3000\n\n"
    assert json.loads((await anext(stream)).removeprefix("data: ")) == {"type": "hello"}

    bus.publish({"type": "activity", "entity_type": "task", "entity_id": 1})
    frame = await asyncio.wait_for(anext(stream), 1)
    assert frame.startswith("data: ") and frame.endswith("\n\n")
    assert json.loads(frame.removeprefix("data: "))["entity_type"] == "task"

    assert await asyncio.wait_for(anext(stream), 1) == ": keepalive\n\n"
    await stream.aclose()


async def test_closing_the_stream_removes_the_subscription(bus: EventBus):
    stream = events.sse_stream(bus, keepalive=0.05)
    await anext(stream)
    assert bus.subscribers == 1
    await stream.aclose()
    assert bus.subscribers == 0


async def test_too_many_subscribers_are_refused(bus: EventBus, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(events, "MAX_SUBSCRIBERS", 1)
    with bus.subscribe(), pytest.raises(events.TooManySubscribers), bus.subscribe():
        pass


def test_event_endpoint_requires_login(client):
    response = client.get("/api/events")
    assert response.status_code == 401


def test_stream_user_accepts_a_member_and_rejects_revoked(client):
    from datetime import UTC, datetime

    from fastapi import HTTPException

    from app import db as database
    from app import models
    from app.api.events import stream_user
    from app.auth import session
    from tests.conftest import login

    login(client, "team", "Анна")
    cookie = client.cookies.get("bs_session")
    assert isinstance(stream_user(cookie), int)

    with database.session_factory()() as db:
        user = db.query(models.User).filter_by(name="Анна").one()
        user.access_revoked_at = datetime.now(UTC)
        db.commit()
    with pytest.raises(HTTPException) as exc:
        stream_user(cookie)
    assert exc.value.status_code == 401
    assert session.read(None) is None
