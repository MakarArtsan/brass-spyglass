"""API сущностей на реальных данных Excel-трекера: списки, правки, права, порядок, журнал."""

import time

import pytest

from tests.conftest import login


@pytest.fixture
def api(seeded_client):
    login(seeded_client, "owner", "Артём")
    return seeded_client


def _by(items, key, value):
    return next(i for i in items if i[key] == value)


# --- чтение ------------------------------------------------------------------------------------------


def test_everything_requires_login(seeded_client):
    for path in (
        "/scenes",
        "/shots",
        "/assets",
        "/setups",
        "/sound",
        "/tasks",
        "/meta",
        "/activity",
    ):
        assert seeded_client.get(f"/api{path}").status_code == 401, path


def test_lists_match_the_excel_counts(api):
    counts = {
        p: len(api.get(f"/api/{p}").json())
        for p in ("scenes", "shots", "assets", "setups", "sound", "tasks")
    }
    assert counts == {
        "scenes": 12,
        "shots": 69,
        "assets": 54,
        "setups": 13,
        "sound": 23,
        "tasks": 29,
    }


def test_scenes_carry_computed_timecodes_and_totals(api):
    scenes = api.get("/api/scenes").json()
    assert [s["number"] for s in scenes] == list(range(1, 13))
    first, last = scenes[0], scenes[-1]
    assert (first["start_sec"], first["end_sec"], first["shots_count"], first["shots_sec"]) == (
        0,
        25,
        6,
        25,
    )
    assert last["end_sec"] == 360
    assert sum(s["planned_sec"] for s in scenes) == 360
    assert all(s["delta_sec"] == 0 for s in scenes)


def test_shot_list_is_fast_and_in_scene_order(api):
    started = time.perf_counter()
    shots = api.get("/api/shots").json()
    elapsed = time.perf_counter() - started
    assert elapsed < 0.5, f"шот-лист из 69 строк отдаётся {elapsed:.2f} с"
    assert [s["code"] for s in shots[:3]] == ["01.01", "01.02", "01.03"]
    assert len(api.get("/api/shots", params={"scene_id": shots[0]["scene_id"]}).json()) == 6


def test_shot_carries_assets_and_detail_adds_sound_and_setups(api):
    shots = api.get("/api/shots").json()
    shot = _by(shots, "code", "04.03")
    assert {a["code"] for a in shot["assets"]} >= {"AN-01"} or shot["assets"]
    detail = api.get(f"/api/shots/{shot['id']}").json()
    assert detail["scene"]["number"] == 4
    assert [s["code"] for s in detail["sound"]] == ["SND-05"]
    assert [(s["number"], s["role"]) for s in detail["setups"]] == [(4, "setup")]


def test_asset_has_states_and_shot_counts(api):
    sheep = _by(api.get("/api/assets").json(), "code", "AN-01")
    assert [s["name"] for s in sheep["states"]][:2] == ["белая", "в саже и краске"] and len(
        sheep["states"]
    ) == 4
    assert _by(api.get("/api/assets").json(), "code", "CH-06")["shots_count"] == 0
    detail = api.get(f"/api/assets/{sheep['id']}").json()
    assert len(detail["shots"]) == sheep["shots_count"] > 0


def test_setups_resolve_shot_codes(api):
    setup = _by(api.get("/api/setups").json(), "number", 6)
    assert [s["code"] for s in setup["setup_shots"]] == [f"07.0{i}" for i in range(1, 7)]
    assert [s["code"] for s in setup["payoff_shots"]] == ["11.06"]


def test_meta_lists_reference_values(api):
    meta = api.get("/api/meta").json()
    assert meta["status"] == ["not_started", "in_progress", "review", "rework", "done", "cut"]
    assert (
        "pov_spyglass" in meta["size"]
        and "blender_3d" in meta["tool"]
        and "take_selection" in meta["stage"]
    )


# --- правки и валидация ------------------------------------------------------------------------------


