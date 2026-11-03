"""Сжатие картинок при загрузке end-to-end: загрузка → превью → фоновая задача → подмена файла,
оригинал на 7 дней, «Вернуть оригинал», уборка, экономия на дашборде. Кодировщики настоящие."""

import hashlib
import io
import shutil
import time
from datetime import timedelta
from pathlib import Path

import pillow_heif
import pytest
from PIL import Image

from app import db as database
from app import metrics, models, worker
from app.config import get_settings
from app.constants import JobType
from app.db import utcnow
from app.services import compression, jobs
from tests.conftest import login
from tests.test_files import upload, wait_for
from tests.test_imagecompress import photo, screenshot

pillow_heif.register_heif_opener()


@pytest.fixture
def api(seeded_client, monkeypatch):
    monkeypatch.setenv("COMPRESS_IMAGES", "true")
    monkeypatch.setenv("CJPEG_BIN", shutil.which("cjpeg") or "cjpeg")
    get_settings.cache_clear()
    login(seeded_client, "owner", "Артём")
    return seeded_client


def png(image=None) -> bytes:
    buffer = io.BytesIO()
    (image or screenshot()).save(buffer, "PNG")
    return buffer.getvalue()


def jpeg(quality=96, image=None, **options) -> bytes:
    buffer = io.BytesIO()
    (image or photo()).save(buffer, "JPEG", quality=quality, **options)
    return buffer.getvalue()


def compressed(client, file_id: int, timeout: float = 40) -> dict:
    """Ждём, пока сжатие дало итог (done / small_gain / failed)."""
    return wait_for(
        client, file_id, ready=lambda f: f["compression"]["state"] is not None, timeout=timeout
    )


def settled(client, file_id: int) -> dict:
    """Превью готово и очередь задач опустела: больше ничего с файлом не произойдёт."""
    wait_for(client, file_id)
    deadline = time.time() + 20
    while time.time() < deadline:
        with database.session_factory()() as db:
            busy = db.query(models.Job).filter(models.Job.status.in_(["queued", "running"])).count()
        if not busy:
            return client.get(f"/api/files/{file_id}").json()
        time.sleep(0.1)
    raise AssertionError("очередь не опустела")


def files_dir_listing(file_id: int) -> list[str]:
    folder = get_settings().files_dir / f"{file_id:06d}"
    return sorted(p.name for p in folder.iterdir())


def kept_original(file_id: int, ext: str) -> Path:
    return get_settings().originals_dir / f"{file_id:06d}" / f"original.{ext}"


# --- подмена файла ------------------------------------------------------------------------------------


def test_a_png_is_compressed_silently_and_the_original_is_kept(api):
    original = png()
    file = upload(api, original, "screen.png").json()["file"]
    assert file["compression"]["state"] is None  # сразу после загрузки файл — как загрузили
    done = compressed(api, file["id"])

    assert done["compression"]["state"] == "done"
    assert done["size_bytes"] < len(original) * 0.7
    assert done["compression"]["original_size_bytes"] == len(original)
    assert done["compression"]["can_restore"] and done["compression"]["original_until"]
    assert done["sha256"] == hashlib.sha256(original).hexdigest()  # дубли ищутся по оригиналу
    assert (done["width"], done["height"]) == (1000, 600)  # разрешение не меняется

    served = api.get(done["urls"]["original"])
    assert served.status_code == 200 and len(served.content) == done["size_bytes"]
    assert Image.open(io.BytesIO(served.content)).size == (1000, 600)
    assert kept_original(file["id"], "png").read_bytes() == original  # оригинал бит в бит
    assert files_dir_listing(file["id"]) == ["original.png"]


def test_a_jpeg_is_recompressed_and_keeps_its_size_in_pixels(api):
    original = jpeg()
    file = upload(api, original, "camera.jpg").json()["file"]
    done = compressed(api, file["id"])
    assert done["compression"]["state"] == "done" and done["size_bytes"] < len(original) * 0.9
    assert (done["width"], done["height"]) == (800, 533)
    assert done["mime"] == "image/jpeg" and done["original_name"] == "camera.jpg"


def test_a_jpeg_extension_is_kept_after_compression(api):
    original = jpeg()
    file = upload(api, original, "camera.jpeg").json()["file"]
    done = compressed(api, file["id"])
    assert done["compression"]["state"] == "done" and done["original_name"] == "camera.jpeg"
    assert files_dir_listing(file["id"]) == ["original.jpeg"]
    assert kept_original(file["id"], "jpeg").read_bytes() == original


def test_the_same_original_is_still_a_duplicate_after_compression(api):
    original = png()
    first = upload(api, original, "screen.png").json()["file"]
    compressed(api, first["id"])
    again = upload(api, original, "screen-copy.png")
    assert again.status_code == 409 and again.json()["duplicate"]["file_id"] == first["id"]


