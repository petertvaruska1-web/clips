import json
import subprocess

import pytest

from clipforge.captions import build_ass, chunk_words
from clipforge.render import RenderJob, render_short
from clipforge.transcribe import Word


def W(s, e, t):
    return Word(s, e, t)


def test_chunks_are_one_to_three_words_and_break_on_pauses():
    words = [W(0, .2, "no"), W(.2, .4, "way"), W(.4, .6, "bro,"), W(.6, .8, "the"), W(2.0, 2.2, "police")]
    chunks = chunk_words(words)
    assert all(1 <= len(c) <= 3 for c in chunks)
    assert [w.text for w in chunks[-1]] == ["police"]


def test_ass_highlights_active_word_and_offsets_times():
    ass = build_ass([W(10.0, 10.4, "hello"), W(10.4, 10.9, "chat")], clip_start=10.0, hook="WAIT FOR IT",
                    credit="twitch.tv/xqc", layout="fill")
    assert "&H00E1FF&" in ass
    assert "0:00:00.00" in ass and "HELLO" in ass
    assert "WAIT FOR IT" in ass and "twitch.tv/xqc" in ass


def test_ass_masks_slurs():
    ass = build_ass([W(0, .5, "retard")], clip_start=0, hook="", credit="", layout="fill")
    assert "RETARD" not in ass


def probe(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                          "-of", "json", str(p)], capture_output=True, text=True).stdout
    return json.loads(out)


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    p = tmp_path_factory.mktemp("src") / "src.ts"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=60",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000", "-t", "12",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-f", "mpegts", str(p)], check=True)
    return p


@pytest.mark.parametrize("layout", ["fill", "stack"])
def test_render_produces_vertical_short(src, tmp_path, layout):
    job = RenderJob(raw_path=src, a=2.0, b=10.0, t_event=5.0, layout=layout,
                    facecam=(1500, 40, 380, 236) if layout == "stack" else None,
                    words=[W(3.0, 3.5, "no"), W(3.5, 4.0, "way")], hook="WAIT FOR IT",
                    credit="twitch.tv/test", out_path=tmp_path / f"{layout}.mp4")
    out = render_short(job)
    info = probe(out)
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    assert (v["width"], v["height"]) == (1080, 1920)
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert abs(float(info["format"]["duration"]) - 8.0) < 0.3


def test_no_facecam_in_test_pattern(src):
    from clipforge.facecam import find_facecam, sample_frames
    assert find_facecam(sample_frames(src, count=4), 1920, 1080) is None


def _start_freeze(path):
    out = subprocess.run(["ffmpeg", "-v", "info", "-t", "3", "-i", str(path), "-vf", "freezedetect=n=0.003:d=0.2",
                          "-map", "0:v", "-f", "null", "-"], capture_output=True, text=True).stderr
    for line in out.splitlines():
        if "freeze_start: 0" in line or "freeze_start: 0." in line:
            return True
    return False


def test_render_starting_mid_gop_has_no_frozen_start(tmp_path):
    src = tmp_path / "gop.ts"
    # 60 fps with a keyframe only every 2 s, like Twitch; content changes every frame
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=60",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000", "-t", "12",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "120", "-keyint_min", "120", "-sc_threshold", "0",
                    "-c:a", "aac", "-f", "mpegts", str(src)], check=True)
    job = RenderJob(raw_path=src, a=3.3, b=9.3, t_event=6.0, layout="fill", out_path=tmp_path / "o.mp4")
    out = render_short(job)
    assert not _start_freeze(out)


@pytest.fixture(scope="module")
def bg_dir(tmp_path_factory):
    from clipforge.background import prepare
    d = tmp_path_factory.mktemp("bg")
    src = d / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "mandelbrot=size=1280x720:rate=30",
                    "-t", "20", "-c:v", "libx264", "-preset", "ultrafast", str(src)], check=True)
    dur = prepare(src, d / "a.mp4")
    (d / "manifest.json").write_text(json.dumps([
        {"file": "a.mp4", "category": "parkour", "credit": "Test (CC BY)", "duration": dur}]))
    return d


