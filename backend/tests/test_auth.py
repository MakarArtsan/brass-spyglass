"""Вход через Telegram: токены, членство, сессия, повторная проверка."""

import asyncio
import hashlib
import hmac
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db as database
from app import models
from app.auth import flow, session
from app.auth.membership import MembershipUnavailable
from app.auth.telegram import TelegramService
from app.auth.tokens import LoginTokenStore
from app.config import get_settings
from tests.conftest import OWNER_TG_ID

PETYA = flow.TgProfile(tg_id=5001, username="petya", name="Петя")


class FakeClient:
    async def disconnect(self) -> None:
        pass


class FakeMembership:
    def __init__(self, members: set[int] | None = None, down: bool = False) -> None:
        self.members = members or set()
        self.down = down

    async def is_member(self, tg_id: int) -> bool:
        if self.down:
            raise MembershipUnavailable("нет связи")
        return tg_id in self.members


# --- токены ---------------------------------------------------------------------------------


async def test_token_is_one_time_and_claimed_once():
    store = LoginTokenStore(ttl_sec=60)
    token = store.create()
    assert token and len(token) <= 64  # влезает в start-параметр Telegram
    assert store.claim(token) is None  # ещё не подтверждён
    assert store.confirm(token, user_id=7)
    assert not store.confirm(token, user_id=8)  # второй Start токен не перехватывает
    assert await store.wait(token, 1) == 7
    assert store.claim(token) == 7
    assert store.claim(token) is None  # одноразовый


async def test_token_expires():
    store = LoginTokenStore(ttl_sec=0)
    token = store.create()
    assert store.get(token) is None
    assert not store.confirm(token, user_id=1)
    assert await store.wait(token, 0.01) is None


def test_pending_tokens_are_capped():
    store = LoginTokenStore(ttl_sec=60)
    tokens = [store.create() for _ in range(600)]
    assert tokens.count(None) == 100


# --- проверка членства ----------------------------------------------------------------------


async def test_member_logs_in_and_gets_team_role_color_and_avatar(db):
    async def avatar() -> bytes:
        return b"\xff\xd8jpeg"

    profile = flow.TgProfile(5001, "petya", "Петя", avatar)
    result = await flow.authenticate(profile, FakeMembership({5001}), get_settings())
    assert result.outcome is flow.LoginOutcome.OK
    user = db.get(models.User, result.user_id)
    assert (user.role, user.name, user.tg_username) == ("team", "Петя", "petya")
    assert user.color.startswith("#")
    assert (get_settings().cache_dir / user.avatar_path).read_bytes() == b"\xff\xd8jpeg"


async def test_stranger_is_refused_and_not_created(db):
    result = await flow.authenticate(PETYA, FakeMembership({1}), get_settings())
    assert result.outcome is flow.LoginOutcome.NOT_MEMBER
    assert db.scalar(select(models.User).where(models.User.tg_id == 5001)) is None


async def test_owner_gets_owner_role_even_without_userbot(db):
    profile = flow.TgProfile(OWNER_TG_ID, "boss", "Артём")
    result = await flow.authenticate(profile, FakeMembership(down=True), get_settings())
    assert result.outcome is flow.LoginOutcome.OK
    assert db.get(models.User, result.user_id).role == "owner"


async def test_unavailable_telegram_is_not_treated_as_not_member(db):
    result = await flow.authenticate(PETYA, FakeMembership(down=True), get_settings())
    assert result.outcome is flow.LoginOutcome.UNAVAILABLE


async def test_relogin_updates_profile_and_keeps_role(db):
    first = await flow.authenticate(PETYA, FakeMembership({5001}), get_settings())
    user = db.get(models.User, first.user_id)
    user.role = "director"
    db.commit()
    renamed = flow.TgProfile(5001, "petr", "Пётр")
    again = await flow.authenticate(renamed, FakeMembership({5001}), get_settings())
    assert again.user_id == first.user_id
    db.expire_all()
    user = db.get(models.User, first.user_id)
    assert (user.name, user.tg_username, user.role) == ("Пётр", "petr", "director")


async def test_colors_differ_between_first_members(db):
    ids = []
    for tg_id in (7001, 7002, 7003):
        res = await flow.authenticate(
            flow.TgProfile(tg_id, None, f"U{tg_id}"), FakeMembership({tg_id}), get_settings()
        )
        ids.append(res.user_id)
    colors = {db.get(models.User, i).color for i in ids}
    assert len(colors) == 3