def test_without_a_noticeable_gain_the_original_stays_untouched(api):
    original = jpeg(quality=55, optimize=True, progressive=True)
    file = upload(api, original, "low.jpg").json()["file"]
    done = compressed(api, file["id"])
    assert done["compression"]["state"] == "small_gain"
    assert done["size_bytes"] == len(original) and not done["compression"]["can_restore"]
    assert on_disk_bytes(file["id"], "jpg") == original
    assert not get_settings().originals_dir.exists() or not list(
        get_settings().originals_dir.rglob("*.jpg")
    )


def on_disk_bytes(file_id: int, ext: str) -> bytes:
    return (get_settings().files_dir / f"{file_id:06d}" / f"original.{ext}").read_bytes()


def test_no_compress_keeps_the_file_bit_for_bit(api):
    original = png()
    file = upload(api, original, "master.png", no_compress=True).json()["file"]
    done = settled(api, file["id"])
    assert done["compression"]["state"] is None and done["compression"]["no_compress"] is True
    assert on_disk_bytes(file["id"], "png") == original and done["size_bytes"] == len(original)
    with database.session_factory()() as db:
        assert db.query(models.Job).filter(models.Job.type == "compress").count() == 0


def test_webp_gif_and_other_formats_are_not_queued(api):
    buffer = io.BytesIO()
    photo().save(buffer, "WEBP")
    file = upload(api, buffer.getvalue(), "pic.webp").json()["file"]
    done = settled(api, file["id"])
    assert done["compression"]["state"] is None
    with database.session_factory()() as db:
        assert db.query(models.Job).filter(models.Job.type == "compress").count() == 0


def test_compression_can_be_switched_off(api, monkeypatch):
    monkeypatch.setenv("COMPRESS_IMAGES", "false")
    get_settings.cache_clear()
    file = upload(api, png(), "off.png").json()["file"]
    assert settled(api, file["id"])["compression"]["state"] is None


def test_a_heic_photo_becomes_a_jpg_and_can_be_restored(api):
    buffer = io.BytesIO()
    photo().save(buffer, "HEIF")
    heic = buffer.getvalue()
    file = upload(api, heic, "IMG_0001.HEIC").json()["file"]
    done = compressed(api, file["id"])
    assert (done["original_name"], done["mime"]) == ("IMG_0001.jpg", "image/jpeg")
    assert files_dir_listing(file["id"]) == ["original.jpg"]  # прежний .heic убран после коммита
    assert Image.open(io.BytesIO(api.get(done["urls"]["original"]).content)).format == "JPEG"

    restored = api.post(f"/api/files/{file['id']}/restore-original")
    assert restored.status_code == 200, restored.text
    back = restored.json()
    assert back["original_name"] == "IMG_0001.heic" and back["mime"] == "image/heic"
    assert back["size_bytes"] == len(heic) and back["compression"]["state"] is None
    assert back["compression"]["no_compress"] is True  # второй раз не жмём
    assert files_dir_listing(file["id"]) == ["original.heic"]
    assert on_disk_bytes(file["id"], "heic") == heic
    assert not kept_original(file["id"], "heic").exists()


def test_restoring_the_original_is_logged_and_the_file_is_not_compressed_again(api):
    original = png()
    file = upload(api, original, "screen.png").json()["file"]
    compressed(api, file["id"])
    assert api.post(f"/api/files/{file['id']}/restore-original").status_code == 200
    settled(api, file["id"])
    assert on_disk_bytes(file["id"], "png") == original
    with database.session_factory()() as db:
        logged = db.query(models.Activity).filter_by(action="restore_original").one()
        assert logged.entity_id == file["id"] and logged.actor_id


# --- права, срок хранения, уборка -------------------------------------------------------------------------


def test_only_the_author_the_director_and_the_owner_can_restore(api):
    login(api, "team", "Лена")
    file = upload(api, png(), "mine.png").json()["file"]
    compressed(api, file["id"])

    login(api, "team", "Игорь")
    assert api.post(f"/api/files/{file['id']}/restore-original").status_code == 403
    login(api, "guest", "Гость")
    assert api.post(f"/api/files/{file['id']}/restore-original").status_code == 403
    login(api, "director", "Мария")
    assert api.post(f"/api/files/{file['id']}/restore-original").status_code == 200


def test_the_original_is_deleted_after_seven_days_but_the_saving_stays(api):
    file = upload(api, png(), "old.png").json()["file"]
    done = compressed(api, file["id"])
    saved = done["compression"]["original_size_bytes"] - done["size_bytes"]
    settings = get_settings()

    assert compression.cleanup_expired(settings, utcnow() + timedelta(days=6)) == 0
    assert kept_original(file["id"], "png").exists()
    assert compression.cleanup_expired(settings, utcnow() + timedelta(days=8)) == 1
    assert not kept_original(file["id"], "png").exists()

    after = api.get(f"/api/files/{file['id']}").json()
    assert after["compression"]["can_restore"] is False
    assert after["compression"]["original_size_bytes"] == done["compression"]["original_size_bytes"]
    assert api.post(f"/api/files/{file['id']}/restore-original").status_code == 422
    with database.session_factory()() as db:
        project = db.query(models.Project).one()
        assert metrics.compression_savings(db, project.id)["saved_bytes"] == saved


