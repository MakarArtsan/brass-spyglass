"""Изоляция проектов (критерий приёмки M1): два проекта, два чата, три человека.

Человек видит проект, только если состоит в его чате; о чужих проектах он не узнаёт даже названий:
чужой и несуществующий проект неотличимы (404). Тест проходит по ВСЕМ маршрутам, список берётся из
самого приложения: новый маршрут без проверки доступа роняет тест.
"""

import re
from itertools import count

import pytest
from fastapi.testclient import TestClient

from app import db as database
from app import models, scope, signing
from app.auth import session
from app.config import get_settings
from app.constants import Role
from app.services import core, members, projects, users

A, B = "brass-spyglass", "second-film"
_tg = count(9000)


def person(name: str, memberships: dict[str, Role], tg_id: int | None = None) -> int:
    """Человек, состоящий только в перечисленных проектах (в проект фильма `users` пускает сам)."""
    with database.session_factory()() as db:
        user = users.upsert_from_telegram(
            db,
            tg_id=tg_id or next(_tg),
            username=None,
            name=name,
            avatar_path=None,
            owner_tg_id=None,
        )
        for project in db.query(models.Project).all():
            member = members.get(db, project.id, user.id)
            role = memberships.get(project.slug)
            if role is None:
                if member is not None:
                    members.leave(db, member)
            else:
                members.ensure(db, project, user, role=role)
        db.commit()
        return user.id


def act_as(client: TestClient, user_id: int | None) -> None:
    client.cookies.clear()
    if user_id is not None:
        token = session._serializer(get_settings()).dumps({"uid": user_id})
        client.cookies.set(session.COOKIE_NAME, token)


@pytest.fixture
def world(seeded_client):
    """Проект фильма (с данными Excel) и второй проект со своим набором записей."""
    with database.session_factory()() as db:
        second = models.Project(
            **{
                **projects.DEFAULT_PROJECT,
                "slug": B,
                "title": "Второй фильм",
                "tg_chat_id": -100222,
            }
        )
        db.add(second)
        db.commit()
        second_id = second.id
    with scope.project_session(second_id) as db:
        scene = models.Scene(number=1, order=1, title="Чужая сцена", planned_sec=10)
        db.add(scene)
        db.flush()
        shot = models.Shot(scene_id=scene.id, code="01.01", order=1, description="чужой шот")
        asset = models.Asset(code="CH-01", type="character", name="Чужой персонаж")
        task = models.Task(code="T-01", block="editing", title="Чужая задача")
        file = models.File(
            kind="image", source="upload", original_name="secret.png", sha256="ab" * 32
        )
        db.add_all([shot, asset, task, file])
        db.flush()
        db.add(models.Comment(entity_type="shot", entity_id=shot.id, body="чужой комментарий"))
        db.commit()
    people = {
        "alice": person("Алиса", {A: Role.TEAM}),  # только проект фильма
        "bob": person("Боб", {B: Role.DIRECTOR}),  # только второй проект
        "carol": person("Кэрол", {A: Role.GUEST, B: Role.OWNER}),  # в обоих, роли разные
        "nobody": person("Никто", {}),  # ни в одном чате
    }
    boss = person("Босс", {}, tg_id=1001)  # OWNER_TG_ID: суперадмин
    return seeded_client, people | {"boss": boss}, second_id


# --- доступ по членству ------------------------------------------------------------------------------


def test_a_person_sees_only_projects_of_their_chats_and_never_foreign_titles(world):
    client, p, _ = world
    for who, expected in (
        ("alice", [A]),
        ("bob", [B]),
        ("carol", [A, B]),
        ("nobody", []),
        ("boss", [A, B]),  # суперадмин видит всё
    ):
        act_as(client, p[who])
        assert [x["slug"] for x in client.get("/api/projects").json()] == expected, who
    act_as(client, p["bob"])
    assert "Второй фильм" in client.get("/api/projects").text
    assert "Битва" not in client.get("/api/projects").text
    assert "Битва" not in client.get("/api/session").text


def test_a_foreign_project_and_a_missing_one_look_the_same(world):
    client, p, _ = world
    act_as(client, p["bob"])
    foreign = client.get(f"/api/p/{A}/shots")
    missing = client.get("/api/p/no-such-project/shots")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "Не найдено"}


