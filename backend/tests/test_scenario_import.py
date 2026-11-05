"""Импорт сценария через API: проверка без записи, создание одной транзакцией, права, пустой проект."""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import db as database
from app import models, scope
from app.constants import Role
from app.main import create_app
from app.scenario import convert, prompt
from app.scenario import schema as S
from app.scenario.check import Params
from app.scenario.preview import build
from app.services import projects, scenario_import
from tests.test_isolation import act_as, person
from tests.test_scenario import good, run

SLUG = "new-film"
U = f"/api/p/{SLUG}/import"
CONTENT = (
    models.Scene,
    models.Shot,
    models.Asset,
    models.SoundCue,
    models.Task,
    models.SetupPayoff,
)


def payload(data=None, **extra) -> dict:
    return {"texts": [json.dumps(data or good(), ensure_ascii=False)], **extra}


def counts(project_id: int) -> dict[str, int]:
    out = {}
    with database.session_factory()() as db:
        for model in (*CONTENT, models.ImportRun, models.Activity):
            query = select(func.count()).select_from(model).where(model.project_id == project_id)
            if model is models.Activity:
                query = query.where(models.Activity.action == "import_scenario")
            out[model.__tablename__] = db.scalar(query)
    return out


@pytest.fixture
def studio(client):
    """Пустой подтверждённый проект и люди в нём в каждой роли."""
    with database.session_factory()() as db:
        project = models.Project(
            **{
                **projects.DEFAULT_PROJECT,
                "slug": SLUG,
                "title": "Новый фильм",
                "approved_at": datetime.now(UTC),
            }
        )
        db.add(project)
        db.commit()
        project_id = project.id
    people = {
        role.value: person(role.value, {SLUG: role})
        for role in (Role.OWNER, Role.DIRECTOR, Role.TEAM, Role.GUEST)
    }
    people["boss"] = person("Босс", {}, tg_id=1001)  # суперадмин
    people["stranger"] = person("Чужой", {})
    act_as(client, people["director"])
    return client, people, project_id


# --- проверка: предпросмотр, ничего не пишется ------------------------------------------------------------


def test_check_returns_a_preview_and_writes_nothing(studio):
    client, _, pid = studio
    before = counts(pid)
    answer = client.post(f"{U}/check", json=payload())
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert data["ok"] and data["can_apply"] and data["empty"] and data["errors"] == 0
    preview = data["preview"]
    assert preview["counts"] == {
        "scenes": 1, "shots": 2, "characters": 1, "locations": 1, "assets": 1,
        "dialogue": 1, "setups": 1, "open_questions": 1,
    }  # fmt: skip
    assert preview["total_sec"] == 9 and preview["shots_sec"] == 9 and preview["title"] == "Тест"
    assert counts(pid) == before and not any(before.values())


def test_check_reports_errors_in_russian_with_an_address_and_no_preview(studio):
    client, _, _ = studio
    data = client.post(
        f"{U}/check",
        json=payload(
            {
                **good(),
                "scenes": [
                    {
                        "number": 1,
                        "title": "Х",
                        "planned_sec": 3,
                        "shots": [{"description": "д", "size": "Огромный", "duration_sec": 3}],
                    }
                ],
            }
        ),
    ).json()
    assert not data["ok"] and not data["can_apply"] and data["preview"] is None
    errors = [i for i in data["issues"] if i["level"] == "error"]
    assert errors[0]["where"] == "Сцена 1, шот 1" and "Огромный" in errors[0]["message"]


def test_check_uses_the_project_targets_unless_told_otherwise(studio):
    client, _, _ = studio
    plain = client.post(f"{U}/check", json=payload()).json()
    assert any("вне цели 300–420 с" in i["message"] for i in plain["issues"])  # цели проекта
    custom = client.post(f"{U}/check", json=payload(target_min_sec=5, target_max_sec=20)).json()
    assert not any("вне цели" in i["message"] for i in custom["issues"])
    assert (
        client.post(f"{U}/check", json=payload(target_min_sec=50, target_max_sec=20)).status_code
        == 422
    )


# --- создание ---------------------------------------------------------------------------------------------


