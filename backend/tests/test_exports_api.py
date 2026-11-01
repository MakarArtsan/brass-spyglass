"""Экспорт через API: предпросмотр таймлайна, фоновая сборка, скачивание, права, срок хранения."""

import io
import subprocess
import time
import zipfile
from datetime import timedelta

import pytest

from app import storage
from app.config import get_settings
from app.db import utcnow
from app.services import exports
from tests.conftest import login
from tests.test_files import upload, wait_for


@pytest.fixture(scope="module")
def clips(tmp_path_factory) -> dict[str, bytes]:
    root = tmp_path_factory.mktemp("exp")
    out = {}
    for name, seconds in (("a.mp4", 2), ("b.mp4", 3)):
        path = root / name
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=24:duration={seconds}",
             "-f", "lavfi", "-i", f"sine=frequency={200 + seconds * 50}:duration={seconds}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
            check=True,
        )  # fmt: skip
        out[name] = path.read_bytes()
    return out


@pytest.fixture
def api(seeded_client):
    login(seeded_client, "owner", "Артём")
    return seeded_client


def ready_scene(api, clips, index: int, name: str) -> dict:
    """Сцена по порядку трекера: видео загружено, выбрано финальным, статус «Готово»."""
    scene = sorted(api.get("/api/scenes").json(), key=lambda s: s["order"])[index]
    data = upload(
        api, clips[name], name, entity_type="scene", entity_id=scene["id"], purpose="final"
    )
    file_id = data.json()["file"]["id"]
    wait_for(api, file_id, ready=lambda f: not f["processing"] and f["duration_sec"])
    assert api.put(f"/api/scenes/{scene['id']}/final", json={"file_id": file_id}).status_code == 200
    assert api.patch(f"/api/scenes/{scene['id']}", json={"status": "done"}).status_code == 200
    return scene


def wait_export(api, export_id: int, timeout: float = 150) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        item = next(e for e in api.get("/api/exports").json() if e["id"] == export_id)
        if item["status"] in ("done", "failed"):
            return item
        time.sleep(0.2)
    raise AssertionError(f"экспорт {export_id} не завершился: {item}")


# --- что попадёт на таймлайн ----------------------------------------------------------------------


def test_the_preview_lists_ready_scenes_in_tracker_order_and_what_was_left_out(api, clips):
    first = ready_scene(api, clips, 1, "a.mp4")  # вторая по порядку
    second = ready_scene(api, clips, 0, "b.mp4")  # первая по порядку
    preview = api.get("/api/exports/preview").json()
    assert preview["ready"] == 2 and preview["placeholders"] == 0
    assert [c["scene_number"] for c in preview["clips"]] == [second["number"], first["number"]]
    assert [c["frames"] for c in preview["clips"]] == [72, 48]  # длина файлов в кадрах при 24 к/с
    assert preview["clips"][0]["timecode"] == "01:00:00:00"
    assert preview["clips"][1]["timecode"] == "01:00:03:00"
    assert len(preview["skipped"]) == 10 and "нет финального файла" in preview["skipped"][0]


def test_placeholders_close_the_gaps_and_the_timeline_keeps_its_planned_length(api, clips):
    ready_scene(api, clips, 0, "a.mp4")
    scenes = sorted(api.get("/api/scenes").json(), key=lambda s: s["order"])
    preview = api.get("/api/exports/preview", params={"placeholders": True}).json()
    assert preview["ready"] == 1 and preview["placeholders"] == 11
    expected = 2 + sum(s["planned_sec"] for s in scenes[1:])  # файл 2 с + планы остальных сцен
    assert preview["total_sec"] == pytest.approx(expected, abs=0.1)


def test_the_shots_level_uses_done_takes_inside_scenes(api, clips):
    shot = sorted(api.get("/api/shots").json(), key=lambda s: s["order"])[0]
    data = upload(
        api, clips["a.mp4"], "a.mp4", entity_type="shot", entity_id=shot["id"], purpose="take"
    )
    file_id = data.json()["file"]["id"]
    wait_for(api, file_id, ready=lambda f: not f["processing"] and f["duration_sec"])
    api.put(f"/api/shots/{shot['id']}/final", json={"file_id": file_id})
    api.patch(f"/api/shots/{shot['id']}", json={"status": "done"})
    preview = api.get("/api/exports/preview", params={"level": "shots"}).json()
    assert preview["ready"] == 1 and preview["clips"][0]["shot_code"] == shot["code"]


# --- сборка и скачивание --------------------------------------------------------------------------


