"""Файлы: загрузка кусками с докачкой, обработка, дубли, подписанные ссылки, права."""

import subprocess
import time
from pathlib import Path

import pillow_heif
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import login

pillow_heif.register_heif_opener()  # нужен и для создания HEIC в фикстуре

PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 300]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory) -> dict[str, Path]:
    """Настоящие файлы разных форматов, сделанные один раз на модуль."""
    root = tmp_path_factory.mktemp("media")
    files = {
        name: root / name
        for name in ("clip.mp4", "prores.mov", "tone.wav", "still.png", "photo.heic", "doc.pdf")
    }
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=2", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(files["clip.mp4"]))  # fmt: skip
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=640x360:rate=24:duration=2",
        "-c:v",
        "prores_ks",
        str(files["prores.mov"]),
    )
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(files["tone.wav"]))
    Image.new("RGB", (3000, 2000), (200, 150, 40)).save(files["still.png"])
    Image.new("RGB", (1200, 800), (40, 150, 200)).save(files["photo.heic"], format="HEIF")
    files["doc.pdf"].write_bytes(PDF)
    return files


@pytest.fixture
def api(seeded_client):
    login(seeded_client, "owner", "Артём")
    return seeded_client


def upload(
    client: TestClient,
    path: Path | bytes,
    name: str | None = None,
    *,
    chunk: int = 64 * 1024,
    **complete,
):
    data = path if isinstance(path, bytes) else path.read_bytes()
    name = name or path.name  # type: ignore[union-attr]
    init = client.post("/api/uploads", json={"name": name, "size": len(data)})
    assert init.status_code == 201, init.text
    upload_id, offset = init.json()["id"], 0
    while offset < len(data):
        response = client.patch(
            f"/api/uploads/{upload_id}",
            content=data[offset : offset + chunk],
            headers={"Upload-Offset": str(offset)},
        )
        assert response.status_code == 200, response.text
        offset = response.json()["offset"]
    return client.post(f"/api/uploads/{upload_id}/complete", json=complete)


def wait_for(
    client: TestClient, file_id: int, ready=lambda f: not f["processing"], timeout: float = 30
):
    deadline = time.time() + timeout
    while time.time() < deadline:
        item = client.get(f"/api/files/{file_id}").json()
        if ready(item):
            return item
        time.sleep(0.1)
    raise AssertionError(f"файл {file_id} не обработан за {timeout} с: {item}")


def first_shot(client: TestClient, code: str = "01.01") -> dict:
    return next(s for s in client.get("/api/shots").json() if s["code"] == code)


# --- загрузка и докачка ------------------------------------------------------------------------------------


def test_chunked_upload_keeps_author_from_session_and_original_intact(api, media):
    me = api.get("/api/me").json()["user"]
    done = upload(api, media["still.png"], chunk=100_000)
    assert done.status_code == 201
    file = done.json()["file"]
    assert file["uploaded_by"]["id"] == me["id"] and file["uploaded_at"]
    assert (file["kind"], file["source"], file["original_name"]) == ("image", "upload", "still.png")
    stored = (
        Path(__import__("os").environ["DATA_DIR"]) / "files" / f"{file['id']:06d}" / "original.png"
    )
    assert stored.read_bytes() == media["still.png"].read_bytes()  # оригинал не менялся


def test_author_cannot_be_forged_by_the_client(api, media):
    data = media["still.png"].read_bytes()
    init = api.post("/api/uploads", json={"name": "x.png", "size": len(data), "uploaded_by": 99})
    assert init.status_code == 422
    assert api.patch("/api/files/1", json={"uploaded_by": 1}).status_code == 422


def test_resume_after_a_network_break(api, media):
    data = media["clip.mp4"].read_bytes()
    init = api.post("/api/uploads", json={"name": "clip.mp4", "size": len(data)}).json()
    upload_id, cut = init["id"], len(data) // 3
    assert api.patch(
        f"/api/uploads/{upload_id}", content=data[:cut], headers={"Upload-Offset": "0"}
    ).json() == {"offset": cut}

    # «Обрыв»: клиент не знает, дошёл ли последний кусок, и спрашивает сервер.
    assert api.get(f"/api/uploads/{upload_id}").json()["offset"] == cut
    stale = api.patch(
        f"/api/uploads/{upload_id}", content=data[:100], headers={"Upload-Offset": "0"}
    )
    assert stale.status_code == 409 and stale.headers["Upload-Offset"] == str(
        cut
    )  # повтор старого куска
    assert api.post(f"/api/uploads/{upload_id}/complete", json={}).status_code == 409  # ещё не всё
    api.patch(f"/api/uploads/{upload_id}", content=data[cut:], headers={"Upload-Offset": str(cut)})
    assert api.post(f"/api/uploads/{upload_id}/complete", json={}).status_code == 201