def test_apply_creates_everything_in_one_go_with_the_importer_as_author(studio):
    client, people, pid = studio
    answer = client.post(f"{U}/apply", json=payload(names=["project.json"]))
    assert answer.status_code == 201, answer.text
    data = answer.json()
    assert data["created"]["scene"] == 1 and data["created"]["shot"] == 2 and data["slug"] == SLUG
    assert data["run"]["created"] == data["created"] and data["run"]["filename"] == "project.json"
    assert data["run"]["created_by"]["id"] == people["director"]
    with scope.project_session(pid) as db:
        for model in (
            models.Scene,
            models.Shot,
            models.Asset,
            models.SoundCue,
            models.Task,
            models.SetupPayoff,
        ):
            rows = list(db.scalars(select(model)))
            assert rows and all(r.created_by == people["director"] for r in rows), model
        shot = db.scalar(select(models.Shot).where(models.Shot.code == "01.02"))
        assert shot.description == "Бежит по городу"
    after = counts(pid)
    assert after["import_run"] == 1 and after["activity"] == 1  # в журнале одна запись
    with database.session_factory()() as db:
        entry = db.scalar(
            select(models.Activity).where(models.Activity.action == "import_scenario")
        )
        assert entry.actor_id == people["director"] and entry.diff["schema_version"] == "1.0"
        assert entry.diff["run_id"] == data["run"]["id"] and entry.diff["excluded"] == []


def test_the_film_example_becomes_what_the_excel_tracker_gives(studio):
    client, _, pid = studio
    answer = client.post(f"{U}/apply", json={"texts": [prompt.example_text()]})
    assert answer.status_code == 201, answer.text
    created = answer.json()["created"]
    assert (created["scene"], created["shot"], created["asset"], created["setup_payoff"]) == (
        12,
        69,
        54,
        13,
    )
    assert counts(pid)["sound_cue"] > 12  # реплики и звуки шотов


def test_apply_checks_the_file_again_on_the_server(studio):
    """Клиент мог пропустить проверку или подделать её ответ: сервер верит только файлу."""
    client, _, pid = studio
    data = good()
    data["scenes"][0]["shots"][0]["asset_codes"].append("PR-77")
    answer = client.post(f"{U}/apply", json=payload(data))
    assert answer.status_code == 422 and "не прошёл проверку" in answer.json()["detail"]
    assert not any(counts(pid).values())


def test_a_failure_in_the_middle_leaves_nothing_behind(studio, monkeypatch):
    """Одна транзакция: упали на середине записи — не создано ничего, даже уже записанного."""
    from app.services import importing

    real = importing._upsert
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 6:
            raise RuntimeError("диск сломался")
        return real(*args, **kwargs)

    monkeypatch.setattr(importing, "_upsert", flaky)
    _, people, pid = studio
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        act_as(c, people["director"])
        answer = c.post(f"{U}/apply", json=payload())
    assert answer.status_code == 500 and calls["n"] >= 6
    assert not any(counts(pid).values())  # ни карточек, ни строки импорта, ни записи в журнале


def test_several_parts_become_one_project(studio):
    client, _, pid = studio
    from tests.test_scenario import part

    answer = client.post(
        f"{U}/apply",
        json={
            "texts": [json.dumps(part(2, 2, [3])), json.dumps(part(1, 2, [1, 2]))],
            "names": ["b.json", "a.json"],
        },
    )
    assert answer.status_code == 201, answer.text
    assert answer.json()["created"]["scene"] == 3 and answer.json()["run"]["parts"] == 2
    assert counts(pid)["import_run"] == 1


# --- только в пустой проект -----------------------------------------------------------------------------


def test_a_second_import_into_the_same_project_is_refused_and_changes_nothing(studio):
    client, _, pid = studio
    assert client.post(f"{U}/apply", json=payload()).status_code == 201
    before = counts(pid)
    again = client.post(f"{U}/apply", json=payload())
    assert again.status_code == 409 and "пустой проект" in again.json()["detail"]
    assert counts(pid) == before
    checked = client.post(f"{U}/check", json=payload()).json()
    assert (
        checked["ok"]
        and not checked["can_apply"]
        and not checked["empty"]
        and checked["not_empty_reason"]
    )


