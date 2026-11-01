"""Ночные бэкапы: целостная копия, 14 штук, отправка владельцу, расписание."""

import asyncio
import gzip
import os
import sqlite3
import threading
from datetime import UTC, datetime

import pytest

from app import backup, maintenance, models
from app.config import get_settings
from app.constants import JobType
from tests.conftest import login


def at(year, month, day, hour, minute=0) -> datetime:
    """Момент по Москве (UTC+3) в виде aware-времени."""
    return datetime(year, month, day, hour, minute, tzinfo=backup.TEAM_TZ).astimezone(UTC)


@pytest.fixture
def loop_in_thread():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


@pytest.fixture(autouse=True)
def reset_sender():
    yield
    backup.sender = None
    backup.loop = None


def make_copy(settings, name: str, taken: datetime | None = None) -> None:
    """Файл копии со временем изменения `taken` (по умолчанию — сейчас)."""
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    path = settings.backups_dir / name
    path.write_bytes(b"x")
    stamp = (taken or datetime.now(UTC)).timestamp()
    os.utime(path, (stamp, stamp))


# --- снимок ----------------------------------------------------------------------------------------


def test_the_snapshot_is_a_whole_readable_database(seeded_client, tmp_path):
    settings = get_settings()
    path = backup.snapshot(settings, at(2026, 11, 2, 3))
    assert path.name == "app-20261102-000000.sqlite.gz"  # 03:00 МСК = 00:00 UTC, имя — по UTC
    restored = tmp_path / "restored.sqlite"
    restored.write_bytes(gzip.decompress(path.read_bytes()))
    con = sqlite3.connect(restored)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("SELECT count(*) FROM scene").fetchone()[0] == 12
        assert con.execute("SELECT count(*) FROM shot").fetchone()[0] == 69
    finally:
        con.close()
    # временные файлы не остаются
    assert sorted(p.name for p in settings.backups_dir.iterdir()) == [path.name]


def test_the_snapshot_does_not_stop_the_running_app(seeded_client):
    login(seeded_client, "owner", "Артём")
    backup.snapshot(get_settings())
    assert (
        seeded_client.get("/api/shots").status_code == 200
    )  # приложение живо, база читается и пишется
    assert (
        seeded_client.post("/api/tasks", json={"code": "T-99", "title": "после бэкапа"}).status_code
        == 201
    )


def test_only_fourteen_copies_are_kept(env):
    settings = get_settings()
    for day in range(1, 21):
        make_copy(settings, f"app-202610{day:02d}-000000.sqlite.gz")
    assert backup.prune(settings) == 6
    kept = sorted(p.name for p in settings.backups_dir.glob("app-*.gz"))
    assert (
        len(kept) == 14
        and kept[0] == "app-20261007-000000.sqlite.gz"
        and kept[-1].startswith("app-20261020")
    )


def test_foreign_files_in_the_backup_folder_are_never_pruned(env):
    settings = get_settings()
    make_copy(settings, "notes.txt")
    for day in range(1, 17):
        make_copy(settings, f"app-202610{day:02d}-000000.sqlite.gz")
    backup.prune(settings)
    assert (settings.backups_dir / "notes.txt").exists()


# --- расписание ------------------------------------------------------------------------------------


def test_the_first_copy_is_made_right_away(env):
    assert backup.is_due(get_settings(), at(2026, 11, 2, 14)) is True


def test_a_copy_is_made_once_a_night_after_three_by_moscow(env):
    settings = get_settings()
    make_copy(settings, "app-20261101-000000.sqlite.gz", taken=at(2026, 11, 1, 3, 5))
    assert backup.is_due(settings, at(2026, 11, 1, 20)) is False  # свежая: прошло 17 часов
    assert backup.is_due(settings, at(2026, 11, 2, 2, 30)) is False  # ещё не ночь по Москве
    assert backup.is_due(settings, at(2026, 11, 2, 3, 10)) is True  # новая ночь — новая копия


def test_a_stale_copy_is_caught_up_even_by_day(env):
    settings = get_settings()
    make_copy(settings, "app-20261101-000000.sqlite.gz", taken=at(2026, 10, 31, 3, 5))
    assert backup.is_due(settings, at(2026, 11, 1, 14)) is True  # приложение стояло: догоняем


def test_a_backup_job_is_queued_once_until_it_runs(seeded_client):
    settings = get_settings()
    assert maintenance.queue_backup_if_due(settings) is True
    assert maintenance.queue_backup_if_due(settings) is False  # такая задача уже ждёт
    from app import db as database

    with database.session_factory()() as db:
        types = [j.type for j in db.query(models.Job).all()]
    assert types.count(JobType.BACKUP.value) <= 1


# --- отправка --------------------------------------------------------------------------------------


def test_the_copy_is_sent_to_the_owner_and_the_status_is_recorded(seeded_client, loop_in_thread):
    sent = []

    async def send_file(path, caption):
        sent.append((path.name, caption))

    backup.sender, backup.loop = send_file, loop_in_thread
    result = backup.run(get_settings())
    assert result.sent and result.error is None
    assert sent and sent[0][0] == result.path.name and "Копия базы The Brass Spyglass" in sent[0][1]
    status = backup.read_status(get_settings())
    assert status and status["sent"] is True and status["error"] is None
    health = seeded_client.get("/api/health").json()
    assert health["backup"]["ok"] is True and health["backup"]["sent"] is True


def test_a_failed_send_keeps_the_copy_and_reports_the_reason(seeded_client, loop_in_thread):
    async def blocked(path, caption):
        raise RuntimeError("User is blocked")

    backup.sender, backup.loop = blocked, loop_in_thread
    result = backup.run(get_settings())
    assert result.path.exists() and not result.sent and "blocked" in result.error
    assert seeded_client.get("/api/health").json()["backup"]["ok"] is False


def test_without_a_bot_the_copy_stays_on_disk(seeded_client):
    result = backup.run(get_settings())
    assert result.path.exists() and not result.sent and "Бот не подключён" in result.error


def test_a_copy_over_the_limit_is_not_sent(seeded_client, loop_in_thread, monkeypatch):
    async def never(path, caption):
        raise AssertionError("не должна вызываться")

    backup.sender, backup.loop = never, loop_in_thread
    monkeypatch.setattr(backup, "SEND_LIMIT_MB", 0)
    result = backup.run(get_settings())
    assert not result.sent and "больше лимита" in result.error and result.path.exists()


def test_the_backup_job_runs_through_the_worker(seeded_client):
    """Задача `backup` из очереди делает копию (воркер уже запущен вместе с приложением)."""
    import time

    settings = get_settings()
    assert maintenance.queue_backup_if_due(settings) is True
    seeded_client.app.state.jobs.wake()
    deadline = time.time() + 30
    while time.time() < deadline and backup.newest(settings) is None:
        time.sleep(0.2)
    assert backup.newest(settings) is not None
