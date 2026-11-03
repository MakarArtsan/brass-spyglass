"""Сжатие картинок: чистые функции `imagecompress` на настоящих файлах и настоящих кодировщиках.

Тесты с pngquant и cjpeg пропускаются там, где их нет (машина без них); запасной путь на Pillow
проверяется всегда.
"""

import io
import random
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageCms, ImageDraw, ImageFilter, ImageStat

from app import imagecompress as ic
from app.media import MediaError

FALLBACK = ic.Tools(pngquant=None, cjpeg=None, oxipng=True)
REAL = ic.Tools(pngquant=shutil.which("pngquant"), cjpeg=shutil.which("cjpeg"), oxipng=True)
needs_pngquant = pytest.mark.skipif(REAL.pngquant is None, reason="нет pngquant")
needs_cjpeg = pytest.mark.skipif(REAL.cjpeg is None, reason="нет cjpeg")


def photo(size=(800, 533)) -> Image.Image:
    """Похоже на фото: плавные переходы плюс мелкий шум."""
    noise = Image.effect_noise(size, 18).convert("RGB").filter(ImageFilter.GaussianBlur(1))
    ramp = (
        Image.linear_gradient("L").resize(size).convert("RGB").filter(ImageFilter.GaussianBlur(3))
    )
    return Image.blend(ramp, noise, 0.25)


def screenshot(size=(1000, 600)) -> Image.Image:
    rng = random.Random(7)
    image = Image.new("RGB", size, (24, 28, 38))
    draw = ImageDraw.Draw(image)
    for i in range(30):
        x, y = rng.randint(0, size[0] - 220), rng.randint(0, size[1] - 120)
        draw.rectangle(
            [x, y, x + 200, y + 100], outline=(200, 180, 90), width=3, fill=(40 + i,) * 3
        )
        draw.text((x + 8, y + 8), f"Brass Spyglass {i}", fill=(240, 240, 240))
    return image


def save(image: Image.Image, path: Path, **options) -> Path:
    image.save(path, **options)
    return path


def diff(a: Image.Image, b: Image.Image) -> float:
    """Средняя абсолютная разница по каналам (0–255)."""
    return sum(ImageStat.Stat(ImageChops.difference(a.convert("RGB"), b.convert("RGB"))).mean) / 3


def out_image(result: ic.Result) -> Image.Image:
    assert result.output is not None
    return Image.open(result.output)


# --- JPEG ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("tools", [REAL, FALLBACK], ids=["real", "fallback"])
def test_a_high_quality_jpeg_gets_much_smaller_and_looks_the_same(tmp_path, tools):
    if tools is REAL and REAL.cjpeg is None:
        pytest.skip("нет cjpeg")
    src = save(photo(), tmp_path / "a.jpg", quality=96, subsampling=0)
    result = ic.compress(src, "jpg", tmp_path / "w", tools)
    assert result.state == "done" and (result.ext, result.mime) == ("jpg", "image/jpeg")
    assert result.output.stat().st_size < src.stat().st_size * 0.9
    image = out_image(result)
    assert image.format == "JPEG" and image.size == (800, 533)  # разрешение не меняется
    assert image.info.get("progressive") or image.info.get("progression")
    assert diff(Image.open(src), image) < 3  # на глаз разницы нет


def test_a_small_gain_keeps_the_original(tmp_path):
    # Уже сильно пережатый JPEG: перекодирование на quality 84 больше не даёт 10%.
    src = save(photo(), tmp_path / "low.jpg", quality=60, optimize=True, progressive=True)
    result = ic.compress(src, "jpg", tmp_path / "w", FALLBACK)
    assert result.state == "small_gain" and result.output is None
    assert not (tmp_path / "w" / "result.jpg").exists()