def test_a_card_left_in_the_trash_still_counts_as_content(studio):
    """Импортёр восстанавливает удалённое с тем же кодом и перезаписывает его: пустым такой проект не считаем."""
    client, _, pid = studio
    with scope.project_session(pid) as db:
        db.add(
            models.Task(code="T-01", block="editing", title="Старая", deleted_at=datetime.now(UTC))
        )
        db.commit()
    assert client.post(f"{U}/apply", json=payload()).status_code == 409


def test_the_film_project_with_its_data_cannot_be_overwritten(seeded_client):
    person_id = person("Босс", {}, tg_id=1001)
    act_as(seeded_client, person_id)
    before = seeded_client.get("/api/scenes").json()
    answer = seeded_client.post("/api/import/apply", json={"texts": [prompt.example_text()]})
    assert answer.status_code == 409
    assert seeded_client.get("/api/scenes").json() == before


# --- права ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["owner", "director", "boss"])
def test_owner_director_and_site_owner_can_import(studio, who):
    client, people, _ = studio
    act_as(client, people[who])
    assert client.get(f"{U}/prompt").status_code == 200
    assert client.get(f"{U}/example").status_code == 200
    assert client.post(f"{U}/check", json=payload()).status_code == 200
    assert client.get(f"{U}/runs").status_code == 200


@pytest.mark.parametrize("who", ["team", "guest"])
def test_team_and_guest_cannot_use_any_part_of_the_import(studio, who):
    client, people, pid = studio
    act_as(client, people["director"])
    run_id = client.post(f"{U}/apply", json=payload()).json()["run"]["id"]
    act_as(client, people[who])
    for method, url, body in (
        ("get", f"{U}/prompt", None),
        ("get", f"{U}/example", None),
        ("post", f"{U}/check", payload()),
        ("post", f"{U}/apply", payload()),
        ("get", f"{U}/runs", None),
        ("get", f"{U}/runs/{run_id}/source", None),
    ):
        answer = getattr(client, method)(url, **({"json": body} if body else {}))
        assert answer.status_code == 403, (url, answer.status_code)
    assert counts(pid)["import_run"] == 1


def test_a_stranger_does_not_even_learn_the_project_exists(studio):
    client, people, _ = studio
    act_as(client, people["stranger"])
    assert client.post(f"{U}/check", json=payload()).status_code == 404
    assert client.get(f"{U}/prompt").status_code == 404


def test_a_project_waiting_for_approval_can_still_be_filled_with_cards(studio):
    """Загрузка файлов закрыта до подтверждения, а карточки — нет: импорт на диск ничего не кладёт."""
    client, people, pid = studio
    with database.session_factory()() as db:
        db.get(models.Project, pid).approved_at = None
        db.commit()
    assert client.post(f"{U}/apply", json=payload()).status_code == 201


def test_an_archived_project_is_read_only_even_for_its_owner(studio):
    client, people, pid = studio
    with database.session_factory()() as db:
        db.get(models.Project, pid).archived_at = datetime.now(UTC)
        db.commit()
    act_as(client, people["owner"])
    assert client.post(f"{U}/apply", json=payload()).status_code == 403
    assert not any(counts(pid).values())


def test_requests_come_only_from_our_own_pages(studio):
    client, _, pid = studio
    bad = client.post(f"{U}/apply", json=payload(), headers={"Origin": "https://evil.example"})
    assert bad.status_code == 403 and not any(counts(pid).values())


# --- «не импортировать» -------------------------------------------------------------------------------------


def test_excluded_cards_are_not_created_and_nothing_points_at_them(studio):
    client, _, pid = studio
    answer = client.post(f"{U}/apply", json=payload(exclude=["CH-01", "LC-01"]))
    assert answer.status_code == 201, answer.text
    with scope.project_session(pid) as db:
        assert [a.code for a in db.scalars(select(models.Asset))] == ["PR-01"]
        assert (
            db.scalar(select(func.count()).select_from(models.ShotAsset)) == 1
        )  # труба в первом шоте
        scene = db.scalar(select(models.Scene))
        assert scene.location is None and scene.characters is None and scene.key_assets == "Труба"
        line = db.scalar(select(models.SoundCue).where(models.SoundCue.type == "dialogue"))
        assert (
            line.who == "Дозорный" and line.text_en == "Ma lord!"
        )  # реплика осталась, говорящий — по имени
        assert (
            db.scalar(select(models.AssetState).limit(1)) is None
        )  # состояния персонажа ушли вместе с ним
    with database.session_factory()() as db:
        entry = db.scalar(
            select(models.Activity).where(models.Activity.action == "import_scenario")
        )
        assert entry.diff["excluded"] == ["CH-01", "LC-01"]


