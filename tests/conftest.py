import subprocess
from pathlib import Path

import pytest

from clipforge.recorder import seg_name


def make_ts_segments(directory: Path, start: int, count: int, size="320x180", seg=4):
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        out = directory / seg_name(start + seg * i)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", str(seg),
                        "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-c:a", "aac",
                        "-f", "mpegts", str(out)], check=True)


@pytest.fixture
def ts_segments(tmp_path):
    start = 1_763_500_000
    make_ts_segments(tmp_path / "buf", start, 4)
    return tmp_path / "buf", start
