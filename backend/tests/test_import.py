"""Импорт Excel-трекера: проверки из ТЗ, идемпотентность, правки команды не затираются."""

from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import metrics, models
from app.constants import Role, Status
from app.services import core, projects, seed
from app.services.importing import apply_bundle
from app.xlsx_reader import (
    WorkbookError,
    expand_shot_refs,
    read_workbook,
    split_asset_codes,
    split_states,
    text,
)
from tests.factories import actor, make_user

SEED = Path(__file__).resolve().parent.parent / "seed" / "Krivoe_zerkalo_tracker.xlsx"


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def _project_id(db: Session) -> int:
    return projects.get_project(db).id


@pytest.fixture
def imported(db):
    report = apply_bundle(db, _project_id(db), read_workbook(SEED))
    db.flush()
    return report


# --- разбор ячеек ---------------------------------------------------------------------------


def test_states_split_by_numbers_and_by_slash():
    assert split_states(
        "1) белая 2) в саже и краске 3) в оранжево-чёрных полосах 4) мокрая, краска смыта"
    ) == [
        "белая",
        "в саже и краске",
        "в оранжево-чёрных полосах",
        "мокрая, краска смыта",
    ]
    assert split_states("Дозор / таверна (сытый) / финал за столом") == [
        "Дозор",
        "таверна (сытый)",
        "финал за столом",
    ]
    assert split_states("Едва заметен в 1 / явный в трубе в 12") == [
        "Едва заметен в 1",
        "явный в трубе в 12",
    ]
    assert split_states("Сумерки") == ["Сумерки"]


@pytest.mark.parametrize("empty", [None, "", "—", "  ", "-"])
def test_empty_marks_mean_no_value(empty):
    assert split_states(empty) == []
    assert text(empty) is None


def test_asset_codes_split_and_dedupe():
    assert split_asset_codes("LC-01, LC-02,LC-03 ; LC-01") == ["LC-01", "LC-02", "LC-03"]


def test_shot_ranges_expand_within_and_across_scenes():
    order = ["01.01", "01.02", "02.01", "02.02", "02.03", "03.01"]
    warnings: list[str] = []
    assert expand_shot_refs("01.02, 02.01–02.03", order, warnings, "t") == [
        "01.02",
        "02.01",
        "02.02",
        "02.03",
    ]
    assert expand_shot_refs("01.02–03.01", order, warnings, "t") == order[1:]  # через границы сцен
    assert warnings == []
    assert expand_shot_refs("9.9, 02.03–02.01, abc", order, warnings, "t") == []
    assert len(warnings) == 3  # неизвестный шот, перевёрнутый диапазон, мусор


# --- реальный файл --------------------------------------------------------------------------


def test_reader_finds_everything_the_spec_promises():
    bundle = read_workbook(SEED)
    assert (len(bundle.scenes), len(bundle.shots), len(bundle.assets)) == (12, 69, 54)
    assert (len(bundle.setups), len(bundle.sounds), len(bundle.tasks)) == (13, 23, 29)
    assert bundle.warnings == []


def test_import_counts_and_checks_from_the_spec(db, imported):
    created = imported.created
    assert (created["scene"], created["shot"], created["asset"]) == (12, 69, 54)
    assert (created["setup_payoff"], created["sound_cue"], created["task"]) == (13, 23, 29)
    assert created["shot_asset"] == 182
    assert imported.warnings == []

    project_id = _project_id(db)
    checks = {c.name: c for c in metrics.consistency_checks(db, project_id)}
    assert checks["Сумма плана сцен, сек"].detail == "360"  # сумма плана 360 сек
    assert checks["Сумма шотов, сек"].ok and checks["Сумма шотов, сек"].detail.startswith("360")
    assert checks["Ассеты без шотов"].detail == "CH-06"  # у глашатая 0 шотов
    glashatay = db.scalar(select(models.Asset).where(models.Asset.code == "CH-06"))
    links = db.scalar(
        select(func.count())
        .select_from(models.ShotAsset)
        .where(models.ShotAsset.asset_id == glashatay.id)
    )
    assert links == 0


def test_import_maps_values_and_references(db, imported):
    scene = db.scalar(select(models.Scene).where(models.Scene.number == 4))
    assert (scene.title, scene.drum_level, scene.planned_sec, scene.status, scene.priority) == (
        "Тигр",
        1,
        30,
        "not_started",
        "high",
    )
    assert scene.characters and scene.key_assets and scene.lines_en and scene.cut_notes

    shot = db.scalar(select(models.Shot).where(models.Shot.code == "01.04"))
    assert (shot.size, shot.tool, shot.stage, shot.duration_sec) == (
        "pov_spyglass",
        "seedance",
        "storyboard",
        4,
    )
    assert shot.order == 4 and shot.scene_id == scene.id - 3  # четвёртый шот первой сцены

    sheep = db.scalar(select(models.Asset).where(models.Asset.code == "AN-01"))
    states = db.scalars(
        select(models.AssetState.name)
        .where(models.AssetState.asset_id == sheep.id)
        .order_by(models.AssetState.order)
    ).all()
    assert sheep.type == "animal" and len(states) == 4 and states[0] == "белая"

    setup = db.scalar(select(models.SetupPayoff).where(models.SetupPayoff.number == 10))
    codes = [db.get(models.Shot, i).code for i in setup.payoff_shot_ids]
    assert codes == ["10.01", "10.02", "10.03", "10.04", "10.05", "10.06", "11.01", "11.02"]

    task = db.scalar(select(models.Task).where(models.Task.code == "T-01"))
    assert (task.block, task.status, task.due_date.isoformat()) == ("contest", "done", "2026-10-29")

    cue = db.scalar(select(models.SoundCue).where(models.SoundCue.code == "SND-05"))
    assert (
        cue.type == "dialogue"
        and cue.text_en.startswith("Ma lord")
        and db.get(models.Shot, cue.shot_id).code == "04.03"
    )