def test_exif_rotation_is_applied_to_pixels_and_exif_with_gps_is_dropped(tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 6  # повернуть на 90° по часовой при показе
    exif[0x010F] = "Камера"
    exif.get_ifd(0x8825)[1] = "N"  # GPS: широта-референс
    src = save(photo((800, 400)), tmp_path / "r.jpg", quality=96, subsampling=0, exif=exif)
    assert Image.open(src).getexif().get(0x0112) == 6

    result = ic.compress(src, "jpg", tmp_path / "w", FALLBACK)
    assert result.state == "done"
    image = out_image(result)
    assert image.size == (400, 800)  # поворот применён к пикселям
    assert not image.getexif()  # EXIF (в том числе GPS) не остался
    assert b"Exif" not in result.output.read_bytes()[:64]


@needs_cjpeg
def test_the_icc_profile_survives_in_jpeg(tmp_path):
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    src = save(photo(), tmp_path / "p.jpg", quality=96, subsampling=0, icc_profile=profile)
    for tools in (REAL, FALLBACK):
        result = ic.compress(src, "jpg", tmp_path / f"w{bool(tools.cjpeg)}", tools)
        assert result.state == "done"
        assert out_image(result).info.get("icc_profile") == profile


def test_a_cmyk_jpeg_is_left_alone(tmp_path):
    src = save(photo().convert("CMYK"), tmp_path / "c.jpg", quality=96)
    assert ic.compress(src, "jpg", tmp_path / "w", FALLBACK).state == "skipped"


def test_a_grayscale_jpeg_stays_grayscale(tmp_path):
    src = save(photo().convert("L"), tmp_path / "g.jpg", quality=96)
    for tools in (REAL, FALLBACK):
        if tools.cjpeg is None and tools is REAL:
            continue
        result = ic.compress(src, "jpg", tmp_path / f"w{bool(tools.cjpeg)}", tools)
        assert result.state == "done" and out_image(result).mode == "L"


# --- PNG ----------------------------------------------------------------------------------------


@needs_pngquant
def test_a_png_screenshot_loses_most_of_its_weight_without_visible_change(tmp_path):
    src = save(screenshot(), tmp_path / "s.png")
    result = ic.compress(src, "png", tmp_path / "w", REAL)
    assert result.state == "done" and result.ext == "png"
    assert result.output.stat().st_size < src.stat().st_size * 0.7
    assert diff(Image.open(src), out_image(result)) < 3


@needs_pngquant
def test_png_transparency_is_preserved(tmp_path):
    base = photo().convert("RGBA")
    base.putalpha(Image.linear_gradient("L").resize(base.size))
    src = save(base, tmp_path / "t.png")
    result = ic.compress(src, "png", tmp_path / "w", REAL)
    assert result.state == "done"
    image = out_image(result).convert("RGBA")
    assert (
        image.getchannel("A").getpixel((10, 0)) < 10
        and image.getchannel("A").getpixel((10, 530)) > 245
    )


def test_without_pngquant_a_png_is_only_optimized_losslessly(tmp_path):
    src = save(
        screenshot(), tmp_path / "s.png", compress_level=1
    )  # слабо упакован: есть что убрать
    result = ic.compress(src, "png", tmp_path / "w", FALLBACK)
    assert result.state == "done"
    assert (
        ImageChops.difference(
            Image.open(src).convert("RGB"), out_image(result).convert("RGB")
        ).getbbox()
        is None
    )


def test_a_png_with_a_foreign_profile_is_not_quantized(tmp_path):
    # Профиль не sRGB: квантование (оно переводит в sRGB) сдвинуло бы цвета, поэтому только lossless
    # с сохранением профиля.
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    src = save(screenshot(), tmp_path / "p.png", icc_profile=profile, compress_level=1)
    result = ic.compress(src, "png", tmp_path / "w", REAL)
    assert result.state == "done"
    image = out_image(result)
    assert image.info.get("icc_profile") == profile
    assert (
        ImageChops.difference(Image.open(src).convert("RGB"), image.convert("RGB")).getbbox()
        is None
    )


def test_a_16_bit_png_is_never_quantized(tmp_path):
    gradient = Image.new("I;16", (512, 64))
    gradient.putdata([x * 128 for x in range(512)] * 64)
    src = save(gradient, tmp_path / "d.png", compress_level=1)
    result = ic.compress(src, "png", tmp_path / "w", REAL)
    if result.state == "done":
        assert out_image(result).tobytes() == Image.open(src).tobytes()  # ни бита потерь


def test_an_animated_png_is_left_alone(tmp_path):
    frames = [Image.new("RGB", (64, 64), (i * 40, 0, 0)) for i in range(4)]
    src = tmp_path / "anim.png"
    frames[0].save(src, save_all=True, append_images=frames[1:], duration=100, loop=0)
    assert ic.png_facts(src.read_bytes())[0] is True
    assert ic.compress(src, "png", tmp_path / "w", FALLBACK).state == "skipped"


# --- форматы, которые не трогаем, и те, что конвертируем -------------------------------------------


@pytest.mark.parametrize("ext", ["webp", "avif", "gif", "pdf", "mp4"])
def test_already_compressed_or_animated_formats_are_skipped(tmp_path, ext):
    src = tmp_path / f"x.{ext}"
    src.write_bytes(b"not read at all")
    assert ic.compress(src, ext, tmp_path / "w", FALLBACK).state == "skipped"
    assert not ic.can_compress(ext)


@pytest.mark.parametrize("ext", ["bmp", "tif", "tiff"])
def test_bmp_and_tiff_become_jpeg(tmp_path, ext):
    src = save(photo(), tmp_path / f"s.{ext}")
    result = ic.compress(src, ext, tmp_path / "w", FALLBACK)
    assert result.state == "done" and result.ext == "jpg"
    assert out_image(result).format == "JPEG" and out_image(result).size == (800, 533)
    assert result.output.stat().st_size < src.stat().st_size * 0.3


def test_a_tiff_with_transparency_becomes_png_not_jpeg(tmp_path):
    # (у обычного BMP канала прозрачности нет: четвёртый байт пикселя там не используется)
    image = photo().convert("RGBA")
    image.putalpha(Image.linear_gradient("L").resize(image.size))
    src = save(image, tmp_path / "a.tiff")
    result = ic.compress(src, "tiff", tmp_path / "w", FALLBACK)
    assert result.ext == "png" and result.mime == "image/png"
    assert out_image(result).convert("RGBA").getchannel("A").getpixel((10, 0)) < 10


def test_heic_becomes_jpeg(tmp_path):
    import pillow_heif

    pillow_heif.register_heif_opener()
    src = save(photo(), tmp_path / "i.heic", format="HEIF")
    result = ic.compress(src, "heic", tmp_path / "w", FALLBACK)
    assert result.state == "done" and result.ext == "jpg"
    assert out_image(result).size == (800, 533)


def test_conversion_is_accepted_even_if_the_file_does_not_shrink(tmp_path):
    # Конвертируем ради совместимости с монтажками, а не ради веса: правило «10%» тут не работает.
    tiny = save(Image.new("RGB", (8, 8), (10, 20, 30)), tmp_path / "t.bmp")
    result = ic.compress(tiny, "bmp", tmp_path / "w", FALLBACK)
    assert result.state == "done" and result.ext == "jpg"


# --- ошибки и инструменты ----------------------------------------------------------------------------


def test_a_broken_file_is_reported_not_silently_kept(tmp_path):
    src = tmp_path / "broken.jpg"
    src.write_bytes(b"\xff\xd8\xff garbage")
    with pytest.raises(MediaError):
        ic.compress(src, "jpg", tmp_path / "w", FALLBACK)


def test_a_failing_encoder_raises_media_error(tmp_path):
    bad = ic.Tools(pngquant=None, cjpeg="/bin/false", oxipng=True)
    src = save(photo(), tmp_path / "a.jpg", quality=96)
    with pytest.raises(MediaError):
        ic.compress(src, "jpg", tmp_path / "w", bad)


def test_tools_follow_the_settings(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("PNGQUANT_BIN", "definitely-not-installed")
    monkeypatch.setenv("CJPEG_BIN", "/nowhere/cjpeg")
    get_settings.cache_clear()
    tools = ic.detect_tools()
    assert tools.pngquant is None and tools.cjpeg is None and tools.oxipng is True


def test_png_facts_reads_depth_and_animation(tmp_path):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, "PNG")
    assert ic.png_facts(buffer.getvalue()) == (False, 8)
    deep = io.BytesIO()
    Image.new("I;16", (4, 4)).save(deep, "PNG")
    assert ic.png_facts(deep.getvalue()) == (False, 16)