def test_roles_belong_to_the_pair_person_and_project(world):
    client, p, _ = world
    act_as(client, p["carol"])
    assert client.get(f"/api/p/{A}/me").json()["abilities"]["upload"] is False  # гость в A
    assert client.get(f"/api/p/{B}/me").json()["abilities"]["manage_users"] is True  # владелец в B
    assert (
        client.post(
            f"/api/p/{A}/tasks", json={"code": "T-90", "title": "x", "block": "editing"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/p/{B}/tasks", json={"code": "T-90", "title": "x", "block": "editing"}
        ).status_code
        == 201
    )


def test_leaving_the_chat_closes_access_and_returning_restores_the_role(world):
    client, p, _ = world
    act_as(client, p["alice"])
    assert client.get(f"/api/p/{A}/shots").status_code == 200
    with database.session_factory()() as db:
        member = db.query(models.ProjectMember).filter_by(user_id=p["alice"]).one()
        members.leave(db, member)
        db.commit()
    assert client.get(f"/api/p/{A}/shots").status_code == 404
    assert client.get("/api/projects").json() == []
    with database.session_factory()() as db:
        project = projects.get_by_slug(db, A)
        user = db.get(models.User, p["alice"])
        members.ensure(db, project, user)  # вступила снова
        db.commit()
    assert client.get(f"/api/p/{A}/shots").status_code == 200
    assert client.get(f"/api/p/{A}/me").json()["user"]["role"] == "team"


def test_an_archived_project_is_read_only_for_the_team_but_not_for_a_superadmin(world):
    client, p, _ = world
    with database.session_factory()() as db:
        projects.get_by_slug(db, A).archived_at = __import__("datetime").datetime.now(
            __import__("datetime").UTC
        )
        db.commit()
    act_as(client, p["alice"])
    assert client.get(f"/api/p/{A}/shots").status_code == 200
    assert (
        client.post(
            f"/api/p/{A}/tasks", json={"code": "T-90", "title": "x", "block": "editing"}
        ).status_code
        == 403
    )
    act_as(client, p["boss"])
    assert (
        client.post(
            f"/api/p/{A}/tasks", json={"code": "T-90", "title": "x", "block": "editing"}
        ).status_code
        == 201
    )


# --- данные не перетекают ------------------------------------------------------------------------------


def test_lists_and_cards_of_one_project_never_show_the_other(world):
    client, p, second_id = world
    act_as(client, p["bob"])
    mine = client.get(f"/api/p/{B}/shots").json()
    assert [s["code"] for s in mine] == ["01.01"] and mine[0]["description"] == "чужой шот"
    act_as(client, p["alice"])
    shots = client.get(f"/api/p/{A}/shots").json()
    assert shots and all(s["description"] != "чужой шот" for s in shots)
    assert "Чужой персонаж" not in client.get(f"/api/p/{A}/assets").text
    assert "Чужая задача" not in client.get(f"/api/p/{A}/tasks").text
    assert "secret.png" not in client.get(f"/api/p/{A}/library").text


def test_a_card_of_another_project_is_not_reachable_by_its_id(world):
    client, p, second_id = world
    with scope.project_session(second_id) as db:
        foreign = {
            "shots": db.query(models.Shot).one().id,
            "scenes": db.query(models.Scene).one().id,
            "assets": db.query(models.Asset).one().id,
        }
        file_id = db.query(models.File).one().id
    act_as(client, p["alice"])
    for kind, entity_id in foreign.items():
        assert client.get(f"/api/p/{A}/{kind}/{entity_id}").status_code == 404, kind
        assert (
            client.patch(f"/api/p/{A}/{kind}/{entity_id}", json={"comment": "x"}).status_code == 404
        )
        assert client.delete(f"/api/p/{A}/{kind}/{entity_id}").status_code == 404
    assert client.get(f"/api/p/{A}/files/{file_id}").status_code == 404
    assert (
        client.get(
            f"/api/p/{A}/comments", params={"entity_type": "shot", "entity_id": foreign["shots"]}
        ).json()
        == []
    )
    assert client.get(f"/api/p/{A}/activity").status_code in (200, 403)


def test_the_same_file_in_two_projects_is_not_a_duplicate_and_does_not_hint_at_the_other(world):
    from tests.test_files import upload

    client, p, _ = world
    data = b"\x89PNG\r\n\x1a\n" + b"x" * 200
    act_as(client, p["alice"])
    first = upload(client, data, "same.png")
    assert first.status_code == 201
    act_as(client, p["bob"])
    second = upload(
        client,
        data,
        "same.png",
        base=f"/api/p/{B}",
    )  # другой проект: дубля нет
    assert second.status_code in (201, 422), second.text  # не 409 «такой файл уже есть»
    assert "same.png" not in str(second.json().get("duplicate", ""))


def test_a_signed_link_works_only_in_its_project(world):
    client, p, second_id = world
    with scope.project_session(second_id) as db:
        file_id = db.query(models.File).one().id
    token_b = signing.sign(file_id, "original", second_id)
    assert signing.verify(token_b, file_id, "original", second_id)
    assert not signing.verify(token_b, file_id, "original", second_id + 1)
    act_as(client, p["alice"])  # в проекте A этого файла нет, подпись чужая
    assert client.get(f"/api/p/{A}/files/{file_id}/original?t={token_b}").status_code in (403, 404)


def test_notifications_and_member_lists_stay_inside_the_project(world):
    client, p, second_id = world
    act_as(client, p["bob"])
    names = [u["name"] for u in client.get(f"/api/p/{B}/users").json()]
    assert "Боб" in names and "Кэрол" in names and "Алиса" not in names
    # комментарий в проекте B уведомляет только участников B
    with scope.project_session(second_id) as db:
        actor = __import__("app.permissions", fromlist=["Actor"]).Actor(
            id=p["bob"], role=Role.DIRECTOR, project_id=second_id
        )
        shot = db.query(models.Shot).one()
        core.create(
            db,
            actor,
            "comment",
            {"entity_type": "shot", "entity_id": shot.id, "body": "привет"},
            project_id=second_id,
        )
        db.commit()
    act_as(client, p["carol"])
    assert client.get(f"/api/p/{B}/notifications").json()["unread"] == 1
    assert client.get(f"/api/p/{A}/notifications").json()["unread"] == 0  # в A ничего не пришло
    act_as(client, p["alice"])
    assert client.get(f"/api/p/{A}/notifications").json()["unread"] == 0


# --- каждый маршрут проверяет доступ -----------------------------------------------------------------


def api_routes(client: TestClient) -> list[tuple[str, str]]:
    """Все (метод, путь) приложения — из OpenAPI: FastAPI держит подключённые роутеры лениво."""
    out = []
    for path, operations in client.app.openapi()["paths"].items():
        for method in operations:
            if method in {"get", "post", "put", "patch", "delete"}:
                out.append((method.upper(), path))
    return sorted(out)


def fill(path: str, slug: str) -> str:
    """Подставляет проект и произвольные значения вместо параметров пути."""
    path = path.replace("{slug}", slug)
    return re.sub(r"\{[^}]*id\}", "1", re.sub(r"\{(?!slug)[^}]+\}", "x", path))


def project_routes(client: TestClient) -> list[tuple[str, str]]:
    return [(m, p) for m, p in api_routes(client) if p.startswith("/api/p/{slug}/")]


def test_every_project_route_refuses_strangers_and_foreign_members(world):
    """Главная защита: ни один маршрут проекта не отвечает тому, кто не в его чате, и не различает
    «чужой» и «нет такого». Список маршрутов берётся из приложения: новый без проверки роняет тест."""
    client, p, _ = world
    routes = project_routes(client)
    assert len(routes) > 60, "список маршрутов должен браться из приложения"
    for method, path in routes:
        for who, slug in (("nobody", A), ("nobody", B), ("bob", A), ("alice", B)):
            act_as(client, p[who])
            url = fill(path, slug)
            response = client.request(method, url, json={})
            assert response.status_code == 404, f"{who} {method} {url}: {response.status_code}"
            assert response.json() == {"detail": "Не найдено"}, f"{who} {method} {url}"
        act_as(client, None)
        anonymous = client.request(method, fill(path, A), json={})
        assert anonymous.status_code == 401, f"аноним {method} {path}: {anonymous.status_code}"


def test_members_get_through_every_project_route(world):
    """Обратное тому, что выше: участнику тот же маршрут не отвечает «нет проекта», иначе тест
    выше проходил бы и на сломанной проверке (404 на всё)."""
    client, p, _ = world
    act_as(client, p["boss"])
    reached = 0
    for method, path in project_routes(client):
        if path.endswith("/events"):  # поток не заканчивается
            continue
        response = client.request(method, fill(path, A), json={})
        if response.status_code == 404 and response.json() == {"detail": "Не найдено"}:
            continue  # такой карточки нет: это ответ маршрута, а не проверки проекта
        reached += 1
    assert reached > 30


def test_only_known_routes_live_outside_projects(world):
    client, *_ = world
    expected = (
        "/api/health",
        "/api/auth/",
        "/api/session",
        "/api/projects",
        "/api/users/",
        "/api/{rest}",  # заглушка 404 для неизвестных адресов
    )
    outside = {p for _, p in api_routes(client) if not p.startswith("/api/p/{slug}/")}
    stray = sorted(p for p in outside if not p.startswith(expected))
    assert stray == [], f"маршруты вне проектов без решения о доступе: {stray}"


# --- адреса в ответах всегда ведут в свой проект ---------------------------------------------------------


def api_urls(value) -> list[str]:
    """Все строки вида `/api/…` внутри ответа (ссылки на файлы, скачивание, миниатюры)."""
    if isinstance(value, str):
        return [value] if value.startswith("/api/") else []
    if isinstance(value, dict):
        return [u for v in value.values() for u in api_urls(v)]
    if isinstance(value, list):
        return [u for v in value for u in api_urls(v)]
    return []


def test_every_url_in_a_response_carries_the_project(world):
    """Ссылка без `/p/<slug>` ведёт на 404, а тестовый клиент подставляет проект сам и скрывает такую
    ошибку, поэтому адреса проверяются здесь, по тексту ответов."""
    from tests.test_files import upload

    client, p, _ = world
    act_as(client, p["boss"])
    first = upload(client, b"\x89PNG\r\n\x1a\n" + b"y" * 300, "link-check.png")
    assert first.status_code == 201, first.text
    shot = client.get(f"/api/p/{A}/shots").json()[0]
    found: list[str] = []
    for path in (
        "shots", f"shots/{shot['id']}", "scenes", "assets", "library", "dashboard", "animatic",
        "exports", "notifications", "users", "me", "project", "tg/status", "journal",
    ):  # fmt: skip
        response = client.get(f"/api/p/{A}/{path}")
        if response.status_code == 200:
            found += api_urls(response.json())
    # Ссылка на скачивание экспорта проверена в test_exports_api; здесь — файлы, миниатюры, аватары.
    assert any("/files/" in u for u in found), (
        "в ответах должны встретиться ссылки, иначе проверка пустая"
    )
    allowed = (f"/api/p/{A}/", "/api/users/")  # аватары — общие, вне проектов
    stray = sorted({u.split("?")[0] for u in found if not u.startswith(allowed)})
    assert stray == [], f"ссылки без проекта: {stray[:5]}"


def test_renaming_one_project_does_not_touch_the_other(world):
    client, p, _ = world
    act_as(client, p["carol"])  # владелец второго проекта, гость в первом
    assert client.patch(f"/api/p/{B}/project", json={"title": "Переименован"}).status_code == 200
    assert client.patch(f"/api/p/{A}/project", json={"title": "Чужое"}).status_code == 403  # гость
    titles = {x["slug"]: x["title"] for x in client.get("/api/projects").json()}
    assert titles[B] == "Переименован" and titles[A] != "Чужое"
    act_as(client, p["alice"])  # состоит только в первом
    assert client.get(f"/api/p/{A}/project").json()["title"] == titles[A]
    assert client.patch(f"/api/p/{B}/project", json={"title": "Взлом"}).status_code == 404
    act_as(client, p["bob"])  # директор второго: видит новое имя, но менять не может
    assert client.get(f"/api/p/{B}/project").json()["title"] == "Переименован"
    assert client.patch(f"/api/p/{B}/project", json={"title": "Взлом"}).status_code == 403
