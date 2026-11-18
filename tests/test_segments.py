import time
from datetime import datetime

from clipforge.recorder import SegmentIndex, seg_name


def make(dirp, starts):
    for t in starts:
        (dirp / seg_name(t)).write_bytes(b"x")


def test_seg_name_roundtrip(tmp_path):
    t = 1_763_500_000
    name = seg_name(t)
    idx = SegmentIndex(tmp_path)
    assert idx.parse(name) == t


def test_covering_returns_contiguous_segments(tmp_path):
    base = 1_763_500_000
    make(tmp_path, [base + 4 * i for i in range(20)])
    segs = SegmentIndex(tmp_path).covering(base + 10, base + 30)
    assert [SegmentIndex.parse(p.name) for p in segs] == [base + 8 + 4 * i for i in range(6)]


def test_covering_with_gap_returns_none(tmp_path):
    base = 1_763_500_000
    make(tmp_path, [base + 4 * i for i in range(5)] + [base + 60 + 4 * i for i in range(5)])
    assert SegmentIndex(tmp_path).covering(base + 5, base + 70) is None


def test_covering_outside_buffer_returns_none(tmp_path):
    base = 1_763_500_000
    make(tmp_path, [base + 4 * i for i in range(5)])
    assert SegmentIndex(tmp_path).covering(base - 30, base + 10) is None


def test_prune_keeps_recent_and_pinned(tmp_path):
    base = 1_763_500_000
    make(tmp_path, [base + 4 * i for i in range(100)])  # 400 s
    idx = SegmentIndex(tmp_path)
    idx.prune(now=base + 400, keep_seconds=240, pinned=[(base + 20, base + 30)])
    kept = sorted(SegmentIndex.parse(p.name) for p in tmp_path.glob("*.ts"))
    assert base + 20 in kept and base + 28 in kept
    assert base + 100 not in kept
    assert min(t for t in kept if t > base + 40) >= base + 400 - 240 - 4
