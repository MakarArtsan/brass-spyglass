"""План экспорта: порядок сцен, только готовое, заглушки, кадры, звук и субтитры по собранному таймлайну."""

import pytest

from app import export_plan as ep
from app.export_plan import CueX, FileRef, Level, SceneX, ShotX


def f(n: int, name: str = "clip.mov", seconds: float | None = 5.0, v: int = 1) -> FileRef:
    return FileRef(n, f"{n:06d}/original.mov", name, v, seconds)


def scene(i, number, title, order, status="done", planned=10.0, final=None):
    return SceneX(i, number, title, order, status, planned, final)


def shot(i, scene_id, code, order, status="done", dur=4.0, final=None):
    return ShotX(i, scene_id, code, order, status, dur, final)


# --- имена -------------------------------------------------------------------------------------


def test_slug_is_latin_and_safe_for_file_names():
    assert ep.slug("Два зеркала") == "dva-zerkala"
    assert ep.slug("Тигр!") == "tigr"
    assert ep.slug("Щит и меч: Ёж") == "shchit-i-mech-ezh"
    assert ep.slug("???") == "scene"


def test_file_names_carry_scene_number_title_and_version():
    s = scene(1, 1, "Два зеркала", 1)
    assert ep.scene_file_name(s, f(1, "x.MOV", v=3)) == "S01_dva-zerkala_v3.mov"
    assert ep.shot_file_name(s, shot(5, 1, "01.03", 1), f(2, "y.mp4", v=2)) == "S01_01.03_v2.mp4"


# --- что и в каком порядке -----------------------------------------------------------------------


def test_scenes_go_in_tracker_order_and_the_scene_number_does_not_matter():
    scenes = [
        scene(1, 1, "Первая", 3, final=f(1)),
        scene(2, 2, "Вторая", 1, final=f(2)),
        scene(3, 3, "Третья", 2, final=f(3)),
    ]
    clips = ep.plan_timeline(scenes, [])
    assert [c.scene_number for c in clips] == [2, 3, 1]


def test_only_done_scenes_with_a_final_file_are_exported():
    scenes = [
        scene(1, 1, "Готова", 1, final=f(1)),
        scene(2, 2, "В работе", 2, status="in_progress", final=f(2)),
        scene(3, 3, "Нет файла", 3, status="done", final=None),
        scene(4, 4, "Вырезана", 4, status="cut", final=f(4)),
    ]
    clips = ep.plan_timeline(scenes, [])
    assert [c.scene_number for c in clips] == [1]
    assert all(c.kind == "file" for c in clips)


def test_placeholders_fill_the_gaps_with_the_planned_length():
    scenes = [
        scene(1, 1, "Готова", 1, planned=10, final=f(1, seconds=5)),
        scene(2, 2, "Дыра", 2, status="not_started", planned=7.5),
        scene(3, 3, "Вырезана", 3, status="cut", planned=9),
    ]
    clips = ep.plan_timeline(scenes, [], placeholders=True)
    assert [c.kind for c in clips] == ["file", "placeholder"]
    assert [c.frames for c in clips] == [120, 180]  # файл — по своей длине, заглушка — по плану
    assert clips[1].package_path.startswith("Media/Placeholders/")
    assert clips[1].label == "Сцена 2 · Дыра"  # вырезанная сцена в таймлайн не попадает


def test_clips_are_contiguous_and_frame_accurate():
    scenes = [scene(i, i, f"С{i}", i, final=f(i, seconds=2.5 + i / 24)) for i in (1, 2, 3)]
    clips = ep.plan_timeline(scenes, [])
    assert clips[0].start_frame == 0
    for a, b in zip(clips, clips[1:], strict=False):
        assert b.start_frame == a.end_frame  # встык, без дыр и наложений
    assert [c.frames for c in clips] == [round((2.5 + i / 24) * 24) for i in (1, 2, 3)]


def test_a_file_without_a_probed_duration_falls_back_to_the_plan():
    clips = ep.plan_timeline([scene(1, 1, "С", 1, planned=3, final=f(1, seconds=None))], [])
    assert clips[0].frames == 72


def test_shots_level_takes_done_takes_in_order_inside_scenes():
    scenes = [scene(1, 1, "А", 2), scene(2, 2, "Б", 1)]
    shots = [
        shot(10, 1, "01.02", 2, final=f(10)),
        shot(11, 1, "01.01", 1, final=f(11)),
        shot(12, 1, "01.03", 3, status="in_progress", final=f(12)),
        shot(20, 2, "02.01", 1, final=f(20)),
    ]
    clips = ep.plan_timeline(scenes, shots, level=Level.SHOTS)
    assert [c.name for c in clips] == [
        "S02_02.01_v1.mov",
        "S01_01.01_v1.mov",
        "S01_01.02_v1.mov",
    ]
    assert all(c.shot_id is not None and c.package_path.startswith("Media/Shots/") for c in clips)


def test_shots_level_placeholders_take_the_shot_duration():
    scenes = [scene(1, 1, "А", 1)]
    shots = [
        shot(10, 1, "01.01", 1, status="not_started", dur=3),
        shot(11, 1, "01.02", 2, final=f(11)),
    ]
    clips = ep.plan_timeline(scenes, shots, level=Level.SHOTS, placeholders=True)
    assert [(c.kind, c.frames) for c in clips] == [("placeholder", 72), ("file", 120)]


