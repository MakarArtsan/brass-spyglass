"""Аниматик: раскладка шотов и звука на таймлайне, список «Смотреть фильм»."""

import pytest

from app import metrics
from app.metrics import CueIn, SceneIn, ShotLay
from tests.conftest import login
from tests.test_files import upload


def scenes(*rows):
    return [SceneIn(i, order, planned, status) for i, order, planned, status in rows]


def shots(*rows):
    return [ShotLay(i, scene, order, dur, status) for i, scene, order, dur, status in rows]


# --- чистая раскладка ----------------------------------------------------------------------------


def test_shots_follow_each_other_in_tracker_order_not_by_scene_number():
    layout = metrics.film_layout(
        scenes((1, 2, 10, "not_started"), (2, 1, 10, "not_started")),  # сцена 2 стоит первой
        shots((10, 1, 1, 4, "not_started"), (11, 1, 2, 6, "not_started"), (20, 2, 1, 3, "done")),
    )
    assert [s.scene_id for s in layout] == [2, 1]
    assert (layout[0].start_sec, layout[0].end_sec) == (0, 3)
    assert [(s.shot_id, s.start_sec, s.end_sec) for s in layout[1].shots] == [
        (10, 3, 7),
        (11, 7, 13),
    ]


def test_cut_scenes_and_shots_take_no_time():
    layout = metrics.film_layout(
        scenes((1, 1, 5, "not_started"), (2, 2, 5, "cut"), (3, 3, 5, "not_started")),
        shots((10, 1, 1, 4, "cut"), (11, 1, 2, 2, "done"), (30, 3, 1, 1, "done")),
    )
    assert [s.scene_id for s in layout] == [1, 3]
    assert (layout[0].end_sec, layout[1].start_sec, layout[1].end_sec) == (2, 2, 3)


def test_a_scene_without_shots_takes_its_planned_time():
    layout = metrics.film_layout(scenes((1, 1, 7, "not_started")), [])
    assert (layout[0].start_sec, layout[0].end_sec) == (0, 7)


def test_sound_is_anchored_to_its_shot_or_scene_plus_the_offset():
    layout = metrics.film_layout(
        scenes((1, 1, 5, "not_started"), (2, 2, 5, "not_started")),
        shots((10, 1, 1, 4, "x"), (20, 2, 1, 6, "x")),
    )
    assert metrics.cue_span(CueIn(1, 2, 20, 1.5, 3.0), layout) == (5.5, 8.5)  # шот 20 с 4-й секунды
    assert metrics.cue_span(CueIn(2, 2, None, 0, None), layout) == (
        4,
        6,
    )  # сцена, длина по умолчанию
    assert metrics.cue_span(CueIn(3, None, None, 2, 1.0), layout) == (2, 3)  # от начала фильма


def test_sound_of_a_cut_scene_is_not_on_the_timeline():
    layout = metrics.film_layout(scenes((1, 1, 5, "cut"), (2, 2, 5, "x")), [])
    assert metrics.cue_span(CueIn(1, 1, None, 0, None), layout) is None
    assert metrics.cue_span(CueIn(2, 2, None, 0, None), layout) == (0, 2)


def test_silence_has_no_lane():
    assert metrics.SOUND_LANES["silence"] is None
    assert metrics.SOUND_LANES["dialogue"] == 1 and metrics.SOUND_LANES["music"] == 3


# --- API -----------------------------------------------------------------------------------------


@pytest.fixture
def api(seeded_client):
    login(seeded_client, "owner", "Артём")
    return seeded_client


def video(n: int) -> bytes:
    return (b"animatic-video-%d-" % n) * 40


def test_the_timeline_from_the_tracker_matches_the_plan(api):
    data = api.get("/api/animatic").json()
    assert (
        len(data["scenes"]) == 12 and data["total_sec"] == 360
    )  # сумма шотов = плану, как в Excel
    first = data["scenes"][0]
    assert first["start_sec"] == 0
    ends = [s["end_sec"] for s in data["scenes"]]
    assert ends == sorted(ends)  # встык, по порядку
    shot_ends = [sh["end_sec"] for s in data["scenes"] for sh in s["shots"]]
    assert shot_ends == sorted(shot_ends) and shot_ends[-1] == 360


def test_without_files_every_shot_is_a_card_with_the_description(api):
    data = api.get("/api/animatic").json()
    assert data["ready_count"] == 0
    cards = [p for p in data["playlist"] if p["kind"] == "card"]
    assert len(cards) == 69 and all(p["file"] is None for p in data["playlist"])
    assert sum(p["duration_sec"] for p in cards) == pytest.approx(360)
    assert cards[0]["title"].startswith("Шот ") and cards[0]["description"]


def test_a_final_shot_file_plays_instead_of_its_card(api):
    shot = api.get("/api/shots").json()[0]
    file_id = upload(api, video(1), "take.mp4", entity_type="shot", entity_id=shot["id"]).json()[
        "file"
    ]["id"]
    api.put(f"/api/shots/{shot['id']}/final", json={"file_id": file_id})
    data = api.get("/api/animatic").json()
    first = data["playlist"][0]
    assert first["kind"] == "file" and first["shot_id"] == shot["id"]
    assert first["file"]["id"] == file_id and first["file"]["urls"]["play"]
    assert data["ready_count"] == 1 and len(data["playlist"]) == 69


def test_a_final_scene_file_replaces_the_cards_of_its_shots(api):
    scene = api.get("/api/scenes").json()[0]
    own = [s for s in api.get("/api/shots").json() if s["scene_id"] == scene["id"]]
    file_id = upload(api, video(2), "scene.mp4", entity_type="scene", entity_id=scene["id"]).json()[
        "file"
    ]["id"]
    api.put(f"/api/scenes/{scene['id']}/final", json={"file_id": file_id})
    data = api.get("/api/animatic").json()
    assert len(data["playlist"]) == 69 - len(own) + 1
    first = data["playlist"][0]
    assert first["kind"] == "file" and first["shot_id"] is None and first["scene_id"] == scene["id"]


def test_sound_lanes_follow_the_cue_type(api):
    cues = api.get("/api/animatic").json()["sound"]
    assert {c["lane"] for c in cues} <= {1, 2, 3}
    dialogue = [c for c in cues if c["type"] == "dialogue"]
    assert dialogue and all(c["lane"] == 1 for c in dialogue)


def test_a_guest_can_watch_the_animatic(api):
    login(api, "guest", "Гость")
    assert api.get("/api/animatic").status_code == 200
