"""Превью ассета в списке: его собственный референс, а если нет — референс его состояния."""

import io

import pytest
from PIL import Image

from tests.conftest import login
from tests.test_files import upload, wait_for


def png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def api(seeded_client):
    login(seeded_client, "owner", "Артём")
    return seeded_client


def asset_with_states(api) -> dict:
    return next(a for a in api.get("/api/assets").json() if len(a["states"]) >= 2)


def add_reference(api, entity_type: str, entity_id: int, color) -> int:
    response = upload(
        api, png(color), f"ref-{color[0]}.png", entity_type=entity_type, entity_id=entity_id
    )
    assert response.status_code == 201, response.text
    file_id = response.json()["file"]["id"]
    wait_for(api, file_id, ready=lambda f: not f["processing"] and "thumb" in f["urls"])
    return file_id


def listed(api, asset_id: int) -> dict:
    return next(a for a in api.get("/api/assets").json() if a["id"] == asset_id)


def test_an_asset_without_files_has_no_preview(api):
    assert asset_with_states(api)["preview"] is None


def test_the_preview_comes_from_a_state_reference_when_the_asset_has_none(api):
    asset = asset_with_states(api)
    file_id = add_reference(api, "asset_state", asset["states"][0]["id"], (200, 80, 40))
    shown = listed(api, asset["id"])
    assert shown["preview"] is not None
    assert (
        shown["preview"]["file_id"] == file_id
        and f"/files/{file_id}/thumb" in shown["preview"]["url"]
    )


def test_the_first_state_with_a_picture_wins(api):
    asset = asset_with_states(api)
    second = add_reference(api, "asset_state", asset["states"][1]["id"], (10, 120, 200))
    assert (
        listed(api, asset["id"])["preview"]["file_id"] == second
    )  # у первого состояния картинок нет
    first = add_reference(api, "asset_state", asset["states"][0]["id"], (200, 80, 40))
    assert (
        listed(api, asset["id"])["preview"]["file_id"] == first
    )  # порядок состояний, а не загрузки


def test_the_asset_own_reference_beats_its_states(api):
    asset = asset_with_states(api)
    add_reference(api, "asset_state", asset["states"][0]["id"], (200, 80, 40))
    own = add_reference(api, "asset", asset["id"], (30, 160, 90))
    assert listed(api, asset["id"])["preview"]["file_id"] == own


def test_the_asset_card_has_the_same_preview(api):
    asset = asset_with_states(api)
    file_id = add_reference(api, "asset_state", asset["states"][0]["id"], (200, 80, 40))
    detail = api.get(f"/api/assets/{asset['id']}").json()
    assert detail["preview"]["file_id"] == file_id