def test_prepare_makes_panel_sized_silent_clip(bg_dir):
    info = probe(bg_dir / "a.mp4")
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    assert (v["width"], v["height"]) == (1080, 960)
    assert not any(s["codec_type"] == "audio" for s in info["streams"])


@pytest.mark.parametrize("cam", [None, (1500, 40, 380, 236), (40, 40, 380, 236)])
def test_split_render(src, tmp_path, bg_dir, cam):
    from clipforge.background import BackgroundPicker
    bg = BackgroundPicker(bg_dir).pick(8.0)
    assert bg is not None and bg.offset + 8.0 < 20
    job = RenderJob(raw_path=src, a=2.0, b=10.0, t_event=5.0, layout="split", facecam=cam,
                    words=[W(3.0, 3.5, "no"), W(3.5, 4.0, "way")], hook="WAIT FOR IT",
                    credit="twitch.tv/test", out_path=tmp_path / "split.mp4", bg=bg)
    info = probe(render_short(job))
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    assert (v["width"], v["height"]) == (1080, 1920)
    assert abs(float(info["format"]["duration"]) - 8.0) < 0.3
    assert job.layout == "split"


def test_split_without_background_falls_back_to_original(src, tmp_path):
    job = RenderJob(raw_path=src, a=2.0, b=6.0, t_event=3.0, layout="split", facecam=None,
                    out_path=tmp_path / "fb.mp4", bg=None)
    render_short(job)
    assert job.layout == "fill"


def test_split_captions_sit_on_the_seam():
    ass = build_ass([W(0, .5, "hey")], clip_start=0, hook="", credit="twitch.tv/x", layout="split",
                    cap_y=960, credit_an=9)
    assert r"\pos(540,960)" in ass and r"{\an9}twitch.tv/x" in ass


def test_picker_avoids_repeating_category(tmp_path):
    from clipforge.background import BackgroundPicker
    for n in ("a", "b", "c"):
        (tmp_path / f"{n}.mp4").write_bytes(b"x")
    (tmp_path / "manifest.json").write_text(json.dumps([
        {"file": "a.mp4", "category": "parkour", "duration": 600},
        {"file": "b.mp4", "category": "ramp", "duration": 600},
        {"file": "c.mp4", "category": "runner", "duration": 10}]))
    p = BackgroundPicker(tmp_path)
    cats = [p.pick(30).category for _ in range(20)]
    assert all(x != y for x, y in zip(cats, cats[1:]))
    assert "runner" not in cats          # too short for a 30 s clip


def test_inset_box_is_centred_on_face_and_inside_frame():
    from clipforge.facecam import facecam_box, inset_box
    x, y, w, h = inset_box((1800, 900, 150), 1920, 1080)        # face at the right edge
    assert x + w <= 1920 and y + h <= 1080 and w > 150
    x, y, w, h = inset_box((900, 500, 120), 1920, 1080)
    assert abs((x + w / 2) - 900) <= 2
    bx, by, bw, bh = facecam_box((900, 500, 120), 1920, 1080)
    assert bw > w                                                # stack crop is wider than the inset


def test_next_style_alternates(tmp_path):
    from clipforge.app import App
    from clipforge.config import load_config
    cfg = load_config()
    cfg.data_dir = str(tmp_path)
    app = App(cfg)
    assert app.next_style() == "split"
    mid = app.db.add_moment(channel="x", t_event=__import__("time").time(), t_on=0, t_peak=0, score=0.9,
                            category="funny", features={"style": "split"})
    app.db.update_moment(mid, state="ready", score=0.9)
    assert app.next_style() == "original"
    mid = app.db.add_moment(channel="x", t_event=__import__("time").time(), t_on=0, t_peak=0, score=0.9,
                            category="funny", features={"style": "original"})
    app.db.update_moment(mid, state="ready", score=0.9)
    assert app.next_style() == "split"
