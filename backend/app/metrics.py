"""Вычисляемое не хранится (ТЗ): таймкоды сцен, суммы, % готовности считаются здесь.

Чистые функции работают на простых структурах и тестируются без БД; обёртки ниже читают БД.
«Вырезано» не занимает времени: вырезанная сцена не сдвигает таймкоды, вырезанные шоты не
входят в суммы (так же, как в Excel-трекере: «хронометраж по шотам без вырезанных»).
"""

import dataclasses
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, storage
from app.config import Settings
from app.constants import FileKind, FileSource, Status

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


# --- таймлайн фильма: раскладка шотов и звука (аниматик, экспорт) ---------------------------------


@dataclass(frozen=True, slots=True)
class ShotLay:
    id: int
    scene_id: int
    order: int
    duration_sec: float
    status: str


@dataclass(frozen=True, slots=True)
class ShotSpan:
    shot_id: int
    scene_id: int
    start_sec: float
    end_sec: float


@dataclass(frozen=True, slots=True)
class SceneSpan:
    scene_id: int
    start_sec: float
    end_sec: float
    shots: tuple[ShotSpan, ...]


def film_layout(scenes: Sequence[SceneIn], shots: Sequence[ShotLay]) -> list[SceneSpan]:
    """Шоты встык в порядке трекера: сцены по `order`, шоты внутри сцены по `order`.

    Ширина шота — его длительность; у сцены без живых шотов — её плановая длительность.
    Вырезанные сцены и шоты на таймлайне времени не занимают. Номер сцены на порядок не влияет.
    """
    by_scene: dict[int, list[ShotLay]] = defaultdict(list)
    for shot in shots:
        if shot.status != CUT:
            by_scene[shot.scene_id].append(shot)
    out: list[SceneSpan] = []
    cursor = 0.0
    for scene in sorted(scenes, key=lambda s: (s.order, s.id)):
        if scene.status == CUT:
            continue
        start = cursor
        spans: list[ShotSpan] = []
        for shot in sorted(by_scene[scene.id], key=lambda s: (s.order, s.id)):
            spans.append(ShotSpan(shot.id, scene.id, cursor, cursor + shot.duration_sec))
            cursor += shot.duration_sec
        if not spans:
            cursor += scene.planned_sec
        out.append(SceneSpan(scene.id, start, cursor, tuple(spans)))
    return out


DEFAULT_CUE_SEC = 2.0
# Дорожки звука на таймлайне (ТЗ: A1 — реплики, A2 — SFX, A3 — музыка). Тишина дорожки не занимает.
SOUND_LANES: dict[str, int | None] = {
    "dialogue": 1,
    "sfx": 2,
    "ambience": 2,
    "music": 3,
    "silence": None,
}


@dataclass(frozen=True, slots=True)
class CueIn:
    id: int
    scene_id: int | None
    shot_id: int | None
    offset_sec: float
    duration_sec: float | None  # длительность звукового файла, если он есть


def cue_span(cue: CueIn, layout: Sequence[SceneSpan]) -> tuple[float, float] | None:
    """Где реплика или звук стоят на таймлайне: от начала шота (или сцены, или фильма) плюс сдвиг.
    None — если сцена или шот вырезаны и их на таймлайне нет."""
    anchor = 0.0
    if cue.shot_id is not None or cue.scene_id is not None:
        found: float | None = None
        for scene in layout:
            for shot in scene.shots:
                if shot.shot_id == cue.shot_id:
                    found = shot.start_sec
            if found is None and scene.scene_id == cue.scene_id:
                found = scene.start_sec
            if found is not None:
                break
        if found is None:
            return None
        anchor = found
    start = anchor + max(0.0, cue.offset_sec)
    return start, start + (cue.duration_sec or DEFAULT_CUE_SEC)


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


# === Дашборд (этап 2) ==========================================================================
# Определения сверены с листом «Дашборд» Excel-трекера: проценты — «готово / (всего − вырезано)»,
# «готовые секунды» — длительность шотов в статусе «Готово», доля Seedance — по секундам, а не по
# числу шотов. Числа считаются здесь и нигде больше: фронтенд только рисует.