# --- Login Widget ---------------------------------------------------------------------------


def _widget(token: str, **extra: str) -> dict[str, str]:
    data = {"id": "5001", "first_name": "Петя", "auth_date": str(int(time.time())), **extra}
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    key = hashlib.sha256(token.encode()).digest()
    data["hash"] = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    return data


def test_widget_signature_is_verified():
    data = _widget("bot-token")
    assert flow.verify_widget(data, "bot-token")
    assert not flow.verify_widget({**data, "id": "9999"}, "bot-token")
    assert not flow.verify_widget(data, "other-token")


def test_widget_rejects_stale_auth_date():
    old = _widget("bot-token")
    assert not flow.verify_widget(old, "bot-token", now=time.time() + 3600)


# --- сессия и API ---------------------------------------------------------------------------


def _login(client: TestClient, tg_id: int = OWNER_TG_ID, name: str = "Артём") -> int:
    """Проходит путь «бот подтвердил → сайт забрал cookie». Возвращает id участника."""
    tokens = client.app.state.tokens
    token = tokens.create()
    result = asyncio.run(
        flow.authenticate(
            flow.TgProfile(tg_id, None, name), FakeMembership({tg_id}), get_settings()
        )
    )
    assert tokens.confirm(token, result.user_id)
    response = client.post(f"/api/auth/login-token/{token}/claim")
    assert response.status_code == 200, response.text
    return result.user_id


def test_api_requires_login(client):
    for path in ("/api/me", "/api/project", "/api/users"):
        assert client.get(path).status_code == 401


def test_login_sets_httponly_30_day_cookie_and_me_works(client):
    user_id = _login(client)
    cookie = next(c for c in client.cookies.jar if c.name == session.COOKIE_NAME)
    assert cookie.has_nonstandard_attr("HttpOnly")
    assert cookie.expires - time.time() == pytest.approx(30 * 86400, abs=30)
    me = client.get("/api/me").json()
    assert me["user"]["id"] == user_id
    assert me["user"]["role"] == "owner"
    assert me["abilities"] == {
        "upload": True, "export": True, "journal": True, "manage_users": True, "restore": True,
    }  # fmt: skip


def test_login_token_cannot_be_claimed_twice_or_unconfirmed(client):
    tokens = client.app.state.tokens
    token = tokens.create()
    assert client.post(f"/api/auth/login-token/{token}/claim").status_code == 404  # не подтверждён
    result = asyncio.run(
        flow.authenticate(
            flow.TgProfile(OWNER_TG_ID, None, "Артём"), FakeMembership(), get_settings()
        )
    )
    tokens.confirm(token, result.user_id)
    assert client.post(f"/api/auth/login-token/{token}/claim").status_code == 200
    assert client.post(f"/api/auth/login-token/{token}/claim").status_code == 404  # одноразовый


def test_sse_reports_confirmation(client):
    tokens = client.app.state.tokens
    token = tokens.create()
    tokens.confirm(token, 1)
    with client.stream("GET", f"/api/auth/login-token/{token}/events") as response:
        body = "".join(response.iter_text())
    assert "event: confirmed" in body


def test_sse_for_unknown_token_is_404(client):
    assert client.get("/api/auth/login-token/nope/events").status_code == 404


def test_forged_and_tampered_cookies_are_ignored(client):
    client.cookies.set(session.COOKIE_NAME, "forged")
    assert client.get("/api/me").status_code == 401
    token = session._serializer(get_settings()).dumps({"uid": 1})
    client.cookies.set(session.COOKIE_NAME, token[:-2] + "xx")
    assert client.get("/api/me").status_code == 401


def test_cookie_signed_with_another_secret_is_ignored(client, monkeypatch):
    _login(client)
    monkeypatch.setenv("SESSION_SECRET", "rotated")
    get_settings.cache_clear()
    assert client.get("/api/me").status_code == 401


def test_logout_clears_session(client):
    _login(client)
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401


def test_revoked_member_loses_access_immediately(client):
    user_id = _login(client, tg_id=5001, name="Петя")
    assert client.get("/api/me").status_code == 200
    with database.session_factory()() as db:
        from app.services import users

        users.revoke_access(db, db.get(models.User, user_id))
        db.commit()
    assert client.get("/api/me").status_code == 401