def test_an_unknown_code_to_exclude_stops_the_import(studio):
    client, _, pid = studio
    answer = client.post(f"{U}/apply", json=payload(exclude=["CH-01", "XX-99"]))
    assert answer.status_code == 422 and "XX-99" in answer.json()["detail"]
    assert not any(counts(pid).values())


def test_excluding_leaves_the_original_document_alone_and_keeps_references_valid():
    doc = run(good()).doc
    original = doc.model_dump()
    reduced = convert.exclude_codes(doc, ["CH-01", "PR-01", "LC-01"])
    assert doc.model_dump() == original  # исходный файл не тронут
    assert not reduced.characters and not reduced.assets and not reduced.locations
    from app.scenario.check import check_references

    assert [i for i in check_references(reduced) if i.level == "error"] == []
    assert reduced.open_questions[0].related == []
    line = reduced.scenes[0].shots[1].dialogue[0]
    assert (line.character, line.speaker) == (None, "Дозорный")
    assert convert.exclude_codes(doc, []).model_dump() == original


# --- промпт, пример, история импортов -----------------------------------------------------------------------


def test_the_prompt_carries_the_project_title_and_chosen_parameters(studio):
    client, _, _ = studio
    answer = client.get(
        f"{U}/prompt",
        params={"target_min_sec": 120, "target_max_sec": 180, "max_shot_sec": 10, "language": "ru"},
    )
    assert answer.status_code == 200
    assert "import-prompt.md" in answer.headers["content-disposition"]
    body = answer.text
    for expected in (
        "Рабочее название: Новый фильм",
        "120–180 сек",
        "не длиннее 10 сек",
        "русский",
    ):
        assert expected in body, expected
    default = client.get(f"{U}/prompt").text  # цели берутся из проекта
    assert "300–420 сек" in default and "не длиннее 15 сек" in default
    assert client.get(f"{U}/prompt", params={"language": "klingon"}).status_code == 422


def test_a_title_that_looks_like_a_template_is_not_expanded(studio):
    client, _, pid = studio
    with database.session_factory()() as db:
        db.get(models.Project, pid).title = "{{json_schema}}"
        db.commit()
    body = client.get(f"{U}/prompt").text
    assert "Рабочее название: {{json_schema}}" in body and len(body) < 40_000


def test_the_example_file_passes_the_check_it_is_meant_to_illustrate(studio):
    client, _, _ = studio
    answer = client.get(f"{U}/example")
    assert "project-example.json" in answer.headers["content-disposition"]
    data = client.post(f"{U}/check", json={"texts": [answer.text]}).json()
    assert data["ok"] and data["errors"] == 0


def test_runs_keep_what_came_in_and_can_be_downloaded(studio):
    client, people, _ = studio
    text = json.dumps(good(), ensure_ascii=False)
    run_id = client.post(f"{U}/apply", json={"texts": [text], "names": ["project.json"]}).json()[
        "run"
    ]["id"]
    listed = client.get(f"{U}/runs").json()
    assert [r["id"] for r in listed] == [run_id] and listed[0]["created_by"]["id"] == people[
        "director"
    ]
    assert listed[0]["created"]["scene"] == 1 and "source" not in listed[0]
    source = client.get(f"{U}/runs/{run_id}/source")
    assert source.text == text and "import-" in source.headers["content-disposition"]
    assert client.get(f"{U}/runs/9999/source").status_code == 404


