"""Форматы картинок: jfif, jpe, avif, bmp, tiff принимаются, превью делается; jfif и jpe лежат как .jpg."""

import io
import os
from pathlib import Path

import pytest
from PIL import Image

from tests.conftest import login
from tests.test_files import upload, wait_for


@pytest.fixture
def api(seeded_client):
    login(seeded_client, "owner", "Артём")
    return seeded_client


def encode(fmt: str, size=(320, 200), mode="RGB", **options) -> bytes:
    image = Image.new(mode, size, (200, 80, 40) if mode == "RGB" else 128)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


def stored_by_id(file_id: int) -> list[Path]:
    folder = Path(os.environ["DATA_DIR"]) / "files" / f"{file_id:06d}"
    return sorted(folder.iterdir())


@pytest.mark.parametrize(
    ("name", "fmt"),
    [
        ("scan.bmp", "BMP"),
        ("scan.tif", "TIFF"),
        ("scan.tiff", "TIFF"),
        ("render.avif", "AVIF"),
        ("camera.jfif", "JPEG"),
        ("camera.jpe", "JPEG"),
        ("CAMERA.JFIF", "JPEG"),
    ],
)
def test_new_image_formats_are_accepted_and_get_previews(api, name, fmt):
    data = encode(fmt)
    done = upload(api, data, name)
    assert done.status_code == 201, done.text
    file = done.json()["file"]
    assert file["kind"] == "image"
    ready = wait_for(api, file["id"])
    assert (ready["width"], ready["height"]) == (320, 200)
    assert ready["urls"]["thumb"] and ready["urls"]["preview"]
    preview = api.get(ready["urls"]["preview"])
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/jpeg"


@pytest.mark.parametrize(
    ("name", "saved_as"),
    [("camera.jfif", "camera.jpg"), ("camera.jpe", "camera.jpg"), ("CAMERA.JFIF", "CAMERA.jpg")],
)
def test_jfif_and_jpe_are_stored_as_jpg_without_touching_the_bytes(api, name, saved_as):
    data = encode("JPEG")
    file = upload(api, data, name).json()["file"]
    assert file["original_name"] == saved_as
    assert file["mime"] == "image/jpeg"
    (path,) = stored_by_id(file["id"])
    assert path.name == "original.jpg" and path.read_bytes() == data
    original = api.get(file["urls"]["original"])
    assert original.status_code == 200 and original.headers["content-type"] == "image/jpeg"


def test_unknown_image_format_is_still_refused(api):
    response = api.post("/api/uploads", json={"name": "layers.psd", "size": 10})
    assert response.status_code == 415


def test_a_16_bit_tiff_gets_a_normal_preview_not_a_white_one(api):
    gradient = Image.new("I;16", (256, 4))
    gradient.putdata([x * 256 for x in range(256)] * 4)
    buffer = io.BytesIO()
    gradient.save(buffer, format="TIFF")
    file = upload(api, buffer.getvalue(), "depth.tif").json()["file"]
    ready = wait_for(api, file["id"])
    preview = Image.open(io.BytesIO(api.get(ready["urls"]["preview"]).content)).convert("L")
    left, middle = preview.getpixel((2, 1)), preview.getpixel((128, 1))
    assert left < 20 and 100 < middle < 160  # градиент, а не сплошной белый
