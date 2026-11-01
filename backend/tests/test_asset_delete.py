"""Удаление ассета: он пропадает из списка и из шотов, права по матрице ролей."""

import pytest

from tests.conftest import login


@pytest.fixture
def api(seeded_client):
    login(seeded_client, "owner", "Артём")
    return seeded_client


def new_asset(api, code: str = "CH-99", name: str = "Ошибочный") -> dict:
    response = api.post("/api/assets", json={"code": code, "name": name, "type": "character"})
    assert response.status_code == 201, response.text
    return response.json()


def in_shot(api, asset_id: int) -> int:
    shot = api.get("/api/shots").json()[0]
    assert api.put(f"/api/shots/{shot['id']}/assets/{asset_id}", json={}).status_code in (
        200,
        201,
        204,
    )
    return shot["id"]


def test_a_deleted_asset_leaves_the_list_and_the_detail(api):
    asset = new_asset(api)
    assert api.delete(f"/api/assets/{asset['id']}").status_code == 204
    assert asset["id"] not in [a["id"] for a in api.get("/api/assets").json()]
    assert api.get(f"/api/assets/{asset['id']}").status_code == 404


def test_a_deleted_asset_is_no_longer_in_the_frame_of_its_shots(api):
    asset = new_asset(api)
    shot_id = in_shot(api, asset["id"])
    before = next(s for s in api.get("/api/shots").json() if s["id"] == shot_id)
    assert asset["id"] in [a["asset_id"] for a in before["assets"]]
    api.delete(f"/api/assets/{asset['id']}")
    after = next(s for s in api.get("/api/shots").json() if s["id"] == shot_id)
    assert asset["id"] not in [a["asset_id"] for a in after["assets"]]
    assert asset["id"] not in [
        a["asset_id"] for a in api.get(f"/api/shots/{shot_id}").json()["assets"]
    ]


def test_the_code_of_a_deleted_asset_can_be_used_again(api):
    asset = new_asset(api, "CH-98")
    api.delete(f"/api/assets/{asset['id']}")
    assert (
        api.post(
            "/api/assets", json={"code": "CH-98", "name": "Заново", "type": "character"}
        ).status_code
        == 201
    )


def test_the_deletion_is_in_the_journal(api):
    asset = new_asset(api, "CH-97")
    api.delete(f"/api/assets/{asset['id']}")
    items = api.get(
        "/api/activity", params={"entity_type": "asset", "entity_id": asset["id"]}
    ).json()["items"]
    assert "delete" in [i["action"] for i in items]


def test_a_team_member_deletes_only_their_own_asset(api):
    mine_owner = new_asset(api, "CH-96", "Чужой")
    login(api, "team", "Дина")
    own = new_asset(api, "CH-95", "Мой")
    assert api.delete(f"/api/assets/{mine_owner['id']}").status_code == 403
    assert api.delete(f"/api/assets/{own['id']}").status_code == 204


def test_a_director_deletes_any_asset_and_a_guest_none(api):
    asset = new_asset(api, "CH-94")
    login(api, "guest", "Гость")
    assert api.delete(f"/api/assets/{asset['id']}").status_code == 403
    login(api, "director", "Режиссёр")
    assert api.delete(f"/api/assets/{asset['id']}").status_code == 204


def test_deleting_an_asset_twice_is_not_found(api):
    asset = new_asset(api, "CH-93")
    assert api.delete(f"/api/assets/{asset['id']}").status_code == 204
    assert api.delete(f"/api/assets/{asset['id']}").status_code == 404


def test_a_deleted_asset_is_not_counted_on_the_dashboard(api):
    before = api.get("/api/dashboard").json()["readiness"]["assets"]
    asset = new_asset(api, "CH-92")
    assert api.get("/api/dashboard").json()["readiness"]["assets"]["total"] == before["total"] + 1
    api.delete(f"/api/assets/{asset['id']}")
    assert api.get("/api/dashboard").json()["readiness"]["assets"] == before
