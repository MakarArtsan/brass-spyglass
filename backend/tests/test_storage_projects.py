"""Место считается по проектам: у каждого свои файлы и свой лимит, а диск тарифа делят все."""

import pytest

from app import db as database
from app import models, storage
from app.config import get_settings
from app.services import projects

GIB = 1024**3


def make_file(project_id: int, size: int, *, originals: int = 0, deleted: bool = False) -> int:
    """Файл проекта: строка в базе и каталог с оригиналом на диске (как после загрузки)."""
    from app.db import utcnow

    settings = get_settings()
    with database.session_factory()() as db:  # без проекта: пишем в любой
        file = models.File(
            project_id=project_id,
            kind="image",
            source="upload",
            original_name="x.png",
            sha256="ab" * 32,
        )
        if deleted:
            file.deleted_at = utcnow()
        db.add(file)
        db.commit()
        name = f"{file.id:06d}"
        file_id = file.id
    (settings.files_dir / name).mkdir(parents=True, exist_ok=True)
    (settings.files_dir / name / "original.png").write_bytes(b"x" * size)
    (settings.files_dir / name / "preview.jpg").write_bytes(b"y" * 100)
    if originals:
        (settings.originals_dir / name).mkdir(parents=True, exist_ok=True)
        (settings.originals_dir / name / "original.png").write_bytes(b"z" * originals)
    storage.forget_project(project_id)
    return file_id


def used(project_id: int, *, fresh: bool = True) -> int:
    with database.session_factory()() as db:
        return storage.project_used_bytes(get_settings(), db, project_id, fresh=fresh)


@pytest.fixture
def two(db):
    first = projects.get_by_slug(db, "brass-spyglass")
    second = models.Project(**{**projects.DEFAULT_PROJECT, "slug": "second", "title": "Второй"})
    db.add(second)
    db.commit()
    storage.forget(get_settings())
    return first.id, second.id


def test_each_project_counts_only_its_own_files(db, two):
    a, b = two
    make_file(a, 1000)
    make_file(a, 2000, originals=500)  # оригинал до сжатия тоже занимает место
    make_file(b, 300)
    assert used(a) == 1000 + 100 + 2000 + 100 + 500
    assert used(b) == 300 + 100


def test_files_in_the_trash_still_count_until_they_are_removed_from_disk(db, two):
    a, _ = two
    make_file(a, 1000, deleted=True)
    assert used(a) == 1100


def test_a_project_is_refused_by_its_own_limit_and_not_by_a_neighbours_files(db, two):
    a, b = two
    make_file(a, 600_000)
    settings = get_settings()
    limit = 1_000_000 / GIB
    with database.session_factory()() as room:
        with pytest.raises(storage.NoRoom, match="не хватает места"):
            storage.ensure_room(settings, room, a, limit, 500_000)  # 600 КБ + 500 КБ > 1 МБ
        storage.ensure_room(settings, room, b, limit, 500_000)  # у второго проекта места хватает


def test_the_whole_disk_cannot_be_overfilled_even_if_a_project_has_quota_left(db, two, monkeypatch):
    a, _ = two
    settings = get_settings()
    in_use = storage.used_bytes(settings, fresh=True)  # база, бэкапы и кэш — общие
    monkeypatch.setattr(settings, "disk_total_gb", (in_use + 2000) / GIB)
    with database.session_factory()() as room:
        storage.ensure_room(settings, room, a, 5.0, 1000)  # помещается
        with pytest.raises(storage.NoRoom, match="делят все проекты"):
            storage.ensure_room(settings, room, a, 5.0, 3000)
    with pytest.raises(storage.NoRoom, match="делят все проекты"):
        storage.ensure_disk(settings, 3000)


def test_usage_reports_warning_and_full_by_the_project_limit():
    limit = 1000 / GIB
    assert storage.usage(limit, 500) == storage.Usage(500, 1000, 50.0, False, False)
    assert storage.usage(limit, 850).warn and not storage.usage(limit, 850).full
    assert storage.usage(limit, 1000).full
    assert storage.usage(0, 1).full  # лимит ноль — места нет


def test_the_project_count_is_cached_and_reset_when_a_file_appears(db, two):
    a, b = two
    settings = get_settings()
    make_file(a, 1000)
    assert used(a) == 1100
    (settings.files_dir / "999999").mkdir()
    (settings.files_dir / "999999" / "x").write_bytes(b"1")
    with database.session_factory()() as session:
        session.add(models.File(
            project_id=a, kind="image", source="upload", original_name="y.png", sha256="cd" * 32,
        ))  # fmt: skip
        session.commit()
    assert used(a, fresh=False) == 1100  # кэш на несколько секунд
    storage.forget_project(a)
    assert used(a, fresh=False) >= 1100  # сброшено: считается заново
    storage.forget(settings)
    mine = str(settings.data_dir)
    assert not any(key[0] == mine for key in storage._project_cache)  # noqa: SLF001


def test_the_dashboard_of_a_project_shows_its_own_usage(seeded_client):
    from app.constants import Role
    from tests.conftest import login

    login(seeded_client, "owner", "Артём")
    with database.session_factory()() as db:
        first = projects.get_by_slug(db, "brass-spyglass")
        second = models.Project(**{**projects.DEFAULT_PROJECT, "slug": "second", "title": "Второй"})
        db.add(second)
        db.flush()
        owner = db.query(models.User).filter_by(name="Артём").one()
        from app.services import members

        members.ensure(db, second, owner, role=Role.OWNER)
        db.commit()
    make_file(first.id, 400_000)
    storage.forget(get_settings())
    mine = seeded_client.get("/api/p/brass-spyglass/dashboard").json()["media"]["storage"]
    other = seeded_client.get("/api/p/second/dashboard").json()["media"]["storage"]
    assert mine["used_bytes"] >= 400_100 and other["used_bytes"] == 0
