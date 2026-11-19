"""Cut a raw clip from the live ring buffer or from the in-progress VOD (spec §6.5)."""
from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .recorder import BELOW_NORMAL, NO_WINDOW, SegmentIndex, _exe

log = logging.getLogger(__name__)


@dataclass
class RawClip:
    path: Path
    t0: float          # wall-clock time of the clip's first frame


def extract_buffer(index: SegmentIndex, a: float, b: float, out: Path) -> RawClip | None:
    segs = index.covering(a, b)
    if not segs:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in segs), encoding="utf-8")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", "-f", "mpegts", str(out)], capture_output=True, text=True,
                       creationflags=BELOW_NORMAL | NO_WINDOW)
    lst.unlink(missing_ok=True)
    if r.returncode != 0 or not out.exists():
        log.warning("buffer concat failed: %s", r.stderr[-500:])
        return None
    return RawClip(path=out, t0=float(SegmentIndex.parse(segs[0].name)))


def extract_vod(vod_url: str, vod_start: float, a: float, b: float, out: Path) -> RawClip | None:
    """Download [a, b] (wall-clock) from a Twitch VOD that started at vod_start."""
    oa, ob = max(0.0, a - vod_start), max(0.0, b - vod_start)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_exe("yt-dlp"), "--quiet", "--no-warnings", "-f", "best[height<=1080]/best",
           "--download-sections", f"*{oa:.1f}-{ob:.1f}", "--force-overwrites",
           "-o", str(out.with_suffix(".%(ext)s")), vod_url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=240, creationflags=BELOW_NORMAL | NO_WINDOW)
    except subprocess.TimeoutExpired:
        log.warning("vod extract timed out (%s)", vod_url)
        return None
    files = sorted(out.parent.glob(out.stem + ".*"))
    files = [f for f in files if f.suffix not in (".part", ".txt", ".ytdl")]
    if r.returncode != 0 or not files:
        log.warning("vod extract failed (%s): %s", vod_url, r.stderr[-500:])
        return None
    return RawClip(path=files[0], t0=vod_start + oa)