# Команда живёт по Москве (UTC+3, без перехода на лето): по ней считаются «сегодня» и границы суток.
TEAM_TZ = timezone(timedelta(hours=3))
LONG_SHOT_SEC = 15  # лимит одного клипа Seedance
SEEDANCE = "seedance"
HISTORY_WINDOW_DAYS = 7  # окно, по которому оценивается текущий темп


def team_date(moment: datetime) -> date:
    return moment.astimezone(TEAM_TZ).date()


def end_of_day(day: date) -> datetime:
    """Последний момент суток по Москве, в UTC: граница, по которой считается «на конец дня»."""
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=TEAM_TZ).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Progress:
    done: int
    total: int  # без вырезанных
    pct: float  # 0…100


def progress(statuses: Iterable[str]) -> Progress:
    """Готовность списка: готовые / (все − вырезанные), как в Excel."""
    alive = [s for s in statuses if s != CUT]
    done = sum(1 for s in alive if s == DONE)
    return Progress(done, len(alive), round(100 * done / len(alive), 1) if alive else 0.0)


@dataclass(frozen=True, slots=True)
class ShotFull:
    id: int
    code: str
    scene_id: int
    duration_sec: float
    status: str
    tool: str | None
    due_date: date | None


def ready_seconds(shots: Iterable[ShotFull]) -> float:
    return sum(s.duration_sec for s in shots if s.status == DONE)


@dataclass(frozen=True, slots=True)
class SeedanceShare:
    seedance_sec: float
    total_sec: float
    pct: float
    target_pct: float


def seedance_share(shots: Iterable[ShotFull], target_pct: float = 70.0) -> SeedanceShare:
    alive = [s for s in shots if s.status != CUT]
    total = sum(s.duration_sec for s in alive)
    seedance = sum(s.duration_sec for s in alive if s.tool == SEEDANCE)
    return SeedanceShare(
        seedance, total, round(100 * seedance / total, 1) if total else 0.0, target_pct
    )


@dataclass(frozen=True, slots=True)
class Runtime:
    shots_sec: float
    plan_sec: float
    min_sec: float
    max_sec: float
    in_zone: bool


def runtime(shots_sec: float, plan_sec: float, min_sec: float, max_sec: float) -> Runtime:
    return Runtime(shots_sec, plan_sec, min_sec, max_sec, min_sec <= shots_sec <= max_sec)


@dataclass(frozen=True, slots=True)
class Dated:
    """Что угодно с дедлайном: сцена, шот, ассет, задача, сетап, звук."""

    entity_type: str
    id: int
    status: str
    due_date: date | None


def overdue(items: Iterable[Dated], today: date) -> list[Dated]:
    """Просрочено: срок раньше сегодняшнего дня, а статус не «Готово» и не «Вырезано»."""
    return [
        i
        for i in items
        if i.due_date is not None and i.due_date < today and i.status not in (DONE, CUT)
    ]


def long_shots(shots: Iterable[ShotFull]) -> list[ShotFull]:
    return [s for s in shots if s.status != CUT and s.duration_sec > LONG_SHOT_SEC]


# --- активность ----------------------------------------------------------------------------------

UPLOAD, STATUS, COMMENT, OTHER = "upload", "status", "comment", "other"


@dataclass(frozen=True, slots=True)
class ActivityRow:
    at: datetime
    actor_id: int | None
    kind: str  # UPLOAD / STATUS / COMMENT / OTHER
    closed: bool = False  # статус сменён на «Готово»


def heatmap(rows: Iterable[ActivityRow], first: date, today: date) -> list[tuple[date, int]]:
    """Число действий по дням за весь проект; дни без действий тоже есть (нулём)."""
    counts: dict[date, int] = defaultdict(int)
    for row in rows:
        counts[team_date(row.at)] += 1
    span = (today - first).days
    return [
        (first + timedelta(days=i), counts.get(first + timedelta(days=i), 0))
        for i in range(span + 1)
    ]


@dataclass(frozen=True, slots=True)
class DayBar:
    day: date
    uploads: int
    statuses: int
    comments: int
    by_user: dict[int, int]


