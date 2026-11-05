"""Членство по чатам проектов: вход, синхронизация участников, события, запасной путь на 72 часа."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import db as database
from app import models
from app.auth import flow
from app.auth import membership as membership_module
from app.auth import telegram as tg
from app.auth.membership import MembershipUnavailable, TelethonMembership
from app.auth.tokens import LoginTokenStore
from app.config import get_settings
from app.db import utcnow
from app.services import projects
from tests.conftest import BOUND_CHAT, OWNER_TG_ID
from tests.test_auth import FakeMembership

pytestmark = pytest.mark.usefixtures("bound_chat")

A, B = BOUND_CHAT, -1002220000001  # чат проекта фильма и чат второго проекта


@pytest.fixture
def two(db):
    """Проект фильма (чат A) и второй проект (чат B)."""
    first = projects.get_by_slug(db, "brass-spyglass")
    assert first.tg_chat_id == A
    second = models.Project(
        **{**projects.DEFAULT_PROJECT, "slug": "second", "title": "Второй", "tg_chat_id": B}
    )
    db.add(second)
    db.commit()
    return first.id, second.id


async def login(tg_id: int, fake: FakeMembership, name: str = "Человек") -> flow.LoginResult:
    return await flow.authenticate(flow.TgProfile(tg_id, None, name), fake, get_settings())


def row(db, tg_id: int, project_id: int):
    db.expire_all()
    user = db.scalar(select(models.User).where(models.User.tg_id == tg_id))
    return None if user is None else _member(db, project_id, user.id)


def _member(db, project_id: int, user_id: int):
    return db.scalar(
        select(models.ProjectMember).where(
            models.ProjectMember.project_id == project_id, models.ProjectMember.user_id == user_id
        )
    )


def active(db, tg_id: int, project_id: int) -> bool:
    member = row(db, tg_id, project_id)
    return member is not None and member.active


def sync_journal() -> set[tuple[int, int, int]]:
    """Записи журнала о синхронизации по всем проектам (сессия `db` видит только проект фильма)."""
    with database.session_factory()() as session:
        rows = session.scalars(
            select(models.Activity).where(models.Activity.action == "members_sync")
        )
        return {(r.project_id, r.diff["joined"], r.diff["left"]) for r in rows}


def service(fake: FakeMembership) -> tg.TelegramService:
    svc = tg.TelegramService(get_settings(), LoginTokenStore())
    svc.membership = fake
    svc.sync_pause_sec = 0
    svc.event_debounce_sec = 0.05
    return svc


# --- вход по чатам проектов --------------------------------------------------------------------


async def test_a_person_joins_only_the_projects_whose_chats_they_are_in(db, two):
    a, b = two
    fake = FakeMembership(chats={A: {7001, 7003}, B: {7002, 7003}})
    assert (await login(7001, fake)).outcome is flow.LoginOutcome.OK
    assert (await login(7002, fake)).outcome is flow.LoginOutcome.OK
    assert (await login(7003, fake)).outcome is flow.LoginOutcome.OK
    assert (active(db, 7001, a), active(db, 7001, b)) == (True, False)
    assert row(db, 7001, b) is None  # запись во втором проекте даже не заводится
    assert (active(db, 7002, a), active(db, 7002, b)) == (False, True)
    assert (active(db, 7003, a), active(db, 7003, b)) == (True, True)


async def test_someone_in_no_project_chat_is_refused_and_not_created(db, two):
    result = await login(7999, FakeMembership(chats={A: {1}, B: {2}}))
    assert result.outcome is flow.LoginOutcome.NOT_MEMBER
    assert db.scalar(select(models.User).where(models.User.tg_id == 7999)) is None


async def test_nobody_but_a_superadmin_gets_in_while_no_project_has_a_chat(db):
    project = projects.get_by_slug(db, "brass-spyglass")
    project.tg_chat_id = None
    db.commit()
    assert (await login(7001, FakeMembership({7001}))).outcome is flow.LoginOutcome.NOT_MEMBER
    boss = await login(OWNER_TG_ID, FakeMembership())
    assert boss.outcome is flow.LoginOutcome.OK
    owner = row(db, OWNER_TG_ID, project.id)  # у проекта без чата людей из чата нет — владелец есть
    assert owner is not None and owner.active and owner.role == "owner"


async def test_a_superadmin_is_let_in_from_outside_every_chat_and_is_owner_where_they_are(db, two):
    a, b = two
    fake = FakeMembership(chats={A: set(), B: {OWNER_TG_ID}})
    assert (await login(OWNER_TG_ID, fake)).outcome is flow.LoginOutcome.OK
    assert row(db, OWNER_TG_ID, a) is None  # в чате проекта A их нет: участником не становятся
    assert row(db, OWNER_TG_ID, b).role == "owner"  # в чате B есть
    third = models.Project(**{**projects.DEFAULT_PROJECT, "slug": "third", "title": "Третий"})
    db.add(third)
    db.commit()  # проект без чата
    await login(OWNER_TG_ID, fake)
    assert row(db, OWNER_TG_ID, third.id).role == "owner"


async def test_leaving_one_chat_closes_only_that_project_and_returning_restores_the_role(db, two):
    a, b = two
    both = FakeMembership(chats={A: {7001}, B: {7001}})
    await login(7001, both)
    row(db, 7001, b).role = "director"
    db.commit()

    await login(7001, FakeMembership(chats={A: {7001}, B: set()}))  # вышел из чата B
    assert (active(db, 7001, a), active(db, 7001, b)) == (True, False)
    assert row(db, 7001, b).role == "director"  # запись и роль остались, авторство не теряется
    assert row(db, 7001, b).left_at is not None

    await login(7001, both)  # вернулся
    assert active(db, 7001, b) and row(db, 7001, b).role == "director"
    assert row(db, 7001, b).left_at is None


# --- запасной путь: Telegram не отвечает --------------------------------------------------------


def age_check(db, tg_id: int, hours: float | None) -> None:
    user = db.scalar(select(models.User).where(models.User.tg_id == tg_id))
    user.membership_checked_at = None if hours is None else utcnow() - timedelta(hours=hours)
    db.commit()


async def test_a_telegram_outage_does_not_lock_the_team_out_for_72_hours(db, two):
    a, _ = two
    await login(7001, FakeMembership({7001}))
    down = FakeMembership(down=True)
    for hours, expected in ((1, flow.LoginOutcome.OK), (71, flow.LoginOutcome.OK),
                            (73, flow.LoginOutcome.UNAVAILABLE)):  # fmt: skip
        age_check(db, 7001, hours)
        assert (await login(7001, down)).outcome is expected, hours
    assert active(db, 7001, a)  # сбой связи никого не выгнал из проекта


async def test_logging_in_during_an_outage_does_not_extend_the_72_hours(db, two):
    await login(7001, FakeMembership({7001}))
    age_check(db, 7001, 70)
    before = db.scalar(select(models.User.membership_checked_at).where(models.User.tg_id == 7001))
    assert (await login(7001, FakeMembership(down=True))).outcome is flow.LoginOutcome.OK
    db.expire_all()
    after = db.scalar(select(models.User.membership_checked_at).where(models.User.tg_id == 7001))
    assert after == before  # иначе вышедший из чата входил бы вечно, пока Telegram недоступен


async def test_an_outage_lets_in_only_people_the_site_already_knows(db, two):
    down = FakeMembership(down=True)
    assert (await login(7500, down)).outcome is flow.LoginOutcome.UNAVAILABLE  # не знаем такого
    assert db.scalar(select(models.User).where(models.User.tg_id == 7500)) is None
    await login(7001, FakeMembership({7001}))
    user = db.scalar(select(models.User).where(models.User.tg_id == 7001))
    user.access_revoked_at = utcnow()  # доступ закрыт синхронизацией
    db.commit()
    assert (await login(7001, down)).outcome is flow.LoginOutcome.UNAVAILABLE
    assert (await login(OWNER_TG_ID, down)).outcome is flow.LoginOutcome.OK  # суперадмин — всегда


async def test_one_unreadable_chat_does_not_hide_the_ones_that_are_readable(db, two):
    a, b = two
    fake = FakeMembership(chats={B: {7001}}, broken={A})
    assert (await login(7001, fake)).outcome is flow.LoginOutcome.OK
    assert active(db, 7001, b) and row(db, 7001, a) is None  # A не прочитался — ничего не решаем
    only_a_known = FakeMembership(chats={}, broken={A})
    # B читается и человека в нём нет, а A не прочитался: «не участник» утверждать нельзя
    assert (await login(7777, only_a_known)).outcome is flow.LoginOutcome.UNAVAILABLE


# --- синхронизация участников -----------------------------------------------------------------


async def test_sync_follows_the_chat_lists_and_keeps_roles(db, two):
    a, b = two
    await login(7001, FakeMembership({7001}))  # в обоих чатах
    await login(7002, FakeMembership(chats={A: {7002}}))
    row(db, 7002, a).role = "director"
    db.commit()

    svc = service(
        FakeMembership(chats={A: {7001}, B: {7001, 7002}})
    )  # 7002 вышел из A, вступил в B
    assert await svc.sync_members() is True
    assert (active(db, 7001, a), active(db, 7001, b)) == (True, True)
    assert (active(db, 7002, a), active(db, 7002, b)) == (False, True)
    assert row(db, 7002, a).role == "director"  # вышел, но роль и запись остались
    assert sync_journal() == {(a, 0, 1), (b, 1, 0)}

    again = service(FakeMembership(chats={A: {7001}, B: {7001, 7002}}))
    await again.sync_members()  # повтор ничего не меняет и в журнал не пишет
    assert sync_journal() == {(a, 0, 1), (b, 1, 0)}


async def test_leaving_every_chat_closes_access_and_a_superadmin_is_never_touched(db, two):
    a, b = two
    await login(7002, FakeMembership(chats={A: {7002}}))
    await login(OWNER_TG_ID, FakeMembership(chats={A: {OWNER_TG_ID}}))
    svc = service(FakeMembership(chats={A: {1}, B: {2}}))  # в списках нет ни 7002, ни владельца
    await svc.sync_members()
    db.expire_all()
    left = db.scalar(select(models.User).where(models.User.tg_id == 7002))
    boss = db.scalar(select(models.User).where(models.User.tg_id == OWNER_TG_ID))
    assert left.access_revoked_at is not None and not active(db, 7002, a)
    assert boss.access_revoked_at is None and active(db, OWNER_TG_ID, a)

    back = await login(7002, FakeMembership(chats={A: {7002}}))  # вернулся в чат и вошёл заново
    assert back.outcome is flow.LoginOutcome.OK
    db.expire_all()
    assert db.get(models.User, back.user_id).access_revoked_at is None and active(db, 7002, a)


async def test_an_empty_or_unreadable_list_changes_nothing(db, two):
    a, b = two
    await login(7001, FakeMembership({7001}))
    empty = service(FakeMembership(chats={A: set(), B: set()}))
    assert await empty.sync_members() is False  # в живом чате всегда есть юзербот: это сбой чтения
    broken = service(FakeMembership(chats={A: {1}}, broken={A, B}))
    assert await broken.sync_members() is False
    db.expire_all()
    assert (active(db, 7001, a), active(db, 7001, b)) == (True, True)
    user = db.scalar(select(models.User).where(models.User.tg_id == 7001))
    assert user.access_revoked_at is None


async def test_a_chat_that_fails_does_not_stop_the_others(db, two):
    a, b = two
    await login(7001, FakeMembership({7001}))
    await login(7002, FakeMembership({7002}))
    svc = service(FakeMembership(chats={B: {7001}}, broken={A}))  # A не читается, из B 7002 вышел
    assert await svc.sync_members() is False
    assert (active(db, 7001, a), active(db, 7002, a)) == (True, True)  # A остался как был
    assert (active(db, 7001, b), active(db, 7002, b)) == (True, False)  # B синхронизирован


async def test_people_in_the_chat_who_never_logged_in_are_not_created(db, two):
    await service(FakeMembership(chats={A: {9001, 9002}, B: {9003}})).sync_members()
    assert db.query(models.User).filter(models.User.tg_id.in_([9001, 9002, 9003])).count() == 0


async def test_sync_confirms_people_who_are_in_the_chat_for_the_fallback(db, two):
    await login(7001, FakeMembership({7001}))
    age_check(db, 7001, 100)  # подтверждение старое: запасной путь уже не сработал бы
    await service(FakeMembership(chats={A: {7001}, B: set()}, broken=set())).sync_members()
    db.expire_all()
    user = db.scalar(select(models.User).where(models.User.tg_id == 7001))
    assert utcnow() - user.membership_checked_at < timedelta(minutes=1)


# --- события и цикл --------------------------------------------------------------------------


def chat_event(chat_id: int, **kind: bool) -> SimpleNamespace:
    flags = dict(user_joined=False, user_added=False, user_left=False, user_kicked=False)
    return SimpleNamespace(chat_id=chat_id, **{**flags, **kind})


async def test_joins_and_leaves_are_picked_up_without_waiting_six_hours(db, two):
    a, b = two
    await login(7001, FakeMembership({7001}))  # состоит в обоих чатах
    fake = FakeMembership(chats={A: {7002}, B: {7001}})  # из чата A 7001 вышел, в B остался
    svc = service(fake)
    await svc._on_chat_action(chat_event(A, user_left=True))
    await svc._on_chat_action(chat_event(A, user_kicked=True))  # два события подряд — одно чтение
    await asyncio.sleep(0.3)
    assert fake.reads == [A] and A in fake.forgotten
    assert not active(db, 7001, a) and active(db, 7001, b)  # B событие не касалось


async def test_an_event_in_a_project_chat_syncs_that_chat_only(db, two):
    a, b = two
    await login(7001, FakeMembership({7001}))
    fake = FakeMembership(chats={A: {7001}, B: {1}})  # из B человек ушёл, а в A остался
    svc = service(fake)
    await svc._on_chat_action(chat_event(B, user_left=True))
    await asyncio.sleep(0.3)
    assert fake.reads == [B] and fake.forgotten == [B]
    assert not active(db, 7001, b) and active(db, 7001, a)


async def test_other_chats_and_other_events_are_ignored(db, two):
    fake = FakeMembership(chats={A: {1}, B: {1}})
    svc = service(fake)
    await svc._on_chat_action(chat_event(-1009999999999, user_joined=True))  # чужой чат
    await svc._on_chat_action(chat_event(A))  # не вступление и не выход
    await asyncio.sleep(0.2)
    assert fake.reads == [] and fake.forgotten == []


async def test_the_loop_retries_soon_after_a_failure_and_waits_when_all_is_well(
    db, two, monkeypatch
):
    monkeypatch.setattr(tg, "SYNC_RETRY_SEC", 0.02)
    failing = FakeMembership(chats={A: {1}}, broken={A})
    svc = service(failing)
    task = asyncio.create_task(svc._sync_loop())
    await asyncio.sleep(0.4)
    task.cancel()
    assert failing.reads.count(A) >= 3  # повторы идут часто, а не раз в 6 часов

    healthy = FakeMembership(chats={A: {1}, B: {1}})
    svc = service(healthy)
    task = asyncio.create_task(svc._sync_loop())
    await asyncio.sleep(0.4)
    task.cancel()
    assert healthy.reads == [A, B]  # прочитали один раз и ждём плановый срок


# --- чтение списков юзерботом --------------------------------------------------------------------


class FakeUserbot:
    def __init__(self, chats: dict[int, set[int]]) -> None:
        self.chats = chats
        self.reads: list[int] = []
        self.fail: set[int] = set()

    async def get_input_entity(self, chat_id: int) -> int:
        if chat_id not in self.chats:
            raise ValueError("нет такого чата")
        return chat_id

    async def get_dialogs(self) -> None:
        return None

    async def iter_participants(self, chat: int):
        self.reads.append(chat)
        if chat in self.fail:
            raise ConnectionError("обрыв")
        for tg_id in self.chats[chat]:
            yield SimpleNamespace(id=tg_id)


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(membership_module.time, "monotonic", lambda: now[0])
    return now


async def test_lists_are_cached_per_chat_and_refreshed_on_demand(clock):
    client = FakeUserbot({A: {1, 2}, B: {3}})
    reader = TelethonMembership(client)
    assert await reader.chats_of(1, [A, B]) == {A: True, B: False}
    assert client.reads == [A, B]
    assert await reader.chats_of(1, [A]) == {A: True}  # свой в кэше, читать заново не нужно
    assert client.reads == [A, B]
    client.chats[A].add(5)
    assert (await reader.chats_of(5, [A]))[
        A
    ] is False  # чаще раза в 10 с список не читаем (FloodWait)
    assert client.reads == [A, B]
    clock[0] += 11
    assert (await reader.chats_of(5, [A]))[A] is True  # чужого в кэше нет: читаем заново
    assert client.reads == [A, B, A]
    client.chats[A].discard(5)
    reader.forget(A)  # событие чата: список устарел
    assert (await reader.chats_of(5, [A]))[A] is False


async def test_a_failed_chat_is_unknown_and_all_failed_means_unavailable(clock):
    client = FakeUserbot({A: {1}, B: {1}})
    client.fail = {B}
    reader = TelethonMembership(client)
    assert await reader.chats_of(1, [A, B]) == {A: True, B: None}
    client.fail = {A, B}
    reader.forget(A)
    reader.forget(B)
    clock[0] += 100
    with pytest.raises(MembershipUnavailable):
        await reader.chats_of(1, [A, B])
    with pytest.raises(MembershipUnavailable):
        await reader.participants(A)
    assert await reader.chats_of(1, []) == {}  # у проектов нет чатов: спрашивать нечего


async def test_participants_always_reads_a_fresh_list(clock):
    client = FakeUserbot({A: {1}})
    reader = TelethonMembership(client)
    assert await reader.participants(A) == {1}
    client.chats[A].add(2)
    assert await reader.participants(A) == {1, 2}  # для синхронизации кэш не используется