def test_foreign_origin_cannot_post(client):
    response = client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    ok = client.post("/api/auth/logout", headers={"Origin": "http://testserver"})
    assert ok.status_code == 204


def test_login_without_telegram_config_is_503_and_config_says_so(client):
    assert client.get("/api/auth/config").json() == {"login_available": False, "bot_username": ""}
    assert client.post("/api/auth/login-token").status_code == 503


def test_login_token_endpoint_builds_bot_link(client):
    client.app.state.tg.bot = FakeClient()
    client.app.state.tg.bot_username = "brass_bot"
    body = client.post("/api/auth/login-token").json()
    assert body["bot_url"] == f"https://t.me/brass_bot?start={body['token']}"
    assert body["expires_in"] == 300


def test_widget_endpoint_logs_member_in(client, monkeypatch):
    monkeypatch.setenv("TG_BOT_TOKEN", "bot-token")
    get_settings.cache_clear()
    client.app.state.tg.membership = FakeMembership({5001})
    response = client.post("/api/auth/widget", json=_widget("bot-token", username="petya"))
    assert response.status_code == 200
    assert client.get("/api/me").json()["user"]["tg_username"] == "petya"


def test_widget_endpoint_rejects_bad_signature_and_strangers(client, monkeypatch):
    monkeypatch.setenv("TG_BOT_TOKEN", "bot-token")
    get_settings.cache_clear()
    client.app.state.tg.membership = FakeMembership(set())
    assert client.post("/api/auth/widget", json=_widget("wrong")).status_code == 401
    assert client.post("/api/auth/widget", json=_widget("bot-token")).status_code == 403


def test_project_and_users_endpoints(client):
    _login(client)
    project = client.get("/api/project").json()
    assert project["title_en"] == "The Brass Spyglass"
    assert [u["name"] for u in client.get("/api/users").json()] == ["Артём"]


def test_health_reports_state_without_secrets(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["telegram"] == {"bot": False, "userbot": False, "chat_configured": False}
    assert "test-secret" not in str(body)


def test_unknown_api_path_is_json_404_not_index_html(client):
    response = client.get("/api/nothing")
    assert response.status_code == 404 and response.json() == {"detail": "Не найдено"}


# --- ежедневная проверка --------------------------------------------------------------------


def _service(members: FakeMembership) -> TelegramService:
    service = TelegramService(get_settings(), LoginTokenStore())
    service.membership = members
    return service


async def _member(tg_id: int, name: str) -> int:
    result = await flow.authenticate(
        flow.TgProfile(tg_id, None, name), FakeMembership({tg_id}), get_settings()
    )
    return result.user_id


def _age_checks(db, hours: int) -> None:
    for user in db.scalars(select(models.User)):
        user.membership_checked_at -= timedelta(hours=hours)
    db.commit()


async def test_daily_recheck_closes_access_of_those_who_left(db):
    stayed, left = await _member(6001, "Остался"), await _member(6002, "Ушёл")
    owner = await _member(OWNER_TG_ID, "Владелец")
    await asyncio.to_thread(_age_checks, db, 25)
    revoked = await _service(FakeMembership({6001})).recheck_members(timedelta(hours=24))
    assert revoked == 1
    db.expire_all()
    assert db.get(models.User, left).access_revoked_at is not None
    assert db.get(models.User, stayed).access_revoked_at is None
    assert db.get(models.User, owner).access_revoked_at is None  # владельца не закрываем


async def test_recheck_skips_fresh_checks_and_survives_telegram_outage(db):
    user = await _member(6001, "Пока свой")
    fresh = await _service(FakeMembership(set())).recheck_members(timedelta(hours=24))
    assert fresh == 0
    await asyncio.to_thread(_age_checks, db, 25)
    outage = await _service(FakeMembership(down=True)).recheck_members(timedelta(hours=24))
    assert outage == 0
    db.expire_all()
    assert db.get(models.User, user).access_revoked_at is None


async def test_returning_member_gets_access_back_on_next_login(db):
    user = await _member(6002, "Вернулся")
    await asyncio.to_thread(_age_checks, db, 25)
    await _service(FakeMembership(set())).recheck_members(timedelta(hours=24))
    db.expire_all()
    assert db.get(models.User, user).access_revoked_at is not None
    again = await _member(6002, "Вернулся")
    db.expire_all()
    assert again == user and db.get(models.User, user).access_revoked_at is None