def daily_bars(rows: Iterable[ActivityRow], today: date, days: int = 14) -> list[DayBar]:
    """Столбики за последние `days` суток: загрузки, смены статусов, комментарии, по участникам."""
    window = [today - timedelta(days=days - 1 - i) for i in range(days)]
    stats: dict[date, dict[str, int]] = {d: defaultdict(int) for d in window}
    by_user: dict[date, dict[int, int]] = {d: defaultdict(int) for d in window}
    for row in rows:
        day = team_date(row.at)
        if day not in stats or row.kind == OTHER:
            continue
        stats[day][row.kind] += 1
        if row.actor_id is not None:
            by_user[day][row.actor_id] += 1
    return [
        DayBar(d, stats[d][UPLOAD], stats[d][STATUS], stats[d][COMMENT], dict(by_user[d]))
        for d in window
    ]


@dataclass(frozen=True, slots=True)
class Contribution:
    user_id: int
    uploads: int
    closed: int


def contribution(rows: Iterable[ActivityRow], today: date, days: int = 7) -> list[Contribution]:
    """Кто сколько загрузил и закрыл за неделю; по убыванию вклада."""
    since = today - timedelta(days=days - 1)
    uploads: dict[int, int] = defaultdict(int)
    closed: dict[int, int] = defaultdict(int)
    for row in rows:
        if row.actor_id is None or team_date(row.at) < since:
            continue
        if row.kind == UPLOAD:
            uploads[row.actor_id] += 1
        if row.closed:
            closed[row.actor_id] += 1
    ids = set(uploads) | set(closed)
    out = [Contribution(i, uploads[i], closed[i]) for i in ids]
    return sorted(out, key=lambda c: (-(c.uploads + c.closed), c.user_id))


# --- сгорание ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShotState:
    duration: float
    status: str
    alive: bool  # не в корзине


@dataclass(frozen=True, slots=True)
class ShotEvent:
    """Запись журнала о шоте. `status`/`duration` — пары (было, стало), если поле менялось."""

    id: int
    at: datetime
    shot_id: int
    action: str
    status: tuple[str, str] | None = None
    duration: tuple[float, float] | None = None


def history_at(
    now_state: dict[int, ShotState],
    events: Sequence[ShotEvent],
    day_ends: Sequence[datetime],
) -> list[tuple[float, float]]:
    """(готовые сек, всего сек) на конец каждого дня из `day_ends` (по возрастанию).

    Журнал откатывается назад от нынешнего состояния: базовая точка не нужна, импорт Excel пишет в
    журнал одну сводную строку, а не статус каждого шота. Откат: смена статуса и длительности
    возвращает «было»; создание шота — его ещё не было; удаление — он ещё был; восстановление —
    он ещё лежал в корзине.
    """
    state = dict(now_state)
    ordered = sorted(events, key=lambda e: (e.at, e.id), reverse=True)
    pointer = 0
    out: list[tuple[float, float]] = []
    for boundary in reversed(day_ends):
        while pointer < len(ordered) and ordered[pointer].at > boundary:
            _undo(state, ordered[pointer])
            pointer += 1
        alive = [s for s in state.values() if s.alive and s.status != CUT]
        out.append(
            (sum(s.duration for s in alive if s.status == DONE), sum(s.duration for s in alive))
        )
    out.reverse()
    return out


def _undo(state: dict[int, ShotState], event: ShotEvent) -> None:
    current = state.get(event.shot_id)
    if event.action == "create":
        if current is not None:
            state[event.shot_id] = ShotState(current.duration, current.status, False)
        return
    if current is None:
        return
    if event.action == "delete":
        state[event.shot_id] = ShotState(current.duration, current.status, True)
        return
    if event.action == "restore":
        state[event.shot_id] = ShotState(current.duration, current.status, False)
        return
    status = event.status[0] if event.status else current.status
    duration = event.duration[0] if event.duration else current.duration
    state[event.shot_id] = ShotState(duration, status, current.alive)


@dataclass(frozen=True, slots=True)
class BurndownPoint:
    day: date
    ideal: float
    actual: float | None  # None у будущих дней