def test_status_change_is_one_request_and_logged(api):
    shot = api.get("/api/shots").json()[0]
    changed = api.patch(f"/api/shots/{shot['id']}", json={"status": "in_progress"})
    assert changed.status_code == 200 and changed.json()["status"] == "in_progress"
    journal = api.get(
        "/api/activity", params={"entity_type": "shot", "entity_id": shot["id"]}
    ).json()
    top = journal["items"][0]
    assert (top["action"], top["label"], top["actor"]["name"]) == ("status", "шот 01.01", "Артём")
    assert top["diff"] == {"status": ["not_started", "in_progress"]}


@pytest.mark.parametrize(
    "body",
    [
        {"status": "почти_готово"},
        {"size": "huge"},
        {"created_by": 1},  # автора ставит сервер
        {"duration_sec": -1},
        {"unknown": 1},
    ],
)
def test_invalid_input_is_rejected_with_422(api, body):
    shot = api.get("/api/shots").json()[0]
    assert api.patch(f"/api/shots/{shot['id']}", json=body).status_code == 422


def test_scene_drum_level_is_limited_to_0_5(api):
    scene = api.get("/api/scenes").json()[0]
    assert api.patch(f"/api/scenes/{scene['id']}", json={"drum_level": 9}).status_code == 422
    assert api.patch(f"/api/scenes/{scene['id']}", json={"drum_level": 3}).json()["drum_level"] == 3


def test_create_assigns_author_order_and_rejects_duplicate_codes(api):
    scene = api.get("/api/scenes").json()[0]
    made = api.post(
        "/api/shots", json={"scene_id": scene["id"], "code": "01.07", "duration_sec": 2}
    ).json()
    assert made["order"] == 7 and made["created_by"] is not None
    dup = api.post("/api/shots", json={"scene_id": scene["id"], "code": "01.07"})
    assert dup.status_code == 409 and "код" in dup.json()["detail"]
    assert api.post("/api/shots", json={"code": "01.99"}).status_code == 422  # нет сцены
    new_scene = api.post("/api/scenes", json={"number": 13, "title": "Эпилог"}).json()
    assert new_scene["order"] == 13


def test_delete_goes_to_trash_and_disappears_from_lists(api):
    shot = api.get("/api/shots").json()[5]
    assert api.delete(f"/api/shots/{shot['id']}").status_code == 204
    assert len(api.get("/api/shots").json()) == 68
    assert api.get(f"/api/shots/{shot['id']}").status_code == 404


# --- права «Команды» и гостя ---------------------------------------------------------------------------


def test_team_changes_status_of_any_card_but_not_its_content(seeded_client):
    login(seeded_client, "owner", "Артём")
    shot = seeded_client.get("/api/shots").json()[0]
    login(seeded_client, "team", "Петя")
    assert (
        seeded_client.patch(f"/api/shots/{shot['id']}", json={"status": "review"}).status_code
        == 200
    )
    assert (
        seeded_client.patch(f"/api/shots/{shot['id']}", json={"description": "моё"}).status_code
        == 403
    )
    assert seeded_client.delete(f"/api/shots/{shot['id']}").status_code == 403
    mine = seeded_client.post("/api/tasks", json={"code": "T-90", "title": "Своя задача"}).json()
    assert (
        seeded_client.patch(f"/api/tasks/{mine['id']}", json={"title": "Правка своей"}).status_code
        == 200
    )
    assert seeded_client.delete(f"/api/tasks/{mine['id']}").status_code == 204


def test_guest_reads_everything_except_journal_and_changes_nothing(seeded_client):
    login(seeded_client, "owner", "Артём")
    shot = seeded_client.get("/api/shots").json()[0]
    login(seeded_client, "guest", "Гость")
    assert seeded_client.get("/api/shots").status_code == 200
    assert seeded_client.get("/api/activity").status_code == 403
    assert (
        seeded_client.patch(f"/api/shots/{shot['id']}", json={"status": "done"}).status_code == 403
    )
    assert seeded_client.post("/api/tasks", json={"code": "T-91", "title": "x"}).status_code == 403
    assert (
        seeded_client.post(
            "/api/bulk-status", json={"entity_type": "shot", "ids": [shot["id"]], "status": "done"}
        ).status_code
        == 403
    )