def test_runs_of_another_project_are_not_reachable(studio):
    client, people, _ = studio
    run_id = client.post(f"{U}/apply", json=payload()).json()["run"]["id"]
    with database.session_factory()() as db:
        other = models.Project(
            **{
                **projects.DEFAULT_PROJECT,
                "slug": "other",
                "title": "Другой",
                "approved_at": datetime.now(UTC),
            }
        )
        db.add(other)
        db.commit()
    elsewhere = person("Режиссёр другого", {"other": Role.DIRECTOR})
    act_as(client, elsewhere)
    assert client.get(f"/api/p/other/import/runs/{run_id}/source").status_code == 404
    assert client.get("/api/p/other/import/runs").json() == []
    assert client.get(f"{U}/runs").status_code == 404


def test_request_size_limits(studio):
    client, _, _ = studio
    assert client.post(f"{U}/check", json={"texts": []}).status_code == 422
    assert (
        client.post(
            f"{U}/check", json={"texts": ["{}"] * (scenario_import.MAX_TEXTS + 1)}
        ).status_code
        == 422
    )
    huge = "x" * (scenario_import.MAX_TEXT_CHARS + 1)
    assert client.post(f"{U}/check", json={"texts": [huge]}).status_code == 422


# --- чистые функции предпросмотра ---------------------------------------------------------------------------


def test_preview_counts_shots_per_card_and_names_the_speakers():
    doc = run(good()).doc
    shown = build(doc, Params(target_min_sec=5, target_max_sec=20))
    assert shown["in_target"] and shown["scenes"][0]["location"] == "Стена"
    by_code = {e["code"]: e for e in (*shown["characters"], *shown["locations"], *shown["assets"])}
    assert (by_code["CH-01"]["shots"], by_code["CH-01"]["scenes"], by_code["CH-01"]["states"]) == (
        2,
        1,
        ["дозор", "бег"],
    )
    assert (by_code["PR-01"]["shots"], by_code["LC-01"]["shots"], by_code["LC-01"]["scenes"]) == (
        1,
        1,
        1,
    )
    assert shown["scenes"][0]["shots"][1]["dialogue"] == [{"who": "Дозорный", "text": "Ma lord!"}]
    assert shown["open_questions"] == [{"question": "Кто такой Глашатай?", "related": ["Дозорный"]}]
    assert not build(doc, Params(target_min_sec=100, target_max_sec=200))["in_target"]


def test_the_schema_version_in_the_preview_is_the_one_we_check_against():
    assert build(run(good()).doc, Params())["schema_version"] == S.SCHEMA_VERSION


def test_the_service_enforces_its_own_size_limits_whatever_the_caller(studio):
    from app.services.core import ValidationError

    limits = scenario_import._limits
    with pytest.raises(ValidationError):
        limits([])
    with pytest.raises(ValidationError):
        limits(["{}"] * (scenario_import.MAX_TEXTS + 1))
    with pytest.raises(ValidationError):
        limits(["x" * (scenario_import.MAX_TEXT_CHARS + 1)])
    each = scenario_import.MAX_TOTAL_CHARS // 3 + 1  # каждый файл допустим, вместе — слишком много
    assert each <= scenario_import.MAX_TEXT_CHARS
    with pytest.raises(ValidationError):
        limits(["x" * each] * 3)
    limits(["{}"])  # обычный файл проходит


def test_dangling_references_left_after_exclusion_stop_the_import(studio, monkeypatch):
    """Если исключение когда-нибудь забудет почистить новое место со ссылками, проект не создастся с дырой."""
    client, _, pid = studio

    def careless(doc, codes):
        result = doc.model_copy(deep=True)
        result.assets = [
            a for a in result.assets if a.code not in set(codes)
        ]  # а ссылки в шотах остались
        return result

    monkeypatch.setattr(convert, "exclude_codes", careless)
    answer = client.post(f"{U}/apply", json=payload(exclude=["PR-01"]))
    assert answer.status_code == 422 and "битые ссылки" in answer.json()["detail"]
    assert not any(counts(pid).values())


@pytest.mark.parametrize(
    ("who", "expected"),
    [("owner", True), ("director", True), ("boss", True), ("team", False), ("guest", False)],
)
def test_the_page_learns_who_may_import_from_the_session(studio, who, expected):
    client, people, _ = studio
    act_as(client, people[who])
    assert client.get(f"/api/p/{SLUG}/me").json()["abilities"]["import_scenario"] is expected
