"""metrics.py: таймкоды и суммы считаются запросами, а не хранятся."""

import pytest
from sqlalchemy import select

from app import metrics, models
from app.constants import Role, Status
from app.metrics import SceneIn, ShotIn
from app.services import core, projects
from app.services.importing import apply_bundle
from app.xlsx_reader import read_workbook
from tests.factories import actor, make_user
from tests.test_import import SEED


def test_timeline_is_cumulative_by_order_not_by_number():
    scenes = [
        SceneIn(id=7, order=2, planned_sec=30, status="not_started"),
        SceneIn(id=3, order=1, planned_sec=25, status="done"),
    ]
    assert metrics.timeline(scenes) == {3: (0, 25), 7: (25, 55)}  # порядок решает, id/номер — нет


def test_cut_scene_takes_no_time():
    scenes = [
        SceneIn(1, 1, 25, "not_started"),
        SceneIn(2, 2, 30, Status.CUT.value),
        SceneIn(3, 3, 20, "not_started"),
    ]
    assert metrics.timeline(scenes) == {1: (0, 25), 2: (None, None), 3: (25, 45)}
    assert metrics.plan_total_sec(scenes) == 45


def test_scene_stats_ignore_cut_shots_and_compute_readiness():
    scenes = [SceneIn(1, 1, 10, "not_started")]
    shots = [
        ShotIn(1, 4, "done"),
        ShotIn(1, 4, "not_started"),
        ShotIn(1, 5, Status.CUT.value),
    ]
    stat = metrics.scene_stats(scenes, shots)[1]
    assert (stat.shots_count, stat.shots_sec, stat.delta_sec, stat.done_shots, stat.ready_pct) == (
        2,
        8,
        -2,
        1,
        50.0,
    )
    assert metrics.shots_total_sec(shots) == 8


def test_scene_without_shots_is_zero_percent_not_a_division_error():
    assert metrics.scene_stats([SceneIn(1, 1, 10, "x")], [])[1].ready_pct == 0.0


@pytest.mark.parametrize(
    ("sec", "expected"), [(0, "0:00"), (73, "1:13"), (360, "6:00"), (None, "—")]
)
def test_timecode_format(sec, expected):
    assert metrics.format_timecode(sec) == expected


def test_real_data_timecodes_and_reordering(db):
    project_id = projects.get_project(db).id
    apply_bundle(db, project_id, read_workbook(SEED))
    stats = metrics.project_scene_stats(db, project_id)
    scenes = {s.number: s for s in db.scalars(select(models.Scene))}
    assert (stats[scenes[1].id].start_sec, stats[scenes[1].id].end_sec) == (0, 25)
    assert (stats[scenes[2].id].start_sec, stats[scenes[2].id].end_sec) == (25, 55)
    assert stats[scenes[12].id].end_sec == 360  # хронометраж 6:00
    assert all(s.delta_sec == 0 for s in stats.values())

    # Меняем порядок перетаскиванием: сцена 1 уходит в конец — таймкоды пересчитываются сами.
    owner = make_user(db, Role.OWNER)
    core.update(db, actor(owner), "scene", scenes[1].id, {"order": 100})
    stats = metrics.project_scene_stats(db, project_id)
    assert stats[scenes[2].id].start_sec == 0
    assert (stats[scenes[1].id].start_sec, stats[scenes[1].id].end_sec) == (335, 360)