@dataclass(frozen=True, slots=True)
class Burndown:
    points: list[BurndownPoint]
    total_sec: float
    remaining_sec: float
    pace_sec_per_day: float
    forecast: date | None  # когда закончим при текущем темпе; None, если оценить нечем
    deadline: date
    finishes_in_time: bool | None


def burndown(
    history: Sequence[tuple[date, float, float]],
    deadline: date,
    today: date,
) -> Burndown:
    """Сгорание: оставшиеся секунды до готовности против идеальной линии до `deadline`.

    `history` — (день, готово сек, всего сек) на конец каждого дня от старта проекта до сегодня.
    Темп — готовые секунды в сутки за последние `HISTORY_WINDOW_DAYS` суток (меньше, если проект
    моложе); без прогресса прогноза нет.
    """
    start = history[0][0]
    total_start = history[0][2]
    days = max((max(deadline, today) - start).days, 0)
    by_day = {d: (ready, total) for d, ready, total in history}
    span = (deadline - start).days
    points: list[BurndownPoint] = []
    for i in range(days + 1):
        day = start + timedelta(days=i)
        ideal = total_start * max(0.0, (deadline - day).days / span) if span > 0 else 0.0
        actual = None
        if day in by_day:
            ready, total = by_day[day]
            actual = total - ready
        points.append(
            BurndownPoint(day, round(ideal, 1), None if actual is None else round(actual, 1))
        )

    ready_now, total_now = by_day[today] if today in by_day else history[-1][1:]
    remaining = total_now - ready_now
    window = min(HISTORY_WINDOW_DAYS, (today - start).days)
    pace = 0.0
    if window > 0:
        base_day = today - timedelta(days=window)
        pace = max(0.0, (ready_now - by_day.get(base_day, history[0][1:])[0]) / window)
    forecast: date | None = None
    if remaining <= 0:
        forecast = today
    elif pace > 0:
        forecast = today + timedelta(days=math.ceil(remaining / pace))
    return Burndown(
        points=points,
        total_sec=round(total_start, 1),
        remaining_sec=round(remaining, 1),
        pace_sec_per_day=round(pace, 2),
        forecast=forecast,
        deadline=deadline,
        finishes_in_time=None if forecast is None else forecast <= deadline,
    )


# --- обёртки над БД для дашборда -----------------------------------------------------------------


NOISE_ACTIONS = ("login", "access_revoked", "import")  # не «работа команды»: в активность не идут
DASHBOARD_ENTITIES = (
    ("scene", models.Scene),
    ("shot", models.Shot),
    ("asset", models.Asset),
    ("setup_payoff", models.SetupPayoff),
    ("sound_cue", models.SoundCue),
    ("task", models.Task),
)


def load_shots_full(db: Session, project_id: int) -> list[ShotFull]:
    rows = db.execute(
        select(
            models.Shot.id,
            models.Shot.code,
            models.Shot.scene_id,
            models.Shot.duration_sec,
            models.Shot.status,
            models.Shot.tool,
            models.Shot.due_date,
        ).where(models.Shot.project_id == project_id, models.Shot.deleted_at.is_(None))
    )
    return [ShotFull(*row) for row in rows]


def load_dated(db: Session, project_id: int) -> list[Dated]:
    items: list[Dated] = []
    for entity_type, model in DASHBOARD_ENTITIES:
        rows = db.execute(
            select(model.id, model.status, model.due_date).where(
                model.project_id == project_id,  # type: ignore[attr-defined]
                model.deleted_at.is_(None),  # type: ignore[attr-defined]
            )
        )
        items.extend(Dated(entity_type, *row) for row in rows)
    return items


def _json_pair(raw: Any) -> tuple[Any, Any] | None:
    """`json_extract` отдаёт пару «было/стало» текстом `["a","b"]`; одиночное значение — не пара."""
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return (value[0], value[1]) if isinstance(value, list) and len(value) == 2 else None