def test_an_export_is_built_in_the_background_and_downloads_as_a_zip(api, clips):
    ready_scene(api, clips, 0, "a.mp4")
    ready_scene(api, clips, 1, "b.mp4")
    created = api.post(
        "/api/exports",
        json={
            "target": "resolve",
            "level": "scenes",
            "placeholders": True,
            "media_root": "D:/BrassSpyglass",
        },
    )
    assert created.status_code == 201, created.text
    item = wait_export(api, created.json()["id"])
    assert item["status"] == "done", item
    assert item["available"] and item["download_url"]
    assert item["result"]["clips"] == 12 and item["result"]["placeholders"] == 10
    assert item["created_by"]["name"] == "Артём" and item["media_root"] == "D:/BrassSpyglass"

    download = api.get(item["download_url"])
    assert download.status_code == 200 and download.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(download.content)).namelist()
    assert {"timeline_fcp7.xml", "timeline.otio", "subtitles_en.srt", "README.txt"} <= set(names)
    assert sum(n.startswith("Media/Scenes/") for n in names) == 2
    assert sum(n.startswith("Media/Placeholders/") for n in names) == 10


def test_the_export_is_written_to_the_journal(api, clips):
    ready_scene(api, clips, 0, "a.mp4")
    api.post("/api/exports", json={"target": "premiere"})
    actions = [a["action"] for a in api.get("/api/activity").json()["items"]]
    assert "export" in actions


def test_an_empty_timeline_fails_with_a_clear_message(api):
    created = api.post("/api/exports", json={"target": "resolve"}).json()
    item = wait_export(api, created["id"])
    assert item["status"] == "failed" and "нечего собирать" in item["error"]
    assert item["download_url"] is None


def test_a_missing_original_fails_the_export_instead_of_producing_a_broken_package(api, clips):
    scene = ready_scene(api, clips, 0, "a.mp4")
    file_id = api.get("/api/scenes").json()[0]["final"]["id"] if scene else 0
    for path in get_settings().files_dir.glob(f"{file_id:06d}/original*"):
        path.unlink()
    item = wait_export(api, api.post("/api/exports", json={"target": "resolve"}).json()["id"])
    assert item["status"] == "failed" and "нет на диске" in item["error"]


def test_a_full_disk_stops_the_export(api, clips, monkeypatch):
    ready_scene(api, clips, 0, "a.mp4")

    def full(*_args, **_kwargs):
        raise storage.NoRoom("На диске не хватает места: свободно 0.0 ГБ")

    monkeypatch.setattr(storage, "ensure_room", full)
    item = wait_export(api, api.post("/api/exports", json={"target": "resolve"}).json()["id"])
    assert item["status"] == "failed" and "не хватает места" in item["error"]


def test_a_package_is_kept_for_seven_days_then_removed(api, clips):
    ready_scene(api, clips, 0, "a.mp4")
    item = wait_export(api, api.post("/api/exports", json={"target": "resolve"}).json()["id"])
    stored = list(get_settings().exports_dir.glob("*.zip"))
    assert len(stored) == 1
    assert (
        exports.cleanup(get_settings(), now=utcnow() + timedelta(days=exports.KEEP_DAYS - 1)) == 0
    )
    assert stored[0].exists()
    assert (
        exports.cleanup(get_settings(), now=utcnow() + timedelta(days=exports.KEEP_DAYS + 1)) == 1
    )
    assert not stored[0].exists()
    after = next(e for e in api.get("/api/exports").json() if e["id"] == item["id"])
    assert after["expired"] and not after["available"]
    assert api.get(f"/api/exports/{item['id']}/download").status_code == 410


def test_cleanup_leaves_a_fresh_half_built_package_alone(api):
    settings = get_settings()
    fresh = settings.exports_dir / "export-running"
    fresh.mkdir(parents=True, exist_ok=True)
    exports.cleanup(settings)
    assert fresh.exists()  # идущая сборка не должна пострадать


# --- права и проверка параметров ----------------------------------------------------------------


def test_a_guest_has_no_export(api):
    login(api, "guest", "Гость")
    assert api.get("/api/exports").status_code == 403
    assert api.get("/api/exports/preview").status_code == 403
    assert api.post("/api/exports", json={"target": "resolve"}).status_code == 403


def test_the_team_role_can_export(api, clips):
    ready_scene(api, clips, 0, "a.mp4")
    login(api, "team", "Дина")
    created = api.post("/api/exports", json={"target": "premiere", "placeholders": True})
    assert created.status_code == 201
    assert wait_export(api, created.json()["id"])["status"] == "done"


@pytest.mark.parametrize(
    "body",
    [
        {"target": "avid"},
        {"target": "resolve", "level": "frames"},
        {"target": "resolve", "media_root": "x" * 300},
        {"target": "resolve", "extra": 1},
    ],
)
def test_bad_parameters_are_refused(api, body):
    assert api.post("/api/exports", json=body).status_code == 422


def test_a_download_of_a_foreign_origin_post_is_blocked(api):
    response = api.post(
        "/api/exports", json={"target": "resolve"}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