def test_foreign_origin_cannot_write(api):
    shot = api.get("/api/shots").json()[0]
    bad = api.patch(
        f"/api/shots/{shot['id']}",
        json={"status": "done"},
        headers={"Origin": "https://evil.example"},
    )
    assert bad.status_code == 403


def test_only_owner_changes_roles(seeded_client):
    petya = login(seeded_client, "team", "Петя")
    login(seeded_client, "director", "Дина")
    assert (
        seeded_client.patch(f"/api/users/{petya.id}", json={"role": "director"}).status_code == 403
    )
    login(seeded_client, "owner", "Артём")
    changed = seeded_client.patch(f"/api/users/{petya.id}", json={"role": "director"})
    assert changed.status_code == 200 and changed.json()["role"] == "director"


# --- групповые операции и порядок ----------------------------------------------------------------------


def test_bulk_status_changes_selected_shots_and_logs_each(api):
    shots = api.get("/api/shots").json()[:4]
    ids = [s["id"] for s in shots]
    done = api.post("/api/bulk-status", json={"entity_type": "shot", "ids": ids, "status": "done"})
    assert done.json() == {"updated": 4}
    assert [s["status"] for s in api.get("/api/shots").json()[:5]] == ["done"] * 4 + ["not_started"]
    scene = api.get("/api/scenes").json()[0]
    assert (scene["done_shots"], scene["ready_pct"]) == (4, round(100 * 4 / 6, 1))
    assert (
        api.post(
            "/api/bulk-status", json={"entity_type": "shot", "ids": [], "status": "done"}
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/api/bulk-status", json={"entity_type": "shot", "ids": ids, "status": "nope"}
        ).status_code
        == 422
    )


def test_reordering_scenes_moves_the_timecodes(api):
    scenes = api.get("/api/scenes").json()
    ids = [s["id"] for s in scenes]
    moved = api.post("/api/reorder", json={"entity_type": "scene", "ids": ids[1:] + ids[:1]})
    assert moved.json()["moved"] == 12
    after = api.get("/api/scenes").json()
    assert after[0]["number"] == 2 and after[0]["start_sec"] == 0
    assert (after[-1]["number"], after[-1]["start_sec"], after[-1]["end_sec"]) == (1, 335, 360)
    journal = api.get("/api/activity", params={"entity_type": "scene"}).json()["items"]
    assert journal[0]["action"] == "reorder"


def test_reordering_shots_stays_inside_the_scene(api):
    scene = api.get("/api/scenes").json()[0]
    shots = api.get("/api/shots", params={"scene_id": scene["id"]}).json()
    ids = [s["id"] for s in shots]
    assert (
        api.post(
            "/api/reorder", json={"entity_type": "shot", "scene_id": scene["id"], "ids": ids[::-1]}
        ).json()["moved"]
        == 6
    )
    assert [s["code"] for s in api.get("/api/shots", params={"scene_id": scene["id"]}).json()] == [
        "01.06", "01.05", "01.04", "01.03", "01.02", "01.01",
    ]  # fmt: skip
    assert (
        api.post("/api/reorder", json={"entity_type": "shot", "ids": ids}).status_code == 422
    )  # нужна сцена
    assert (
        api.post(
            "/api/reorder", json={"entity_type": "shot", "scene_id": scene["id"], "ids": ids[:-1]}
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/api/reorder",
            json={"entity_type": "shot", "scene_id": scene["id"], "ids": ids[:-1] + [999999]},
        ).status_code
        == 404
    )


def test_team_cannot_reorder_foreign_cards(seeded_client):
    login(seeded_client, "owner", "Артём")
    ids = [s["id"] for s in seeded_client.get("/api/scenes").json()]
    login(seeded_client, "team", "Петя")
    assert (
        seeded_client.post(
            "/api/reorder", json={"entity_type": "scene", "ids": ids[::-1]}
        ).status_code
        == 403
    )
    assert [s["number"] for s in seeded_client.get("/api/scenes").json()][:2] == [
        1,
        2,
    ]  # ничего не сдвинулось


# --- континьюити ассетов ---------------------------------------------------------------------------------


