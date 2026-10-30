"""Вычисляемое не хранится (ТЗ): таймкоды сцен, суммы, % готовности считаются здесь.

Чистые функции работают на простых структурах и тестируются без БД; обёртки ниже читают БД.
«Вырезано» не занимает времени: вырезанная сцена не сдвигает таймкоды, вырезанные шоты не
входят в суммы (так же, как в Excel-трекере: «хронометраж по шотам без вырезанных»).
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.constants import Status

CUT = Status.CUT.value
DONE = Status.DONE.value


@dataclass(frozen=True, slots=True)
class SceneIn:
    id: int
    order: int
    planned_sec: float
    status: str


@dataclass(frozen=True, slots=True)
class ShotIn:
    scene_id: int
    duration_sec: float
    status: str


@dataclass(frozen=True, slots=True)
class SceneStat:
    scene_id: int
    start_sec: float | None  # None у вырезанной сцены: на таймлайне её нет
    end_sec: float | None
    planned_sec: float
    shots_count: int
    shots_sec: float
    delta_sec: float  # сумма шотов − план
    done_shots: int
    ready_pct: float  # доля готовых среди невырезанных шотов, 0…100


def timeline(scenes: Iterable[SceneIn]) -> dict[int, tuple[float | None, float | None]]:
    """Накопительная сумма planned_sec по order. Номер сцены на порядок не влияет."""
    out: dict[int, tuple[float | None, float | None]] = {}
    cursor = 0.0
    for scene in sorted(scenes, key=lambda s: (s.order, s.id)):
        if scene.status == CUT:
            out[scene.id] = (None, None)
            continue
        out[scene.id] = (cursor, cursor + scene.planned_sec)
        cursor += scene.planned_sec
    return out


def scene_stats(scenes: Sequence[SceneIn], shots: Sequence[ShotIn]) -> dict[int, SceneStat]:
    by_scene: dict[int, list[ShotIn]] = defaultdict(list)
    for shot in shots:
        by_scene[shot.scene_id].append(shot)
    times = timeline(scenes)
    stats: dict[int, SceneStat] = {}
    for scene in scenes:
        alive = [s for s in by_scene[scene.id] if s.status != CUT]
        done = sum(1 for s in alive if s.status == DONE)
        shots_sec = sum(s.duration_sec for s in alive)
        start, end = times[scene.id]
        stats[scene.id] = SceneStat(
            scene_id=scene.id,
            start_sec=start,
            end_sec=end,
            planned_sec=scene.planned_sec,
            shots_count=len(alive),
            shots_sec=shots_sec,
            delta_sec=shots_sec - scene.planned_sec,
            done_shots=done,
            ready_pct=round(100 * done / len(alive), 1) if alive else 0.0,
        )
    return stats


def plan_total_sec(scenes: Iterable[SceneIn]) -> float:
    return sum(s.planned_sec for s in scenes if s.status != CUT)


def shots_total_sec(shots: Iterable[ShotIn]) -> float:
    return sum(s.duration_sec for s in shots if s.status != CUT)


def format_timecode(seconds: float | None) -> str:
    """73.0 → «1:13»; пусто для вырезанной сцены."""
    if seconds is None:
        return "—"
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


# --- обёртки над БД ----------------------------------------------------------------------------


def load_scene_inputs(db: Session, project_id: int) -> list[SceneIn]:
    rows = db.execute(
        select(models.Scene.id, models.Scene.order, models.Scene.planned_sec, models.Scene.status)
        .where(models.Scene.project_id == project_id, models.Scene.deleted_at.is_(None))
        .order_by(models.Scene.order)
    )
    return [SceneIn(*row) for row in rows]


def load_shot_inputs(db: Session, project_id: int) -> list[ShotIn]:
    rows = db.execute(
        select(models.Shot.scene_id, models.Shot.duration_sec, models.Shot.status).where(
            models.Shot.project_id == project_id, models.Shot.deleted_at.is_(None)
        )
    )
    return [ShotIn(*row) for row in rows]


def project_scene_stats(db: Session, project_id: int) -> dict[int, SceneStat]:
    return scene_stats(load_scene_inputs(db, project_id), load_shot_inputs(db, project_id))


def assets_without_shots(db: Session, project_id: int) -> list[models.Asset]:
    used = (
        select(models.ShotAsset.asset_id)
        .join(models.Shot, models.Shot.id == models.ShotAsset.shot_id)
        .where(models.Shot.deleted_at.is_(None))
    )
    return list(
        db.scalars(
            select(models.Asset)
            .where(
                models.Asset.project_id == project_id,
                models.Asset.deleted_at.is_(None),
                models.Asset.status != CUT,
                models.Asset.id.not_in(used),
            )
            .order_by(models.Asset.code)
        )
    )


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str


def consistency_checks(db: Session, project_id: int) -> list[Check]:
    """Проверки из раздела ТЗ «Импорт»: план и шоты сходятся, ассеты без шотов видны."""
    scenes = load_scene_inputs(db, project_id)
    shots = load_shot_inputs(db, project_id)
    plan, total = plan_total_sec(scenes), shots_total_sec(shots)
    stats = scene_stats(scenes, shots)
    off = [s for s in stats.values() if abs(s.delta_sec) > 0.01]
    orphans = [a.code for a in assets_without_shots(db, project_id)]
    return [
        Check("Сумма плана сцен, сек", True, f"{plan:g}"),
        Check("Сумма шотов, сек", abs(plan - total) < 0.01, f"{total:g} (план {plan:g})"),
        Check("Сцены, где шоты расходятся с планом", not off, f"{len(off)}"),
        Check("Ассеты без шотов", True, ", ".join(orphans) or "нет"),
    ]