def test_a_missing_original_on_disk_is_reported_not_pretended(api):
    file = upload(api, png(), "lost.png").json()["file"]
    compressed(api, file["id"])
    kept_original(file["id"], "png").unlink()
    assert api.post(f"/api/files/{file['id']}/restore-original").status_code == 422
    assert api.get(f"/api/files/{file['id']}").json()["compression"]["can_restore"] is False


def test_restoring_a_file_that_was_never_compressed_is_refused(api):
    file = upload(api, png(), "plain.png", no_compress=True).json()["file"]
    assert api.post(f"/api/files/{file['id']}/restore-original").status_code == 422


# --- экономия, здоровье, место на диске -------------------------------------------------------------------


def test_the_saving_shows_up_on_the_dashboard_the_library_and_in_the_disk_usage(api):
    from app import storage

    before = storage.used_bytes(get_settings(), fresh=True)
    original = png()
    file = upload(api, original, "tile.png").json()["file"]
    done = compressed(api, file["id"])
    saved = len(original) - done["size_bytes"]

    dashboard = api.get("/api/dashboard").json()["media"]
    assert (dashboard["compressed_files"], dashboard["saved_bytes"]) == (1, saved)
    library = api.get("/api/library").json()["compression"]
    assert library == {"files": 1, "saved_bytes": saved}
    # Оригинал лежит ещё 7 дней и занимает место наравне с сжатым: диск считает и то и другое.
    used = storage.used_bytes(get_settings(), fresh=True) - before
    assert used >= len(original) + done["size_bytes"] - 1024


def test_health_says_what_the_images_are_compressed_with(api):
    state = api.get("/api/health").json()["image_compression"]
    assert state["enabled"] is True and state["oxipng"] is True
    assert set(state) == {"enabled", "pngquant", "oxipng", "mozjpeg"}


def test_a_new_version_is_compressed_as_well(api):
    first = upload(api, png(), "v1.png", no_compress=True).json()["file"]
    settled(api, first["id"])
    second = upload(
        api, png(Image.new("RGB", (1000, 600), (200, 100, 50))), "v2.png", version_of=first["id"]
    )
    assert second.status_code == 201, second.text
    done = compressed(api, second.json()["file"]["id"])
    assert done["compression"]["state"] in ("done", "small_gain") and done["version_no"] == 2


# --- по одному и без гонок -------------------------------------------------------------------------------


def test_compression_runs_one_at_a_time(api):
    with database.session_factory()() as db:
        jobs.enqueue(db, JobType.COMPRESS, {"file_id": 999_001})
        jobs.enqueue(db, JobType.COMPRESS, {"file_id": 999_002})
        db.commit()
    # Фоновый воркер приложения мог успеть забрать их: проверяем на тех, что ещё в очереди.
    with database.session_factory()() as db:
        queued = db.query(models.Job).filter_by(type="compress", status="queued").count()
    if queued < 2:
        pytest.skip("воркер приложения уже разобрал задачи")
    first = worker.claim_next_id()
    assert first is not None and worker.busy_types() == ("compress",)
    assert worker.claim_next_id(worker.busy_types()) is None  # вторая ждёт, пока идёт первая
    worker.process_job(first)  # файла 999001 нет: задача просто завершается
    assert worker.busy_types() == ()
    second = worker.claim_next_id(worker.busy_types())
    assert second is not None and worker.busy_types() == ("compress",)
    worker.process_job(second)
    assert worker.busy_types() == ()  # ничего не осталось занятым для следующих тестов


def test_a_result_for_a_file_that_was_deleted_meanwhile_is_discarded(api):
    from app import imagecompress

    file = upload(api, png(), "gone.png", no_compress=True).json()["file"]
    settled(api, file["id"])
    settings = get_settings()
    work = settings.cache_dir / "x"
    work.mkdir(parents=True, exist_ok=True)
    out = work / "result.png"
    out.write_bytes(b"compressed")
    result = imagecompress.Result("done", out, "png", "image/png")
    assert api.delete(f"/api/files/{file['id']}").status_code == 204
    with database.session_factory()() as db:
        replaced = compression.apply(
            db, file["id"], result, f"{file['id']:06d}/original.png", settings
        )
        db.commit()
    assert replaced.leftover is None and not out.exists()
    assert on_disk_bytes(file["id"], "png") != b"compressed"
