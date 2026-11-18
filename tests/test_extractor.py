import subprocess

from clipforge.extractor import extract_buffer
from clipforge.recorder import SegmentIndex


def duration(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                 "csv=p=0", str(p)], capture_output=True, text=True).stdout)


def test_extract_buffer_concatenates_and_reports_t0(ts_segments, tmp_path):
    buf, start = ts_segments
    raw = extract_buffer(SegmentIndex(buf), start + 5, start + 11, tmp_path / "raw.ts")
    assert raw is not None
    assert raw.t0 == start + 4
    assert 7.5 < duration(raw.path) < 8.6


def test_extract_buffer_missing_range(ts_segments, tmp_path):
    buf, start = ts_segments
    assert extract_buffer(SegmentIndex(buf), start + 100, start + 110, tmp_path / "raw.ts") is None