def test_upload_survives_an_app_restart(env, monkeypatch, media):
    from app.config import get_settings
    from app.main import create_app
    from tests.conftest import SEED_PATH

    monkeypatch.setenv("SEED_XLSX", str(SEED_PATH))
    get_settings.cache_clear()
    data = media["clip.mp4"].read_bytes()
    with TestClient(create_app()) as first:
        user = login(first, "owner", "Артём")
        upload_id = first.post("/api/uploads", json={"name": "clip.mp4", "size": len(data)}).json()[
            "id"
        ]
        first.patch(
            f"/api/uploads/{upload_id}", content=data[:5000], headers={"Upload-Offset": "0"}
        )
        cookie = first.cookies.get("bs_session")
    with TestClient(create_app()) as second:  # «контейнер перезапустили»
        second.cookies.set("bs_session", cookie)
        assert second.get(f"/api/uploads/{upload_id}").json()["offset"] == 5000
        second.patch(
            f"/api/uploads/{upload_id}", content=data[5000:], headers={"Upload-Offset": "5000"}
        )
        done = second.post(f"/api/uploads/{upload_id}/complete", json={})
        assert done.status_code == 201 and done.json()["file"]["uploaded_by"]["id"] == user.id


def test_chunk_size_comes_from_settings(api, monkeypatch):
    from app.config import get_settings

    assert (
        api.post("/api/uploads", json={"name": "a.png", "size": 10}).json()["chunk_size"]
        == 8 * 1024 * 1024
    )
    monkeypatch.setenv("UPLOAD_CHUNK_MB", "1")
    get_settings.cache_clear()
    assert (
        api.post("/api/uploads", json={"name": "b.png", "size": 10}).json()["chunk_size"]
        == 1024 * 1024
    )


def test_upload_validation(api, media):
    assert api.post("/api/uploads", json={"name": "virus.exe", "size": 10}).status_code == 415
    assert (
        api.post("/api/uploads", json={"name": "big.mp4", "size": 5 * 1024**3}).status_code == 413
    )  # лимит 4 ГБ
    assert api.post("/api/uploads", json={"name": "a.mp4", "size": 0}).status_code == 422
    upload_id = api.post("/api/uploads", json={"name": "a.png", "size": 10}).json()["id"]
    assert (
        api.patch(
            f"/api/uploads/{upload_id}", content=b"x" * 11, headers={"Upload-Offset": "0"}
        ).status_code
        == 422
    )
    assert (
        api.patch(
            f"/api/uploads/{'0' * 32}", content=b"x", headers={"Upload-Offset": "0"}
        ).status_code
        == 404
    )
    assert api.get("/api/uploads/..%2f..%2fetc%2fpasswd").status_code == 404  # обход каталога
    big = api.post("/api/uploads", json={"name": "b.png", "size": 20 * 1024 * 1024}).json()["id"]
    chunk = api.patch(
        f"/api/uploads/{big}", content=b"0" * (16 * 1024 * 1024 + 1), headers={"Upload-Offset": "0"}
    )
    assert chunk.status_code == 413  # кусок больше 16 МБ
    assert api.delete(f"/api/uploads/{big}").status_code == 204
    assert api.get(f"/api/uploads/{big}").status_code == 404


def test_someone_elses_upload_cannot_be_touched_and_guests_cannot_upload(seeded_client):
    login(seeded_client, "owner", "Артём")
    upload_id = seeded_client.post("/api/uploads", json={"name": "a.png", "size": 10}).json()["id"]
    login(seeded_client, "team", "Петя")
    assert seeded_client.get(f"/api/uploads/{upload_id}").status_code == 403
    assert (
        seeded_client.patch(
            f"/api/uploads/{upload_id}", content=b"x", headers={"Upload-Offset": "0"}
        ).status_code
        == 403
    )
    login(seeded_client, "guest", "Гость")
    assert seeded_client.post("/api/uploads", json={"name": "a.png", "size": 10}).status_code == 403


