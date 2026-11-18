"""Live rolling recorder (spec §6.3): streamlink -> ffmpeg segment muxer -> ~4 s .ts files
named by their local wall-clock start time; SegmentIndex maps time ranges to files."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)
SEG_SECONDS = 4
NAME_FMT = "%Y%m%d_%H%M%S"
BELOW_NORMAL = 0x00004000 if os.name == "nt" else 0
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def seg_name(t: float) -> str:
    return time.strftime(NAME_FMT, time.localtime(t)) + ".ts"


class SegmentIndex:
    def __init__(self, directory: Path):
        self.dir = Path(directory)

    @staticmethod
    def parse(name: str) -> int:
        return int(time.mktime(time.strptime(Path(name).stem, NAME_FMT)))

    def segments(self) -> list[tuple[int, Path]]:
        out = []
        for p in self.dir.glob("*.ts"):
            try:
                out.append((self.parse(p.name), p))
            except ValueError:
                continue
        out.sort()
        return out

    def _spans(self) -> list[tuple[int, float, Path]]:
        segs = self.segments()
        spans = []
        for i, (t, p) in enumerate(segs):
            nxt = segs[i + 1][0] if i + 1 < len(segs) else None
            end = nxt if nxt is not None and nxt - t <= SEG_SECONDS + 3 else t + SEG_SECONDS
            spans.append((t, end, p))
        return spans

    def covering(self, a: float, b: float) -> list[Path] | None:
        spans = [s for s in self._spans() if s[0] < b and s[1] > a]
        if not spans or spans[0][0] > a + 1 or spans[-1][1] < b - 1:
            return None
        for (t0, e0, _), (t1, _, _) in zip(spans, spans[1:]):
            if t1 - e0 > 1:
                return None
        return [p for _, _, p in spans]

    def latest_time(self) -> float | None:
        segs = self.segments()
        return float(segs[-1][0] + SEG_SECONDS) if segs else None

    def prune(self, now: float, keep_seconds: float, pinned: list[tuple[float, float]] = ()) -> None:
        for t, end, p in self._spans():
            if end >= now - keep_seconds:
                continue
            if any(t < pb and end > pa for pa, pb in pinned):
                continue
            try:
                p.unlink()
            except OSError:
                pass

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for _, p in self.segments() if p.exists())


def _exe(name: str) -> str:
    cand = Path(sys.executable).parent / (name + (".exe" if os.name == "nt" else ""))
    return str(cand) if cand.exists() else name


class Recorder:
    """Runs `streamlink ... -O | ffmpeg -f segment` for one channel."""

    def __init__(self, channel: str, directory: Path, quality: str = "1080p60,720p60,best"):
        self.channel = channel
        self.dir = Path(directory)
        self.quality = quality
        self.index = SegmentIndex(self.dir)
        self._sl: subprocess.Popen | None = None
        self._ff: subprocess.Popen | None = None
        self.started = 0.0

    def start(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        flags = BELOW_NORMAL | NO_WINDOW
        sl_cmd = [_exe("streamlink"), "--twitch-low-latency", "--stream-segment-threads", "2",
                  "--retry-streams", "5", "--retry-open", "3", "--loglevel", "error",
                  f"https://twitch.tv/{self.channel}", self.quality, "-O"]
        ff_cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-map", "0:v:0?",
                  "-map", "0:a:0?", "-c", "copy", "-f", "segment", "-segment_time", str(SEG_SECONDS),
                  "-segment_format", "mpegts", "-reset_timestamps", "1", "-strftime", "1",
                  str(self.dir / f"{NAME_FMT}.ts")]
        self._sl = subprocess.Popen(sl_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    creationflags=flags)
        self._ff = subprocess.Popen(ff_cmd, stdin=self._sl.stdout, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, creationflags=flags)
        self._sl.stdout.close()  # ffmpeg owns the pipe now
        self.started = time.time()
        log.info("recorder started: %s", self.channel)

    def alive(self) -> bool:
        if not self._ff or self._ff.poll() is not None or not self._sl or self._sl.poll() is not None:
            return False
        last = self.index.latest_time()
        return last is not None and time.time() - last < 25 or time.time() - self.started < 40

    def stop(self) -> None:
        for p in (self._sl, self._ff):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
        self._sl = self._ff = None
        log.info("recorder stopped: %s", self.channel)
