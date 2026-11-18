import subprocess
from pathlib import Path

from clipforge.app import App
from clipforge.config import Config
from clipforge.detector import Moment
from clipforge.extractor import RawClip

FIX = Path(__file__).parent / "fixtures" / "speech.wav"


def make_raw(path: Path):
    # 40 s: test pattern video; audio = quiet noise, speech at 8 s and 26 s, loud tone 30-34 s
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30", "-t", "40",
        "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.01:sample_rate=48000", "-i", str(FIX), "-i", str(FIX),
        "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000:duration=4",
        "-filter_complex", "[2:a]adelay=8000|8000[s1];[3:a]adelay=26000|26000[s2];[4:a]volume=3,adelay=30000|30000[t];"
                           "[1:a][s1][s2][t]amix=inputs=4:duration=first:normalize=0[a]",
        "-map", "0:v", "-map", "[a]", "-t", "40", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
        "-f", "mpegts", str(path)], check=True)


def test_process_moment_end_to_end(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", secrets_dir=tmp_path / "secrets")
    app = App(cfg)
    raw = tmp_path / "raw.ts"
    make_raw(raw)
    t0 = 1_763_500_000.0
    m = Moment(channel="xqc", t_on=t0 + 37, t_peak=t0 + 39, t_event=t0 + 30, t_end_hint=t0 + 36, hype_peak=0.95,
               burst_size=8.0, category="funny", rise_time=2.0, features={"chat_lines": ["KEKW", "LMAO"]})
    mid = app.db.add_moment(channel="xqc", t_event=m.t_event, t_on=m.t_on, t_peak=m.t_peak, score=0.95,
                            category="funny", features=m.features)
    app.process(mid, RawClip(raw, t0), m)
    row = app.db.get_moment(mid)
    assert row["state"] == "ready", row["note"]
    assert Path(row["out_path"]).exists()
    s, e = row["features"]["window"]
    assert 15 <= e - s <= 60 and s <= 30 - 10
    assert "GTA 6" in row["title"]