def load_activity_rows(db: Session, project_id: int) -> list[ActivityRow]:
    status = func.json_extract(models.Activity.diff, "$.status")
    rows = db.execute(
        select(
            models.Activity.at,
            models.Activity.actor_id,
            models.Activity.action,
            models.Activity.entity_type,
            status,
        )
        .where(
            (models.Activity.project_id == project_id) | models.Activity.project_id.is_(None),
            models.Activity.action.not_in(NOISE_ACTIONS),
        )
        .order_by(models.Activity.id)
    )
    out: list[ActivityRow] = []
    for at, actor_id, action, entity_type, raw_status in rows:
        pair = _json_pair(raw_status) if action in ("status", "update") else None
        if entity_type == "file" and action == "create":
            kind = UPLOAD
        elif entity_type == "comment" and action == "create":
            kind = COMMENT
        elif pair is not None:
            kind = STATUS
        else:
            kind = OTHER
        out.append(ActivityRow(at, actor_id, kind, closed=pair is not None and pair[1] == DONE))
    return out


def load_shot_history_inputs(
    db: Session, project_id: int
) -> tuple[dict[int, ShotState], list[ShotEvent]]:
    now_state = {
        row[0]: ShotState(row[1], row[2], row[3] is None)
        for row in db.execute(
            select(
                models.Shot.id,
                models.Shot.duration_sec,
                models.Shot.status,
                models.Shot.deleted_at,
            ).where(models.Shot.project_id == project_id)
        )
    }
    status = func.json_extract(models.Activity.diff, "$.status")
    duration = func.json_extract(models.Activity.diff, "$.duration_sec")
    rows = db.execute(
        select(
            models.Activity.id,
            models.Activity.at,
            models.Activity.entity_id,
            models.Activity.action,
            status,
            duration,
        ).where(
            models.Activity.entity_type == "shot",
            models.Activity.entity_id.is_not(None),
            models.Activity.action.in_(("create", "status", "update", "delete", "restore")),
        )
    )
    events: list[ShotEvent] = []
    for event_id, at, shot_id, action, raw_status, raw_duration in rows:
        changed = action in ("status", "update")
        events.append(
            ShotEvent(
                event_id,
                at,
                shot_id,
                action,
                status=_json_pair(raw_status) if changed else None,
                duration=_json_pair(raw_duration) if changed else None,
            )
        )
    return now_state, events


def _scene_rows(db: Session, project_id: int) -> list[models.Scene]:
    return list(
        db.scalars(
            select(models.Scene)
            .where(models.Scene.project_id == project_id, models.Scene.deleted_at.is_(None))
            .order_by(models.Scene.order, models.Scene.id)
        )
    )


def _media_summary(db: Session, project_id: int) -> dict[str, Any]:
    rows = db.execute(
        select(models.File.kind, models.File.source, func.count())
        .where(
            models.File.project_id == project_id,
            models.File.deleted_at.is_(None),
            models.File.is_current.is_(True),
        )
        .group_by(models.File.kind, models.File.source)
    )
    by_kind = {kind.value: 0 for kind in FileKind}
    from_telegram = 0
    for kind, source, count in rows:
        by_kind[kind] += count
        if source == FileSource.TELEGRAM.value:
            from_telegram += count
    return {"total": sum(by_kind.values()), "by_kind": by_kind, "from_telegram": from_telegram}


