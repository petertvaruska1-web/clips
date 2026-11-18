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
