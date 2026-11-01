"""Чистые вычисления дашборда: готовность, Seedance, тревоги, активность, сгорание."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app import metrics as m

D0 = date(2026, 10, 28)


def at(day: date, hour: int = 12) -> datetime:
    """Момент в этот день по Москве (UTC+3)."""
    return datetime(day.year, day.month, day.day, hour, tzinfo=m.TEAM_TZ).astimezone(UTC)


def shot(id: int, sec: float, status: str, tool: str | None = "seedance", due=None) -> m.ShotFull:
    return m.ShotFull(id, f"01.0{id}", 1, sec, status, tool, due)


# --- готовность ----------------------------------------------------------------------------------


def test_progress_is_done_over_all_minus_cut_like_excel():
    got = m.progress(["done", "done", "in_progress", "not_started", "cut", "cut"])
    assert (got.done, got.total, got.pct) == (2, 4, 50.0)


def test_progress_of_nothing_is_zero_not_an_error():
    assert m.progress([]).pct == 0.0
    assert m.progress(["cut"]).pct == 0.0


def test_ready_seconds_count_only_done_shots():
    shots = [shot(1, 10, "done"), shot(2, 5, "review"), shot(3, 4, "cut"), shot(4, 6, "done")]
    assert m.ready_seconds(shots) == 16


def test_seedance_share_is_by_seconds_without_cut_shots():
    shots = [
        shot(1, 6, "done", "seedance"),
        shot(2, 2, "done", "blender_3d"),
        shot(3, 2, "done", "seedance"),
        shot(4, 100, "cut", "other_video"),  # вырезанное не считается
    ]
    got = m.seedance_share(shots)
    assert (got.seedance_sec, got.total_sec, got.pct, got.target_pct) == (8, 10, 80.0, 70.0)
    assert m.seedance_share([]).pct == 0.0


def test_runtime_zone_edges_are_inclusive():
    assert m.runtime(300, 360, 300, 420).in_zone
    assert m.runtime(420, 360, 300, 420).in_zone
    assert not m.runtime(299.9, 360, 300, 420).in_zone
    assert not m.runtime(421, 360, 300, 420).in_zone


# --- тревоги -------------------------------------------------------------------------------------


def test_overdue_skips_done_cut_and_undated_and_today():
    today = date(2026, 11, 5)
    items = [
        m.Dated("task", 1, "in_progress", date(2026, 11, 4)),  # просрочено
        m.Dated("task", 2, "done", date(2026, 11, 1)),
        m.Dated("shot", 3, "cut", date(2026, 11, 1)),
        m.Dated("scene", 4, "not_started", None),
        m.Dated("asset", 5, "review", today),  # срок сегодня — ещё не просрочено
        m.Dated("shot", 6, "rework", date(2026, 10, 1)),  # просрочено
    ]
    assert [i.id for i in m.overdue(items, today)] == [1, 6]


def test_long_shots_are_over_15_seconds_and_not_cut():
    shots = [shot(1, 15, "done"), shot(2, 15.5, "done"), shot(3, 20, "cut"), shot(4, 16, "review")]
    assert [s.id for s in m.long_shots(shots)] == [2, 4]


# --- активность ----------------------------------------------------------------------------------


def row(day: date, kind: str, actor: int | None = 1, closed: bool = False, hour: int = 12):
    return m.ActivityRow(at(day, hour), actor, kind, closed)


def test_heatmap_fills_empty_days_and_buckets_by_team_midnight():
    rows = [
        row(D0, m.UPLOAD),
        row(D0, m.STATUS),
        row(D0 + timedelta(days=2), m.COMMENT),
        # 23:30 UTC — это уже следующие сутки по Москве
        m.ActivityRow(datetime(2026, 10, 28, 23, 30, tzinfo=UTC), 1, m.OTHER),
    ]
    got = m.heatmap(rows, D0, D0 + timedelta(days=2))
    assert got == [(D0, 2), (D0 + timedelta(days=1), 1), (D0 + timedelta(days=2), 1)]


def test_daily_bars_cover_14_days_split_by_type_and_user_and_skip_other():
    today = date(2026, 11, 14)
    rows = [
        row(today, m.UPLOAD, actor=1),
        row(today, m.UPLOAD, actor=2),
        row(today, m.STATUS, actor=1),
        row(today, m.OTHER, actor=1),  # не входит в столбики
        row(today - timedelta(days=13), m.COMMENT, actor=2),
        row(today - timedelta(days=14), m.COMMENT, actor=2),  # за окном
    ]
    bars = m.daily_bars(rows, today)
    assert len(bars) == 14 and bars[-1].day == today and bars[0].day == today - timedelta(days=13)
    assert (bars[-1].uploads, bars[-1].statuses, bars[-1].comments) == (2, 1, 0)
    assert bars[-1].by_user == {1: 2, 2: 1}
    assert bars[0].comments == 1 and sum(b.comments for b in bars) == 1


def test_contribution_counts_week_uploads_and_closed_sorted_by_total():
    today = date(2026, 11, 14)
    rows = [
        row(today, m.UPLOAD, actor=2),
        row(today, m.UPLOAD, actor=2),
        row(today, m.STATUS, actor=1, closed=True),
        row(today, m.STATUS, actor=1, closed=True),
        row(today, m.STATUS, actor=1, closed=True),
        row(today - timedelta(days=6), m.UPLOAD, actor=3),  # последний день окна
        row(today - timedelta(days=7), m.UPLOAD, actor=3),  # уже за неделей
        row(today, m.UPLOAD, actor=None),  # системное действие
    ]
    got = m.contribution(rows, today)
    assert [(c.user_id, c.uploads, c.closed) for c in got] == [(1, 0, 3), (2, 2, 0), (3, 1, 0)]


# --- история и сгорание --------------------------------------------------------------------------


def _ends(days: int) -> list[datetime]:
    return [m.end_of_day(D0 + timedelta(days=i)) for i in range(days)]


def test_history_rolls_the_log_back_from_the_current_state():
    now = {
        1: m.ShotState(10, "done", True),
        2: m.ShotState(5, "in_progress", True),
        3: m.ShotState(4, "done", True),  # создан и закрыт на 3-й день
    }
    d1, d2 = D0 + timedelta(days=1), D0 + timedelta(days=2)
    events = [
        m.ShotEvent(1, at(d1), 1, "status", status=("not_started", "done")),
        m.ShotEvent(2, at(d2, 12), 3, "create"),
        m.ShotEvent(3, at(d2, 13), 3, "status", status=("not_started", "done")),
    ]
    got = m.history_at(now, events, _ends(4))
    assert got == [
        (0, 15),  # до закрытия шота 1; шота 3 ещё нет
        (10, 15),
        (14, 19),
        (14, 19),
    ]


def test_history_undoes_delete_restore_and_duration_edits():
    now = {
        1: m.ShotState(8, "done", False),  # удалён на 2-й день
        2: m.ShotState(6, "done", True),  # удлинён с 4 до 6 на 2-й день
        3: m.ShotState(3, "done", True),  # удалён и восстановлен
    }
    d2 = D0 + timedelta(days=1)
    events = [
        m.ShotEvent(1, at(d2, 10), 1, "delete"),
        m.ShotEvent(2, at(d2, 11), 2, "update", duration=(4, 6)),
        m.ShotEvent(3, at(d2, 9), 3, "delete"),
        m.ShotEvent(4, at(d2, 10), 3, "restore"),
    ]
    got = m.history_at(now, events, _ends(2))
    # конец 1-го дня: шот 1 жив (8), шот 2 длиной 4, шот 3 в корзине
    assert got[0] == (8 + 4 + 3, 15)
    assert got[1] == (6 + 3, 9)


def test_history_ignores_events_of_unknown_shots():
    now = {1: m.ShotState(5, "done", True)}
    events = [m.ShotEvent(1, at(D0 + timedelta(days=1)), 99, "status", status=("a", "done"))]
    assert m.history_at(now, events, _ends(1)) == [(5, 5)]


def _series(ready: list[float], total: float = 20) -> list[tuple[date, float, float]]:
    return [(D0 + timedelta(days=i), r, total) for i, r in enumerate(ready)]


def test_burndown_ideal_line_and_forecast_at_current_pace():
    deadline = D0 + timedelta(days=10)
    today = D0 + timedelta(days=3)
    got = m.burndown(_series([0, 4, 8, 12]), deadline, today)
    assert len(got.points) == 11
    assert [p.ideal for p in got.points[:4]] == [20, 18, 16, 14]
    assert got.points[-1].ideal == 0
    assert [p.actual for p in got.points[:4]] == [20, 16, 12, 8]
    assert all(p.actual is None for p in got.points[4:])
    assert (got.remaining_sec, got.pace_sec_per_day) == (8, 4)
    assert got.forecast == today + timedelta(days=2) and got.finishes_in_time is True


def test_burndown_forecast_after_deadline_is_reported_as_late():
    deadline = D0 + timedelta(days=5)
    today = D0 + timedelta(days=4)
    got = m.burndown(_series([0, 1, 2, 3, 4]), deadline, today)  # 1 сек в сутки, осталось 16
    assert got.forecast == today + timedelta(days=16)
    assert got.finishes_in_time is False


def test_burndown_without_progress_has_no_forecast():
    got = m.burndown(_series([0, 0, 0]), D0 + timedelta(days=10), D0 + timedelta(days=2))
    assert got.pace_sec_per_day == 0 and got.forecast is None and got.finishes_in_time is None


def test_burndown_on_the_first_day_has_no_pace_yet():
    got = m.burndown(_series([0]), D0 + timedelta(days=10), D0)
    assert got.forecast is None and got.remaining_sec == 20


def test_burndown_when_everything_is_ready_finishes_today():
    today = D0 + timedelta(days=2)
    got = m.burndown(_series([0, 10, 20]), D0 + timedelta(days=10), today)
    assert got.remaining_sec == 0 and got.forecast == today and got.finishes_in_time is True


def test_burndown_pace_uses_only_the_last_week():
    series = _series([0, 0, 0, 0, 0, 0, 0, 0, 4, 8, 12, 16, 20, 20, 20, 20, 20][:17], total=40)
    today = D0 + timedelta(days=16)
    got = m.burndown(series, D0 + timedelta(days=30), today)
    # За последние 7 суток готово 20 − 8 = 12 сек: темп ≈ 1,71, осталось 20, то есть ещё 12 суток.
    # По всей истории темп был бы 20 / 16 = 1,25: ранний прогресс не должен разбавлять оценку.
    assert got.pace_sec_per_day == pytest.approx(1.71, abs=0.01)
    assert got.forecast == today + timedelta(days=12)


def test_team_date_and_end_of_day_use_moscow_midnight():
    assert m.team_date(datetime(2026, 10, 28, 21, 30, tzinfo=UTC)) == date(2026, 10, 29)
    assert m.end_of_day(date(2026, 10, 28)) == datetime(2026, 10, 28, 21, 0, tzinfo=UTC)