def test_asset_state_in_a_shot(api):
    shots = api.get("/api/shots").json()
    shot = _by(shots, "code", "01.01")
    sheep = _by(api.get("/api/assets").json(), "code", "AN-01")
    state = sheep["states"][1]
    other = _by(api.get("/api/assets").json(), "code", "CH-01")["states"][0]

    linked = api.put(
        f"/api/shots/{shot['id']}/assets/{sheep['id']}", json={"asset_state_id": state["id"]}
    )
    assert linked.status_code == 200
    entry = _by(linked.json()["assets"], "code", "AN-01")
    assert entry["state_name"] == "в саже и краске"
    wrong = api.put(
        f"/api/shots/{shot['id']}/assets/{sheep['id']}", json={"asset_state_id": other["id"]}
    )
    assert wrong.status_code == 422  # состояние чужого ассета
    assert api.delete(f"/api/shots/{shot['id']}/assets/{sheep['id']}").status_code == 204
    assert api.delete(f"/api/shots/{shot['id']}/assets/{sheep['id']}").status_code == 404
    assert "AN-01" not in [a["code"] for a in api.get(f"/api/shots/{shot['id']}").json()["assets"]]


def test_new_state_is_appended_and_listed(api):
    asset = _by(api.get("/api/assets").json(), "code", "CH-05")
    assert asset["states"] == []
    made = api.post(f"/api/assets/{asset['id']}/states", json={"name": "в краске"}).json()
    assert [s["name"] for s in made["states"]] == ["в краске"]
    state_id = made["states"][0]["id"]
    assert (
        api.patch(f"/api/asset-states/{state_id}", json={"name": "в оранжевой краске"}).json()[
            "states"
        ][0]["name"]
        == "в оранжевой краске"
    )
    assert api.delete(f"/api/asset-states/{state_id}").status_code == 204


# --- комментарии и журнал ----------------------------------------------------------------------------------


def test_comments_thread_with_authors_and_permissions(seeded_client):
    login(seeded_client, "owner", "Артём")
    shot = seeded_client.get("/api/shots").json()[0]
    ref = {"entity_type": "shot", "entity_id": shot["id"]}
    first = seeded_client.post("/api/comments", json={**ref, "body": "Нужен ракурс ниже"})
    assert first.status_code == 201 and first.json()["author"]["name"] == "Артём"

    login(seeded_client, "guest", "Гость")  # гость может только комментировать
    reply = seeded_client.post("/api/comments", json={**ref, "body": "Согласен"})
    assert reply.status_code == 201
    thread = seeded_client.get("/api/comments", params=ref).json()
    assert [(c["body"], c["author"]["name"]) for c in thread] == [
        ("Нужен ракурс ниже", "Артём"),
        ("Согласен", "Гость"),
    ]
    assert seeded_client.delete(f"/api/comments/{thread[0]['id']}").status_code == 403
    assert (
        seeded_client.post(
            "/api/comments", json={"entity_type": "shot", "entity_id": 999999, "body": "x"}
        ).status_code
        == 404
    )
    assert (
        seeded_client.post("/api/comments", json={**ref, "body": "x", "author": 1}).status_code
        == 422
    )

    login(seeded_client, "owner", "Артём")
    assert seeded_client.delete(f"/api/comments/{thread[1]['id']}").status_code == 204
    assert len(seeded_client.get("/api/comments", params=ref).json()) == 1


def test_journal_paginates_and_filters(api):
    shots = api.get("/api/shots").json()
    for shot in shots[:5]:
        api.patch(f"/api/shots/{shot['id']}", json={"status": "in_progress"})
    page = api.get("/api/activity", params={"limit": 3}).json()
    assert len(page["items"]) == 3 and page["next_before_id"] is not None
    older = api.get(
        "/api/activity", params={"limit": 3, "before_id": page["next_before_id"] + 1}
    ).json()
    assert older["items"][0]["id"] < page["items"][0]["id"] + 1
    mine = api.get("/api/activity", params={"actor_id": page["items"][0]["actor"]["id"]}).json()[
        "items"
    ]
    assert mine and all(i["actor"]["name"] == "Артём" for i in mine)
    imports = [
        i
        for i in api.get("/api/activity", params={"limit": 200}).json()["items"]
        if i["action"] == "import"
    ]
    assert imports and imports[0]["actor"] is None  # импорт — действие системы