def dashboard_data(
    db: Session,
    project: models.Project,
    settings: Settings,
    now: datetime,
    user_id: int,
) -> dict[str, Any]:
    """Все числа дашборда за один проход. Фронтенд ничего не считает, только рисует."""
    pid = project.id
    today = team_date(now)
    scene_rows = _scene_rows(db, pid)
    scenes = [SceneIn(s.id, s.order, s.planned_sec, s.status) for s in scene_rows]
    shots = load_shot_inputs(db, pid)
    full = load_shots_full(db, pid)
    stats = scene_stats(scenes, shots)
    plan = plan_total_sec(scenes)
    shots_sec = shots_total_sec(shots)
    ready = ready_seconds(full)
    dated = load_dated(db, pid)

    def statuses(entity_type: str) -> list[str]:
        return [i.status for i in dated if i.entity_type == entity_type]

    def prog(entity_type: str) -> dict[str, Any]:
        p = progress(statuses(entity_type))
        return {"done": p.done, "total": p.total, "pct": p.pct}

    seed = seedance_share(full)
    run = runtime(shots_sec, plan, project.target_min_sec, project.target_max_sec)
    late = overdue(dated, today)
    longs = long_shots(full)
    orphans = assets_without_shots(db, pid)
    alive_scenes = [s for s in scene_rows if s.status != CUT]
    no_final = [s for s in alive_scenes if s.final_file_id is None]

    activity = load_activity_rows(db, pid)
    first_activity = min((team_date(a.at) for a in activity), default=today)
    start = min(team_date(project.created_at), first_activity, today)
    bars = daily_bars(activity, today)
    contrib = contribution(activity, today)

    now_state, events = load_shot_history_inputs(db, pid)
    span = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    hist = history_at(now_state, events, [end_of_day(d) for d in span])
    burn = burndown(
        [(d, ready_d, total_d) for d, (ready_d, total_d) in zip(span, hist, strict=True)],
        team_date(project.deadline_internal),
        today,
    )

    tasks_now = list(
        db.scalars(
            select(models.Task)
            .where(
                models.Task.project_id == pid,
                models.Task.deleted_at.is_(None),
                models.Task.assignee_id == user_id,
                models.Task.status.not_in((DONE, CUT)),
            )
            .order_by(models.Task.due_date.is_(None), models.Task.due_date, models.Task.id)
            .limit(8)
        )
    )

    return {
        "today": today.isoformat(),
        "readiness": {
            "ready_sec": ready,
            "shots_sec": shots_sec,
            "plan_sec": plan,
            "pct": round(100 * ready / shots_sec, 1) if shots_sec else 0.0,
            "shots": prog("shot"),
            "assets": prog("asset"),
            "tasks": prog("task"),
        },
        "runtime": dataclasses.asdict(run),
        "seedance": dataclasses.asdict(seed),
        "media": _media_summary(db, pid)
        | {"storage": dataclasses.asdict(storage.usage(settings, project.storage_limit_gb))},
        "activity": {
            "heatmap": [{"d": d.isoformat(), "n": n} for d, n in heatmap(activity, start, today)],
            "bars": [
                {
                    "d": b.day.isoformat(),
                    "uploads": b.uploads,
                    "statuses": b.statuses,
                    "comments": b.comments,
                    "by_user": b.by_user,
                }
                for b in bars
            ],
        },
        "burndown": {
            "points": [
                {"d": p.day.isoformat(), "ideal": p.ideal, "actual": p.actual} for p in burn.points
            ],
            "total_sec": burn.total_sec,
            "remaining_sec": burn.remaining_sec,
            "pace_sec_per_day": burn.pace_sec_per_day,
            "forecast": burn.forecast.isoformat() if burn.forecast else None,
            "deadline": burn.deadline.isoformat(),
            "finishes_in_time": burn.finishes_in_time,
        },
        "contribution": [dataclasses.asdict(c) for c in contrib],
        "film_strip": [
            {
                "scene_id": s.id,
                "number": s.number,
                "title": s.title,
                "planned_sec": s.planned_sec,
                "ready_pct": stats[s.id].ready_pct,
                "status": s.status,
            }
            for s in alive_scenes
        ],
        "alerts": {
            "overdue": {
                "total": len(late),
                "by_type": {
                    t: sum(1 for i in late if i.entity_type == t) for t, _ in DASHBOARD_ENTITIES
                },
            },
            "long_shots": [
                {"id": s.id, "code": s.code, "duration_sec": s.duration_sec} for s in longs
            ],
            "orphan_assets": [{"id": a.id, "code": a.code, "name": a.name} for a in orphans],
            "scenes_without_final": [
                {"id": s.id, "number": s.number, "title": s.title} for s in no_final
            ],
        },
        "drum": [
            {"scene_id": s.id, "number": s.number, "title": s.title, "level": s.drum_level}
            for s in alive_scenes
        ],
        "my_tasks": [
            {
                "id": t.id,
                "code": t.code,
                "title": t.title,
                "status": t.status,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "overdue": t.due_date is not None and t.due_date < today,
            }
            for t in tasks_now
        ],
    }