def test_import_logs_one_activity_row_with_summary(db, imported):
    rows = db.scalars(select(models.Activity).where(models.Activity.action == "import")).all()
    assert len(rows) == 1 and rows[0].diff["created"]["shot"] == 69


# --- идемпотентность и правки команды ---------------------------------------------------------


def test_second_import_creates_nothing_and_changes_nothing(db, imported):
    before = {
        m: _count(db, m)
        for m in (models.Scene, models.Shot, models.Asset, models.AssetState, models.ShotAsset)
    }
    again = apply_bundle(db, _project_id(db), read_workbook(SEED))
    assert not again.created and not again.updated and not again.restored
    assert before == {m: _count(db, m) for m in before}


def test_reimport_keeps_what_the_team_changed_on_the_site(db, imported):
    owner = make_user(db, Role.OWNER)
    shot = db.scalar(select(models.Shot).where(models.Shot.code == "01.03"))
    core.update(
        db,
        actor(owner),
        "shot",
        shot.id,
        {"status": Status.REVIEW.value, "description": "Моя правка"},
    )
    scene2 = db.scalar(select(models.Scene).where(models.Scene.number == 2))
    core.update(db, actor(owner), "scene", scene2.id, {"order": 99})

    again = apply_bundle(db, _project_id(db), read_workbook(SEED))
    db.refresh(shot)
    db.refresh(scene2)
    assert shot.status == "review"  # рабочее поле команды не затёрто
    assert scene2.order == 99  # порядок тоже
    assert shot.description != "Моя правка"  # содержимое карточки обновляется из Excel
    assert again.updated["shot"] == 1


def test_overwrite_flag_resets_work_fields(db, imported):
    owner = make_user(db, Role.OWNER)
    shot = db.scalar(select(models.Shot).where(models.Shot.code == "01.03"))
    core.update(db, actor(owner), "shot", shot.id, {"status": Status.DONE.value})
    apply_bundle(db, _project_id(db), read_workbook(SEED), overwrite_work_fields=True)
    db.refresh(shot)
    assert shot.status == "not_started"


def test_reimport_restores_a_shot_from_the_trash_instead_of_duplicating(db, imported):
    owner = make_user(db, Role.OWNER)
    shot = db.scalar(select(models.Shot).where(models.Shot.code == "02.02"))
    core.delete(db, actor(owner), "shot", shot.id)
    again = apply_bundle(db, _project_id(db), read_workbook(SEED))
    db.refresh(shot)
    assert shot.deleted_at is None and again.restored["shot"] == 1
    assert _count(db, models.Shot) == 69


# --- стартовые данные -----------------------------------------------------------------------------


def test_seed_runs_only_on_an_empty_project(db):
    project_id = _project_id(db)
    assert seed.seed_if_empty(db, project_id, None) is None
    assert seed.seed_if_empty(db, project_id, Path("/нет/такого.xlsx")) is None
    first = seed.seed_if_empty(db, project_id, SEED)
    assert first is not None and first.created["shot"] == 69
    assert seed.seed_if_empty(db, project_id, SEED) is None  # перезапуск ничего не трогает


def test_app_starts_with_data_from_excel(env, monkeypatch):
    monkeypatch.setenv("SEED_XLSX", str(SEED))
    from fastapi.testclient import TestClient

    from app import db as database
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    with TestClient(create_app()), database.session_factory()() as session:
        assert _count(session, models.Shot) == 69 and _count(session, models.Task) == 29


# --- грязный файл: предупреждения вместо падений ------------------------------------


def _doctored(tmp_path: Path, edit) -> Path:
    wb = openpyxl.load_workbook(SEED)
    edit(wb)
    out = tmp_path / "doctored.xlsx"
    wb.save(out)
    return out


def test_unknown_references_become_warnings_not_crashes(db, tmp_path):
    def edit(wb):
        shots = wb["Шоты"]
        shots["G2"] = "LC-01, ZZ-99"  # неизвестный ассет
        shots["D3"] = "Сверхкрупный"  # неизвестная крупность
        wb["Сетапы"]["C2"] = "99.99"  # неизвестный шот
        wb["Ассеты"]["H2"] = "https://example.com/ref"  # референс не импортируется
        wb["Шоты"]["O2"] = "Артём"  # ответственный не сопоставлен

    bundle = read_workbook(_doctored(tmp_path, edit))
    joined = "\n".join(bundle.warnings)
    for fragment in ("ZZ-99", "Сверхкрупный", "99.99", "Референс", "Артём"):
        assert fragment in joined
    report = apply_bundle(db, _project_id(db), bundle)
    assert report.created["shot"] == 69  # импорт всё равно прошёл


def test_missing_sheet_or_column_stops_with_a_clear_message(tmp_path):
    def drop_sheet(wb):
        del wb["Задачи"]

    with pytest.raises(WorkbookError, match="Задачи"):
        read_workbook(_doctored(tmp_path, drop_sheet))

    def drop_column(wb):
        wb["Шоты"]["F1"] = "Что-то другое"

    with pytest.raises(WorkbookError, match="Длит"):
        read_workbook(_doctored(tmp_path, drop_column))


def test_columns_are_found_by_header_not_by_letter(db, tmp_path):
    def edit(wb):
        ws = wb["Сцены"]
        ws.insert_cols(2)  # сдвигаем всё вправо: буквы поплыли, заголовки остались
        ws["B1"] = "Лишняя колонка"

    bundle = read_workbook(_doctored(tmp_path, edit))
    assert len(bundle.scenes) == 12 and bundle.scenes[0].title == "Два зеркала"
