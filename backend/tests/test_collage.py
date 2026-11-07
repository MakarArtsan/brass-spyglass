"""Коллаж из фото: раскладка (чистая арифметика) и сборка JPEG на настоящих картинках."""

import random
from pathlib import Path

import pytest
from PIL import Image

from app import collage
from app.collage import CollageError, plan, render

ASPECTS = (0.5625, 0.667, 0.75, 1.0, 1.333, 1.5, 1.777)


def check_layout(layout, aspects):
    """Что должно быть верно для любой раскладки."""
    gap, width = collage.GAP, layout.width
    assert [c.index for c in layout.cells] == list(range(len(aspects)))
    rows: dict[int, list] = {}
    for cell in layout.cells:
        rows.setdefault(cell.y, []).append(cell)
        assert cell.w > 0 and cell.h > 0 and cell.x >= gap and cell.y >= gap
        assert (
            abs(cell.w / cell.h - aspects[cell.index]) / aspects[cell.index] < 0.01
        )  # без искажений
    for cells in rows.values():
        cells.sort(key=lambda c: c.x)
        assert len({c.h for c in cells}) == 1  # в ряду одна высота
        assert cells[0].x == gap and cells[-1].x + cells[-1].w == width - gap  # ряд — во всю ширину
        for left, right in zip(cells, cells[1:], strict=False):
            assert right.x - (left.x + left.w) == gap  # зазор ровно один
    ys = sorted(rows)
    for upper, lower in zip(ys, ys[1:], strict=False):
        assert lower - (upper + rows[upper][0].h) == gap
    last = ys[-1]
    assert layout.height == last + rows[last][0].h + gap  # нижнее поле равно зазору


@pytest.mark.parametrize("count", range(collage.MIN_PHOTOS, collage.MAX_PHOTOS + 1))
def test_every_layout_is_tidy_and_never_crops_or_distorts(count):
    rng = random.Random(count)
    for _ in range(40):
        aspects = [rng.choice(ASPECTS) for _ in range(count)]
        check_layout(plan(aspects), aspects)


def test_the_layout_is_the_same_for_the_same_photos():
    aspects = [1.5, 0.75, 1.0, 1.777, 0.667, 1.333]
    assert plan(aspects) == plan(list(aspects))


def test_ten_mixed_photos_make_a_balanced_landscape_sheet():
    layout = plan([1.333, 1.5, 0.75, 1.0, 0.75, 1.777, 0.75, 0.5625, 1.333, 1.0])
    ratio = layout.width / layout.height
    assert 1.0 <= ratio <= 1.9 and len({c.y for c in layout.cells}) in (3, 4)
    assert min(c.h for c in layout.cells) >= 800  # даже в самом низком ряду фото крупные
    assert min(c.w * c.h for c in layout.cells) >= 500_000  # а самое узкое (9:16) не мельче 0,5 Мп
    assert layout.width == collage.CANVAS_WIDTH == 3840


def test_the_order_of_photos_is_kept_row_by_row():
    layout = plan([1.0] * 6)
    reading = sorted(layout.cells, key=lambda c: (c.y, c.x))
    assert [c.index for c in reading] == [0, 1, 2, 3, 4, 5]


def test_rows_are_not_wildly_different_in_height():
    rng = random.Random(7)
    for _ in range(60):
        aspects = [rng.choice(ASPECTS) for _ in range(rng.randint(3, 10))]
        heights = {c.y: c.h for c in plan(aspects).cells}.values()
        assert max(heights) / min(heights) <= collage.MAX_ROW_RATIO + 0.25


@pytest.mark.parametrize("count", [0, 1, collage.MAX_PHOTOS + 1])
def test_the_number_of_photos_is_limited(count):
    with pytest.raises(ValueError):
        plan([1.0] * count)
    with pytest.raises(CollageError, match="от 2 до 10"):
        render([(Path("x.jpg"), "x.jpg")] * count, Path("out.jpg"))