def test_timecode_starts_at_one_hour():
    assert ep.timecode(0) == "01:00:00:00"
    assert ep.timecode(24 * 61 + 5) == "01:01:01:05"


# --- звук и субтитры -----------------------------------------------------------------------------


def cue(i, type_, text, scene_id=None, shot_id=None, offset=0.0, file=None, who=None):
    return CueX(i, f"SND-{i:02d}", type_, who, text, scene_id, shot_id, offset, file)


def test_subtitles_are_timed_on_the_assembled_timeline_not_on_the_tracker_one():
    # В трекере сцена 1 стоит второй, но на таймлайн готова только она: её реплика уходит к нулю.
    scenes = [
        scene(1, 1, "А", 2, planned=4, final=f(1, seconds=4)),
        scene(2, 2, "Б", 1, status="in_progress"),
    ]
    shots = [shot(10, 1, "01.01", 1, dur=4), shot(20, 2, "02.01", 1, dur=6)]
    clips = ep.plan_timeline(scenes, shots)
    assert len(clips) == 1 and clips[0].scene_id == 1
    placed = ep.place_cues(
        [cue(1, "dialogue", "Hello there", shot_id=10, offset=1.0)], scenes, shots, clips
    )
    items = ep.subtitles(placed)
    assert [(s.start_frame, s.text) for s in items] == [(24, "Hello there")]


def test_a_cue_keeps_its_offset_inside_the_scene_when_the_file_length_differs():
    scenes = [scene(1, 1, "А", 1, planned=10, final=f(1, seconds=12))]
    shots = [shot(10, 1, "01.01", 1, dur=4), shot(11, 1, "01.02", 2, dur=6)]
    clips = ep.plan_timeline(scenes, shots)
    placed = ep.place_cues(
        [cue(1, "dialogue", "Second shot line", shot_id=11, offset=0.5)], scenes, shots, clips
    )
    assert ep.subtitles(placed)[0].start_frame == round(4.5 * 24)  # 4 с до шота + 0,5 с сдвиг


def test_a_cue_of_a_scene_that_is_not_on_the_timeline_is_dropped():
    scenes = [scene(1, 1, "А", 1, final=f(1)), scene(2, 2, "Б", 2, status="in_progress")]
    clips = ep.plan_timeline(scenes, [])
    placed = ep.place_cues([cue(1, "dialogue", "Lost line", scene_id=2)], scenes, [], clips)
    assert placed == []


def test_placeholders_keep_their_subtitles():
    scenes = [scene(1, 1, "А", 1, status="in_progress", planned=5)]
    clips = ep.plan_timeline(scenes, [], placeholders=True)
    placed = ep.place_cues([cue(1, "dialogue", "Still here", scene_id=1)], scenes, [], clips)
    assert len(ep.subtitles(placed)) == 1


def test_subtitle_length_follows_reading_speed_and_never_leaves_its_clip():
    scenes = [scene(1, 1, "А", 1, planned=3, final=f(1, seconds=3))]
    clips = ep.plan_timeline(scenes, [])
    long_text = "x" * 200
    placed = ep.place_cues(
        [cue(1, "dialogue", long_text, scene_id=1, offset=2.0)], scenes, [], clips
    )
    (item,) = ep.subtitles(placed)
    assert item.end_frame == clips[0].end_frame  # обрезано по концу клипа
    assert ep.subtitle_seconds("hi", None) == ep.MIN_SUBTITLE_SEC
    assert ep.subtitle_seconds(long_text, None) == ep.MAX_SUBTITLE_SEC
    assert ep.subtitle_seconds("anything", 3.25) == 3.25  # у озвучки есть файл — берём его длину


def test_srt_format():
    text = ep.format_srt(
        [
            ep.Subtitle(1, 0, 48, "Line one"),
            ep.Subtitle(2, 3600 * 24 + 12, 3600 * 24 + 60, "Line two"),
        ]
    )
    assert text.startswith(
        "1\n00:00:00,000 --> 00:00:02,000\nLine one\n\n2\n01:00:00,500 --> 01:00:02,500\nLine two"
    )


def test_only_sound_with_a_file_goes_to_audio_tracks_and_lanes_follow_the_type():
    scenes = [scene(1, 1, "А", 1, planned=10, final=f(1, seconds=10))]
    clips = ep.plan_timeline(scenes, [])
    wav = FileRef(50, "000050/original.wav", "x.wav", 1, 2.0, "audio")
    cues = [
        cue(1, "dialogue", "Voice", scene_id=1, file=wav),
        cue(2, "sfx", None, scene_id=1, offset=1, file=wav),
        cue(3, "music", None, scene_id=1, file=wav),
        cue(4, "sfx", None, scene_id=1),  # файла нет — на дорожку не идёт
        cue(5, "silence", None, scene_id=1, file=wav),  # у «тишины» дорожки нет
    ]
    placements = ep.audio_placements(ep.place_cues(cues, scenes, [], clips))
    assert [(p.cue.id, p.lane) for p in placements] == [(1, 1), (2, 2), (3, 3)]
    assert placements[1].start_frame == 24 and placements[1].frames == 48


@pytest.mark.parametrize("planned", [0.04, 0.5, 359.99])
def test_a_clip_is_never_shorter_than_a_frame(planned):
    clips = ep.plan_timeline(
        [scene(1, 1, "А", 1, status="x", planned=planned)], [], placeholders=True
    )
    assert clips[0].frames >= 1
