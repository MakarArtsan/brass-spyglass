"""Сборка пакета для Resolve и Premiere: XML, OTIO, SRT, файлы и заглушки на настоящих видео."""

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import opentimelineio as otio
import pytest

from app import export_plan as ep
from app import exporter, media
from app.export_plan import CueX, FileRef, SceneX, ShotX
from app.exporter import Options, PackageSpec, Reference


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


@pytest.fixture(scope="module")
def library(tmp_path_factory) -> Path:
    """Папка «файлы проекта» с настоящими видео по 24 к/с: 2,0 с, 3,5 с и звук 1,5 с."""
    root = tmp_path_factory.mktemp("files")
    for name, seconds in (("000001/original.mp4", 2.0), ("000002/original.mp4", 3.5)):
        (root / name).parent.mkdir(parents=True)
        ffmpeg("-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=24:duration={seconds}",
               "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(root / name))  # fmt: skip
    (root / "000010").mkdir()
    ffmpeg(
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5", str(root / "000010/original.wav")
    )
    (root / "000020").mkdir()
    (root / "000020/original.png").write_bytes(b"\x89PNG-reference")
    return root


def spec_for(library: Path, tmp: Path, **options) -> PackageSpec:
    scenes = [
        SceneX(
            1, 1, "Два зеркала", 2, "done", 2.0, FileRef(1, "000001/original.mp4", "a.mp4", 3, 2.0)
        ),
        SceneX(2, 2, "Тигр", 1, "done", 3.5, FileRef(2, "000002/original.mp4", "b.mp4", 1, 3.5)),
        SceneX(3, 3, "Дыра", 3, "not_started", 4.0, None),
        SceneX(4, 4, "Вырезана", 4, "cut", 9.0, None),
    ]
    shots = [
        ShotX(10, 1, "01.01", 1, "done", 2.0, None),
        ShotX(20, 2, "02.01", 1, "done", 3.5, None),
    ]
    wav = FileRef(10, "000010/original.wav", "x.wav", 1, 1.5, "audio")
    cues = [
        CueX(1, "SND-01", "dialogue", "Herald", "Hello, strait!", 1, 10, 0.5, None),
        CueX(2, "SND-02", "sfx", None, None, 2, 20, 1.0, wav),
        CueX(3, "SND-03", "music", None, None, 1, None, 0, wav),
    ]
    opts = Options(
        **{
            "media_root": "D:\\BrassSpyglass",
            "placeholders": True,
            "base_url": "https://x.example",
            **options,
        }
    )
    clips = ep.plan_timeline(scenes, shots, level=opts.level, placeholders=opts.placeholders)
    placed = ep.place_cues(cues, scenes, shots, clips)
    refs = [
        Reference(
            FileRef(20, "000020/original.png", "ref.png", 1, None, "image"),
            "Media/References/R00020_ref.png",
        )
    ]
    return PackageSpec(
        project_title="Битва при кривом зеркале",
        options=opts,
        clips=clips,
        placements=ep.audio_placements(placed),
        subtitles=ep.subtitles(placed),
        references=refs if opts.references else [],
        skipped=["Сцена 4 · Вырезана — вырезана"],
        files_dir=library,
        font=exporter.find_font(),
    )


@pytest.fixture
def built(library, tmp_path):
    spec = spec_for(library, tmp_path, references=True)
    dest = tmp_path / "pack.zip"
    result = exporter.build_package(spec, dest)
    return spec, dest, result, tmp_path


# --- пути ----------------------------------------------------------------------------------------


def test_media_url_for_each_kind_of_folder():
    assert (
        exporter.media_url("D:\\BrassSpyglass\\", "Media/Scenes/a b.mov")
        == "file://localhost/D:/BrassSpyglass/Media/Scenes/a%20b.mov"
    )
    assert (
        exporter.media_url("/Users/me/Brass", "Media/x.mov")
        == "file://localhost/Users/me/Brass/Media/x.mov"
    )
    assert exporter.media_url("", "Media/x.mov") == "Media/x.mov"


def test_overlapping_sounds_move_to_a_second_track():
    cue = CueX(1, "SND-01", "sfx", None, None, 1, None, 0, None)
    a, b, c = (ep.Placement(cue, 2, s, n) for s, n in ((0, 48), (24, 48), (60, 10)))
    tracks = exporter.pack_lane([a, b, c])
    assert [[p.start_frame for p in t] for t in tracks] == [[0, 60], [24]]


def test_card_text_is_latin_without_a_cyrillic_font():
    clip = ep.plan_timeline([SceneX(1, 3, "Тигр", 1, "x", 6.0, None)], [], placeholders=True)[0]
    assert exporter.card_lines(clip, 24, False) == ("SCENE 3", "NO FILE · 0:06")
    assert exporter.card_lines(clip, 24, True) == ("Сцена 3 · Тигр", "Нет файла · 0:06")


# --- пакет ---------------------------------------------------------------------------------------


def test_the_package_has_everything_the_spec_promises(built):
    _, dest, result, _ = built
    names = set(zipfile.ZipFile(dest).namelist())
    assert {"timeline_fcp7.xml", "timeline.otio", "subtitles_en.srt", "README.txt"} <= names
    assert (
        "Media/Scenes/S02_tigr_v1.mp4" in names and "Media/Scenes/S01_dva-zerkala_v3.mp4" in names
    )
    assert any(n.startswith("Media/Placeholders/") for n in names)
    assert "Media/Sound/SND-02_v1.wav" in names and "Media/References/R00020_ref.png" in names
    assert (result.clips, result.placeholders, result.references) == (3, 1, 1)


def test_originals_are_copied_byte_for_byte(built, library):
    _, dest, _, _ = built
    with zipfile.ZipFile(dest) as archive:
        packed = hashlib.sha256(archive.read("Media/Scenes/S02_tigr_v1.mp4")).hexdigest()
    assert packed == hashlib.sha256((library / "000002/original.mp4").read_bytes()).hexdigest()


def test_the_timeline_opens_in_otio_with_scenes_in_tracker_order_to_the_frame(built, tmp_path):
    _, dest, _, _ = built
    with zipfile.ZipFile(dest) as archive:
        archive.extract("timeline_fcp7.xml", tmp_path)
    timeline = otio.adapters.read_from_file(
        str(tmp_path / "timeline_fcp7.xml"), adapter_name="fcp_xml"
    )
    video = [t for t in timeline.tracks if t.kind == otio.schema.TrackKind.Video][0]
    clips = [(c.name, int(c.source_range.duration.value)) for c in video]
    # порядок трекера: Тигр (order 1), Два зеркала (order 2), Дыра (3, заглушка); «Вырезана» нет
    assert [c[0] for c in clips[:2]] == ["S02_tigr_v1.mp4", "S01_dva-zerkala_v3.mp4"]
    assert clips[2][0].startswith("P03_S03_dyra")
    assert [c[1] for c in clips] == [84, 48, 96]  # 3,5 с, 2,0 с и 4,0 с ровно в кадрах при 24 к/с
    starts = [int(video.range_of_child_at_index(i).start_time.value) for i in range(3)]
    assert starts == [0, 84, 132]  # встык, без дыр и наложений


def test_the_xml_carries_sequence_settings_paths_and_marker_comments(built, tmp_path):
    _, dest, _, _ = built
    text = zipfile.ZipFile(dest).read("timeline_fcp7.xml").decode("utf-8")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>')
    assert "<width>1920</width>" in text and "<height>1080</height>" in text
    assert "<samplerate>48000</samplerate>" in text
    assert "<timebase>24</timebase>" in text and "<string>01:00:00:00</string>" in text
    assert "file://localhost/D:/BrassSpyglass/Media/Scenes/S02_tigr_v1.mp4" in text
    assert "<name>2 · Тигр</name>" in text
    assert "Статус: Готово · https://x.example/scenes/2" in text  # комментарий маркера
    assert "нет файла, заглушка" in text  # у заглушки статус честный


def test_otio_json_has_the_timeline_start_and_markers(built):
    _, dest, _, _ = built
    data = json.loads(zipfile.ZipFile(dest).read("timeline.otio"))
    assert data["global_start_time"]["value"] == 86400 and data["global_start_time"]["rate"] == 24
    markers = [
        m for t in data["tracks"]["children"] for c in t["children"] for m in c.get("markers", [])
    ]
    assert [m["name"] for m in markers] == ["2 · Тигр", "1 · Два зеркала", "3 · Дыра"]
    assert markers[0]["comment"].startswith("Статус: Готово")


def test_audio_lands_on_its_own_tracks_at_the_right_frame(built, tmp_path):
    _, dest, _, _ = built
    with zipfile.ZipFile(dest) as archive:
        archive.extract("timeline_fcp7.xml", tmp_path)
    timeline = otio.adapters.read_from_file(
        str(tmp_path / "timeline_fcp7.xml"), adapter_name="fcp_xml"
    )
    audio = [t for t in timeline.tracks if t.kind == otio.schema.TrackKind.Audio]
    placed = {
        c.name: int(t.range_of_child(c).start_time.value)
        for t in audio
        for c in t
        if isinstance(c, otio.schema.Clip)
    }
    # SND-02 — sfx, шот 02.01 стоит первым на таймлайне (Тигр), сдвиг 1 с = 24 кадра
    assert placed["SND-02"] == 24
    assert placed["SND-03"] == 84  # музыка сцены 1 — от начала сцены «Два зеркала»


def test_subtitles_follow_the_assembled_timeline(built):
    _, dest, result, _ = built
    srt = zipfile.ZipFile(dest).read("subtitles_en.srt").decode("utf-8")
    # реплика шота 01.01 со сдвигом 0,5 с; сцена «Два зеркала» на таймлайне начинается на 3,5 с
    assert srt.startswith("1\n00:00:04,000 --> ")
    assert "Hello, strait!" in srt and result.subtitles == 1


def test_the_placeholder_is_a_real_clip_of_exactly_the_planned_length(built, tmp_path):
    _, dest, _, _ = built
    with zipfile.ZipFile(dest) as archive:
        name = next(n for n in archive.namelist() if n.startswith("Media/Placeholders/"))
        archive.extract(name, tmp_path)
    info = media.probe(tmp_path / name)
    assert (info.width, info.height) == (1920, 1080)
    assert round(info.duration * 24) == 96


def test_readme_explains_how_to_open_it_and_lists_what_was_left_out(built):
    _, dest, _, _ = built
    text = zipfile.ZipFile(dest).read("README.txt").decode("utf-8")
    assert "File → Import → Timeline" in text and "D:\\BrassSpyglass" in text
    assert "01:00:00:00" in text and "Сцена 4 · Вырезана — вырезана" in text
    assert "[заглушка]" in text


def test_the_premiere_readme_names_premiere(library, tmp_path):
    spec = spec_for(library, tmp_path, target="premiere")
    result = exporter.build_package(spec, tmp_path / "p.zip")
    text = zipfile.ZipFile(tmp_path / "p.zip").read("README.txt").decode("utf-8")
    assert "Premiere Pro: File → Import" in text and result.size_bytes > 0


def test_a_missing_original_fails_before_any_work_and_leaves_no_partial_zip(library, tmp_path):
    spec = spec_for(library, tmp_path)
    spec.files_dir = tmp_path / "empty"  # файлы из базы на диске не лежат
    dest = tmp_path / "x.zip"
    with pytest.raises(exporter.MissingSource):
        exporter.build_package(spec, dest)
    assert not dest.exists() and not dest.with_suffix(".part").exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith("export-")]
