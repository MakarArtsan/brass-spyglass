"""Дашборд на реальных данных Excel-трекера: числа сходятся с листом «Дашборд», живут обновлениями."""

import pytest

from tests.conftest import login


@pytest.fixture
def api(seeded_client):
    login(seeded_client, "owner", "Артём")
    return seeded_client


def _dash(client):
    response = client.get("/api/dashboard")
    assert response.status_code == 200, response.text
    return response.json()


def test_requires_login(seeded_client):
    assert seeded_client.get("/api/dashboard").status_code == 401


def test_numbers_match_the_excel_dashboard_sheet(api):
    d = _dash(api)
    # «Хронометраж по плану/по шотам»: 360 сек, зона 5:00–7:00
    assert d["readiness"]["plan_sec"] == 360 and d["readiness"]["shots_sec"] == 360
    assert d["runtime"] == {
        "shots_sec": 360,
        "plan_sec": 360,
        "min_sec": 300,
        "max_sec": 420,
        "in_zone": True,
    }
    # данных о готовности пока нет
    assert d["readiness"]["ready_sec"] == 0 and d["readiness"]["pct"] == 0
    assert d["readiness"]["shots"]["total"] == 69 and d["readiness"]["shots"]["done"] == 0
    assert d["readiness"]["assets"]["total"] == 54
    assert d["readiness"]["tasks"]["total"] == 29 and d["readiness"]["tasks"]["done"] >= 1  # T-01
    # Seedance считается по секундам, цель 70%
    assert d["seedance"]["target_pct"] == 70 and 0 < d["seedance"]["pct"] <= 100
    assert d["seedance"]["total_sec"] == 360
    # тревоги: у глашатая CH-06 нет шотов, финальных файлов сцен нет ни у одной
    assert "CH-06" in [a["code"] for a in d["alerts"]["orphan_assets"]]
    assert len(d["alerts"]["scenes_without_final"]) == 12
    assert all(s["duration_sec"] > 15 for s in d["alerts"]["long_shots"])
    # полоса фильма и барабан — 12 сцен в порядке трекера
    assert [s["number"] for s in d["film_strip"]] == sorted(s["number"] for s in d["film_strip"])
    assert len(d["film_strip"]) == len(d["drum"]) == 12
    assert sum(s["planned_sec"] for s in d["film_strip"]) == 360


def test_status_change_moves_readiness_burndown_contribution_and_feed(api):
    shots = api.get("/api/shots").json()
    shot = shots[0]
    before = _dash(api)

    assert api.patch(f"/api/shots/{shot['id']}", json={"status": "done"}).status_code == 200
    d = _dash(api)

    assert d["readiness"]["ready_sec"] == shot["duration_sec"]
    assert d["readiness"]["shots"]["done"] == 1
    assert (
        d["burndown"]["remaining_sec"] == before["burndown"]["remaining_sec"] - shot["duration_sec"]
    )
    mine = [c for c in d["contribution"] if c["closed"] == 1]
    assert len(mine) == 1 and str(mine[0]["user_id"]) in d["people"]
    today = d["activity"]["bars"][-1]
    assert today["statuses"] >= 1 and sum(today["by_user"].values()) >= 1
    assert d["activity"]["heatmap"][-1]["n"] >= 1
    top = d["feed"][0]
    assert (top["entity_type"], top["action"], top["status"]) == (
        "shot",
        "status",
        ["not_started", "done"],
    )
    assert top["actor"]["name"] == "Артём" and top["label"] == f"шот {shot['code']}"


def test_burndown_history_follows_the_log_back_from_the_current_state(api):
    shot = api.get("/api/shots").json()[0]
    api.patch(f"/api/shots/{shot['id']}", json={"status": "done"})
    api.delete(f"/api/shots/{shot['id']}")  # ушёл в корзину: готового больше нет
    d = _dash(api)
    assert d["readiness"]["ready_sec"] == 0
    assert d["burndown"]["remaining_sec"] == d["readiness"]["shots_sec"]
    assert d["readiness"]["shots_sec"] == 360 - shot["duration_sec"]


def test_my_tasks_are_only_mine_sorted_by_deadline_and_skip_done(api):
    me = api.get("/api/me").json()["user"]["id"]
    tasks = api.get("/api/tasks").json()
    open_tasks = [t for t in tasks if t["status"] not in ("done", "cut")]
    for task, due in zip(open_tasks[:3], ("2026-11-09", "2026-11-03", None), strict=True):
        assert (
            api.patch(
                f"/api/tasks/{task['id']}", json={"assignee_id": me, "due_date": due}
            ).status_code
            == 200
        )
    done = next(t for t in tasks if t["status"] == "done")
    api.patch(f"/api/tasks/{done['id']}", json={"assignee_id": me})

    mine = _dash(api)["my_tasks"]
    assert [t["due_date"] for t in mine] == ["2026-11-03", "2026-11-09", None]
    assert done["code"] not in [t["code"] for t in mine]


def test_overdue_counts_by_entity_type(api):
    task = next(t for t in api.get("/api/tasks").json() if t["status"] == "not_started")
    api.patch(f"/api/tasks/{task['id']}", json={"due_date": "2020-01-01"})
    overdue = _dash(api)["alerts"]["overdue"]
    assert overdue["total"] >= 1 and overdue["by_type"]["task"] >= 1


def test_guest_gets_numbers_but_no_feed(seeded_client):
    login(seeded_client, "owner", "Артём")
    seeded_client.patch("/api/shots/1", json={"status": "review"})
    login(seeded_client, "guest", "Гость")
    d = _dash(seeded_client)
    assert d["feed"] == []
    assert d["readiness"]["shots"]["total"] == 69


def test_media_widget_counts_files_by_kind_and_reports_disk_usage(api):
    from io import BytesIO

    from PIL import Image

    from tests.test_files import upload

    buffer = BytesIO()
    Image.new("RGB", (64, 48), (200, 150, 40)).save(buffer, format="PNG")
    shot = api.get("/api/shots").json()[0]
    assert (
        upload(
            api, buffer.getvalue(), "a.png", entity_type="shot", entity_id=shot["id"]
        ).status_code
        == 201
    )

    media = _dash(api)["media"]
    assert media["total"] == 1 and media["by_kind"]["image"] == 1 and media["from_telegram"] == 0
    storage = media["storage"]
    assert storage["limit_bytes"] == 5 * 1024**3 and storage["used_bytes"] > 0
    assert storage["warn"] is False and storage["full"] is False