def test_stale_uploads_are_cleaned_up(api, env):
    import os

    from app import uploads
    from app.config import get_settings

    upload_id = api.post("/api/uploads", json={"name": "a.png", "size": 10}).json()["id"]
    part = uploads.part_path(get_settings(), upload_id)
    old = time.time() - 8 * 86400
    for path in part.parent.glob(f"{upload_id}.*"):
        os.utime(path, (old, old))
    assert uploads.cleanup_stale(get_settings()) == 2
    assert api.get(f"/api/uploads/{upload_id}").status_code == 404


# --- обработка -----------------------------------------------------------------------------------------------


def test_video_is_probed_and_gets_poster_and_thumb(api, media):
    file = upload(api, media["clip.mp4"]).json()["file"]
    ready = wait_for(api, file["id"])
    assert (ready["width"], ready["height"], ready["fps"]) == (640, 360, 24.0)
    assert ready["duration_sec"] == pytest.approx(2.0, abs=0.1)
    assert {"thumb", "poster", "play", "original"} <= set(ready["urls"])
    assert "/original?" in ready["urls"]["play"]  # H.264 браузер играет как есть — прокси не нужен
    thumb = api.get(ready["urls"]["thumb"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    with Image.open(__import__("io").BytesIO(thumb.content)) as image:
        assert max(image.size) <= 400


def test_prores_gets_an_h264_proxy_that_plays_with_range(api, media):
    file = upload(api, media["prores.mov"]).json()["file"]
    ready = wait_for(
        api, file["id"], ready=lambda f: not f["processing"] and "/proxy?" in f["urls"]["play"]
    )
    partial = api.get(ready["urls"]["play"], headers={"Range": "bytes=0-99"})
    assert partial.status_code == 206 and len(partial.content) == 100
    assert partial.headers["content-range"].startswith("bytes 0-99/")
    assert partial.headers["content-type"] == "video/mp4"
    # оригинал остаётся ProRes и скачивается как есть
    assert api.get(ready["urls"]["original"]).content == media["prores.mov"].read_bytes()


def test_png_and_heic_get_1600_and_400_previews(api, media):
    png = wait_for(api, upload(api, media["still.png"]).json()["file"]["id"])
    assert (png["width"], png["height"]) == (3000, 2000)
    for variant, limit in (("preview", 1600), ("thumb", 400)):
        response = api.get(png["urls"][variant])
        with Image.open(__import__("io").BytesIO(response.content)) as image:
            assert max(image.size) == limit
    heic = wait_for(api, upload(api, media["photo.heic"]).json()["file"]["id"])
    preview = api.get(heic["urls"]["preview"])  # HEIC в браузере не открыть — отдаём JPG
    assert preview.headers["content-type"] == "image/jpeg"


def test_audio_gets_duration_and_waveform(api, media):
    audio = wait_for(api, upload(api, media["tone.wav"]).json()["file"]["id"])
    assert audio["duration_sec"] == pytest.approx(3.0, abs=0.1) and "waveform" in audio["urls"]
    peaks = api.get(audio["urls"]["waveform"]).json()
    assert len(peaks) == 800 and max(peaks) == 1.0 and min(peaks) >= 0


def test_pdf_gets_a_first_page_preview(api, media):
    doc = wait_for(api, upload(api, media["doc.pdf"]).json()["file"]["id"])
    assert "preview" in doc["urls"] and api.get(doc["urls"]["preview"]).status_code == 200


def test_broken_file_reports_an_error_instead_of_hanging(api):
    broken = upload(api, "это совсем не видео".encode(), name="broken.mp4").json()["file"]
    failed = wait_for(api, broken["id"])
    assert failed["processing"] is False and failed["error"]
    assert api.get(failed["urls"]["original"]).status_code == 200  # оригинал при этом цел


def test_interrupted_jobs_return_to_the_queue_after_restart(db):
    from sqlalchemy import select

    from app import models
    from app.constants import JobStatus, JobType
    from app.services import jobs

    job = jobs.enqueue(db, JobType.PREVIEW, {"file_id": 1})
    job.status = JobStatus.RUNNING.value
    db.flush()
    assert jobs.requeue_interrupted(db) == 1
    assert (
        db.scalar(select(models.Job.status).where(models.Job.id == job.id))
        == JobStatus.QUEUED.value
    )


# --- дубли, привязки ------------------------------------------------------------------------------------------


def test_duplicate_is_caught_by_sha256_and_can_be_added_anyway(seeded_client, media):
    login(seeded_client, "team", "Петя")
    shot = first_shot(seeded_client, "04.02")
    first = upload(seeded_client, media["still.png"], entity_type="shot", entity_id=shot["id"])
    assert first.status_code == 201
    again = upload(seeded_client, media["still.png"], name="copy.png")
    assert again.status_code == 409
    info = again.json()["duplicate"]
    assert (info["uploaded_by"], info["original_name"], info["attached_to"]) == (
        "Петя",
        "still.png",
        ["шот 04.02"],
    )
    forced = upload(seeded_client, media["still.png"], name="copy.png", force=True)
    assert forced.status_code == 201 and forced.json()["file"]["id"] != first.json()["file"]["id"]


def test_upload_straight_into_a_card_and_takes_counter(api, media):
    shot = first_shot(api)
    done = upload(api, media["clip.mp4"], entity_type="shot", entity_id=shot["id"], purpose="take")
    file_id = done.json()["file"]["id"]
    wait_for(api, file_id)
    listed = api.get("/api/files", params={"entity_type": "shot", "entity_id": shot["id"]}).json()
    assert [(i["purpose"], i["file"]["id"], i["attached_by"]["name"]) for i in listed] == [
        ("take", file_id, "Артём")
    ]
    row = first_shot(api)
    assert row["takes_count"] == 1 and row["files_count"] == 1
    assert row["preview"]["file_id"] == file_id and row["preview"]["url"].startswith(
        f"/api/files/{file_id}/thumb"
    )

    other = first_shot(api, "01.02")  # тот же файл на другой карточке — без повторной загрузки
    bound = api.post(
        "/api/attachments",
        json={"file_id": file_id, "entity_type": "shot", "entity_id": other["id"]},
    )
    assert bound.status_code == 201
    assert (
        api.post(
            "/api/attachments",
            json={"file_id": file_id, "entity_type": "shot", "entity_id": other["id"]},
        ).status_code
        == 409
    )
    assert api.delete(f"/api/attachments/{listed[0]['attachment_id']}").status_code == 204
    assert first_shot(api)["takes_count"] == 0
    journal = [
        i["action"]
        for i in api.get(
            "/api/activity", params={"entity_type": "shot", "entity_id": shot["id"]}
        ).json()["items"]
    ]
    assert "attach" in journal and "detach" in journal


def test_upload_to_a_missing_card_is_refused_before_anything_is_stored(api, media):
    response = upload(api, media["still.png"], entity_type="shot", entity_id=999999)
    assert response.status_code == 404
    assert api.get("/api/files", params={"entity_type": "shot", "entity_id": 999999}).json() == []


# --- ссылки и доступ --------------------------------------------------------------------------------------------


def test_files_are_served_only_to_logged_in_users_by_signed_links(seeded_client, media):
    login(seeded_client, "owner", "Артём")
    file = upload(seeded_client, media["still.png"]).json()["file"]
    url = file["urls"]["original"]
    assert seeded_client.get(url).status_code == 200
    assert seeded_client.head(url).status_code == 200
    path, token = url.split("?t=")

    assert seeded_client.get(path).status_code == 403  # без подписи
    assert seeded_client.get(f"{path}?t={token}x").status_code == 403  # подделка
    assert (
        seeded_client.get(f"/api/files/{file['id']}/thumb?t={token}").status_code == 403
    )  # подпись от другого варианта
    seeded_client.cookies.clear()
    assert seeded_client.get(url).status_code == 401  # ссылка без входа не работает


def test_signed_links_expire(seeded_client, media, monkeypatch):
    from app.config import get_settings

    login(seeded_client, "owner", "Артём")
    file = upload(seeded_client, media["still.png"]).json()["file"]
    monkeypatch.setenv("FILE_LINK_TTL_SEC", "1")
    get_settings.cache_clear()
    time.sleep(2.1)
    assert seeded_client.get(file["urls"]["original"]).status_code == 403


def test_download_flag_and_utf8_name(api, media):
    file = upload(api, media["still.png"], name="Кадр зеркала.png").json()["file"]
    response = api.get(file["urls"]["original"] + "&download=true")
    assert response.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
    assert "%D0%9A%D0%B0%D0%B4%D1%80" in response.headers["content-disposition"]
    assert api.get(file["urls"]["original"]).headers["content-disposition"].startswith("inline")


def test_zip_of_a_card(api, media):
    shot = first_shot(api)
    upload(api, media["still.png"], entity_type="shot", entity_id=shot["id"])
    upload(api, media["clip.mp4"], entity_type="shot", entity_id=shot["id"], purpose="take")
    response = api.get(f"/api/entities/shot/{shot['id']}/zip")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    import io
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert sorted(names) == ["clip.mp4", "still.png"]
    assert api.get("/api/entities/shot/999999/zip").status_code == 404


# --- удаление и права ----------------------------------------------------------------------------------------------


def test_team_cannot_delete_a_foreign_file_even_by_direct_api_request(seeded_client, media):
    """Критерий приёмки ТЗ: «Команда» не может удалить чужой файл прямым запросом к API."""
    login(seeded_client, "team", "Вася")
    foreign = upload(seeded_client, media["still.png"]).json()["file"]
    login(seeded_client, "team", "Петя")
    assert seeded_client.delete(f"/api/files/{foreign['id']}").status_code == 403
    assert (
        seeded_client.patch(
            f"/api/files/{foreign['id']}", json={"original_name": "моё.png"}
        ).status_code
        == 403
    )
    assert seeded_client.get(f"/api/files/{foreign['id']}").json()["original_name"] == "still.png"
    assert seeded_client.get(foreign["urls"]["original"]).status_code == 200  # файл цел

    mine = upload(seeded_client, media["tone.wav"]).json()["file"]
    assert seeded_client.delete(f"/api/files/{mine['id']}").status_code == 204


def test_director_and_owner_delete_foreign_files_into_trash(seeded_client, media):
    login(seeded_client, "team", "Петя")
    first = upload(seeded_client, media["still.png"]).json()["file"]
    second = upload(seeded_client, media["tone.wav"]).json()["file"]
    login(seeded_client, "director", "Дина")
    assert seeded_client.delete(f"/api/files/{first['id']}").status_code == 204
    login(seeded_client, "owner", "Артём")
    assert seeded_client.delete(f"/api/files/{second['id']}").status_code == 204
    assert seeded_client.get(f"/api/files/{first['id']}").status_code == 404  # в корзине
    assert seeded_client.get(first["urls"]["original"]).status_code == 404


def test_deleted_file_disappears_from_the_card_and_takes_counter(api, media):
    shot = first_shot(api)
    file = upload(
        api, media["clip.mp4"], entity_type="shot", entity_id=shot["id"], purpose="take"
    ).json()["file"]
    assert first_shot(api)["files_count"] == 1
    assert api.delete(f"/api/files/{file['id']}").status_code == 204
    assert first_shot(api)["files_count"] == 0
    assert (
        api.get("/api/files", params={"entity_type": "shot", "entity_id": shot["id"]}).json() == []
    )


async def test_runner_survives_a_failure_while_claiming_a_job(db, monkeypatch):
    """Разовая ошибка базы не должна навсегда останавливать обработку файлов."""
    import asyncio

    from app import worker
    from app.constants import JobType
    from app.services import jobs

    real = worker.claim_next_id
    calls = {"n": 0}

    def flaky() -> int | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return real()

    monkeypatch.setattr(worker, "claim_next_id", flaky)
    monkeypatch.setattr(worker, "process_job", lambda job_id: None)
    job = jobs.enqueue(db, JobType.PREVIEW, {"file_id": 999999})
    db.commit()

    runner = worker.JobRunner()
    await runner.start()
    try:
        for _ in range(60):
            await asyncio.sleep(0.1)
            db.expire_all()
            if db.get(__import__("app.models", fromlist=["Job"]).Job, job.id).status == "running":
                break
        assert calls["n"] >= 2  # после ошибки цикл жив и взял задачу
    finally:
        await runner.stop()