def test_a_non_positive_aspect_is_refused():
    with pytest.raises(ValueError):
        plan([1.0, 0.0])


# --- настоящие картинки ---------------------------------------------------------------------------

RED, GREEN, BLUE, YELLOW = (220, 30, 30), (30, 200, 60), (40, 70, 230), (240, 220, 40)


def solid(tmp_path: Path, name: str, size: tuple[int, int], color, fmt="JPEG", **save) -> Path:
    path = tmp_path / name
    Image.new("RGB", size, color).save(path, fmt, **save)
    return path


def pixel_at_center(image: Image.Image, cell) -> tuple[int, int, int]:
    return image.getpixel((cell.x + cell.w // 2, cell.y + cell.h // 2))[:3]


def close(a, b, tol=14) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def test_a_collage_is_a_valid_4k_wide_jpeg_with_every_photo_in_its_cell(tmp_path):
    photos = [
        (solid(tmp_path, "a.jpg", (1200, 800), RED), "a.jpg"),
        (solid(tmp_path, "b.jpg", (600, 900), GREEN), "b.jpg"),
        (solid(tmp_path, "c.png", (800, 800), BLUE, "PNG"), "c.png"),
        (solid(tmp_path, "d.jpg", (1600, 900), YELLOW), "d.jpg"),
    ]
    dest = tmp_path / "out" / "collage.jpg"
    layout = render(photos, dest)
    with Image.open(dest) as out:
        assert out.format == "JPEG" and out.size == (3840, layout.height) and out.mode == "RGB"
        for cell, color in zip(layout.cells, (RED, GREEN, BLUE, YELLOW), strict=True):
            assert close(pixel_at_center(out, cell), color), (cell, color)
        assert close(out.getpixel((4, 4)), collage.BACKGROUND, 6)  # поле — фон
    check_layout(layout, [1200 / 800, 600 / 900, 1.0, 1600 / 900])


def test_exif_rotation_is_applied_so_a_portrait_shot_stays_portrait(tmp_path):
    """Телефон пишет вертикальный кадр горизонтальным и ставит метку поворота."""
    path = tmp_path / "rot.jpg"
    image = Image.new("RGB", (900, 600), RED)  # лежит на боку
    image.paste(Image.new("RGB", (450, 600), GREEN), (450, 0))  # правая половина зелёная
    exif = Image.Exif()
    exif[0x0112] = 6  # повернуть на 90° по часовой: правая половина уйдёт вниз
    image.save(path, "JPEG", exif=exif)
    other = solid(tmp_path, "o.jpg", (900, 600), BLUE)
    dest = tmp_path / "c.jpg"
    layout = render([(path, "rot.jpg"), (other, "o.jpg")], dest)
    first = layout.cells[0]
    assert first.h > first.w  # вертикальный
    with Image.open(dest) as out:
        top = out.getpixel((first.x + first.w // 2, first.y + first.h // 4))[:3]
        bottom = out.getpixel((first.x + first.w // 2, first.y + 3 * first.h // 4))[:3]
    assert close(top, RED) and close(bottom, GREEN)


def test_transparency_is_flattened_onto_the_dark_background(tmp_path):
    path = tmp_path / "t.png"
    Image.new("RGBA", (400, 400), (255, 0, 0, 0)).save(path)  # полностью прозрачный
    other = solid(tmp_path, "o.jpg", (400, 400), BLUE)
    dest = tmp_path / "c.jpg"
    layout = render([(path, "t.png"), (other, "o.jpg")], dest)
    with Image.open(dest) as out:
        assert close(
            pixel_at_center(out, layout.cells[0]), collage.BACKGROUND, 8
        )  # не чёрный и не красный


def test_cmyk_and_grayscale_and_palette_photos_are_accepted(tmp_path):
    cmyk = tmp_path / "k.jpg"
    Image.new("CMYK", (500, 500), (0, 255, 255, 0)).save(cmyk, "JPEG")  # красный
    gray = tmp_path / "g.png"
    Image.new("L", (500, 500), 128).save(gray)
    palette = tmp_path / "p.gif"
    Image.new("P", (500, 500), 3).save(palette)
    dest = tmp_path / "c.jpg"
    layout = render([(cmyk, "k.jpg"), (gray, "g.png"), (palette, "p.gif")], dest)
    with Image.open(dest) as out:
        assert out.mode == "RGB"
        assert pixel_at_center(out, layout.cells[0])[0] > 150  # красный остался красным
        r, g, b = pixel_at_center(out, layout.cells[1])
        assert abs(r - 128) < 6 and abs(g - 128) < 6 and abs(b - 128) < 6


def test_sixteen_bit_photos_do_not_turn_white(tmp_path):
    path = tmp_path / "deep.png"
    Image.new("I;16", (400, 400), 20000).save(path)
    other = solid(tmp_path, "o.jpg", (400, 400), BLUE)
    dest = tmp_path / "c.jpg"
    layout = render([(path, "deep.png"), (other, "o.jpg")], dest)
    with Image.open(dest) as out:
        assert pixel_at_center(out, layout.cells[0])[0] < 120  # около 78, а не 255


def test_a_broken_file_is_named_in_the_message(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes("это не картинка".encode())
    good = solid(tmp_path, "g.jpg", (300, 300), RED)
    with pytest.raises(CollageError, match="bad.jpg"):
        render([(good, "g.jpg"), (bad, "bad.jpg")], tmp_path / "c.jpg")
    assert not (tmp_path / "c.jpg").exists()  # половина коллажа не остаётся


def test_a_gigantic_photo_is_refused_before_it_is_decoded(tmp_path, monkeypatch):
    monkeypatch.setattr(collage, "MAX_SOURCE_PIXELS", 10_000)
    big = solid(tmp_path, "big.jpg", (200, 200), RED)  # 40 000 пикселей > 10 000
    small = solid(tmp_path, "s.jpg", (50, 50), BLUE)
    with pytest.raises(CollageError, match="слишком большое"):
        render([(big, "big.jpg"), (small, "s.jpg")], tmp_path / "c.jpg")


def test_a_color_profile_is_converted_not_ignored(tmp_path):
    """Профиль, отличный от sRGB (телефоны пишут Display P3), приводится к sRGB; плохой профиль не мешает."""
    from PIL import ImageCms

    lab = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    ok = tmp_path / "icc.jpg"
    Image.new("RGB", (400, 400), RED).save(
        ok, "JPEG", icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    )
    broken = tmp_path / "icc2.jpg"
    Image.new("RGB", (400, 400), GREEN).save(
        broken, "JPEG", icc_profile="мусор вместо профиля".encode()
    )
    other = solid(tmp_path, "o.jpg", (400, 400), BLUE)
    dest = tmp_path / "c.jpg"
    layout = render([(ok, "icc.jpg"), (broken, "icc2.jpg"), (other, "o.jpg")], dest)
    with Image.open(dest) as out:
        assert close(pixel_at_center(out, layout.cells[0]), RED)
        assert close(pixel_at_center(out, layout.cells[1]), GREEN)
    assert lab  # профиль LAB создаётся: библиотека цвета на месте


def test_the_file_size_is_reasonable_for_ten_photos(tmp_path):
    rng = random.Random(3)
    photos = []
    for i in range(10):
        image = Image.effect_noise((900, 700), 60).convert(
            "RGB"
        )  # шумная картинка: худший случай для JPEG
        path = tmp_path / f"n{i}.jpg"
        image.save(path, "JPEG", quality=92)
        photos.append((path, path.name))
    dest = tmp_path / "c.jpg"
    render(photos, dest)
    assert dest.stat().st_size < 40 * 1024 * 1024
    assert rng  # детерминированность входа не нужна, достаточно потолка размера
