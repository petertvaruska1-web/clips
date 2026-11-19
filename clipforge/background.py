"""Satisfying background gameplay for the split-screen style (bottom half of the Short).

Footage is Creative Commons Attribution (CC BY) gameplay from YouTube, pre-cut to the panel size by
`prepare()` and listed in data/backgrounds/manifest.json with its credit line.
"""
from __future__ import annotations

import json
import logging
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT
from .recorder import BELOW_NORMAL, NO_WINDOW

log = logging.getLogger(__name__)
BG_DIR = ROOT / "data" / "backgrounds"
PANEL_W, PANEL_H = 1080, 960


@dataclass
class Background:
    path: Path
    offset: float        # seconds into the file
    category: str
    credit: str          # attribution line for the description (CC BY)


def load_manifest(bg_dir: Path = BG_DIR) -> list[dict]:
    f = bg_dir / "manifest.json"
    if not f.exists():
        return []
    items = json.loads(f.read_text(encoding="utf-8"))
    return [it for it in items if (bg_dir / it["file"]).exists()]


class BackgroundPicker:
    """Random clip + random offset, never the same category twice in a row."""

    def __init__(self, bg_dir: Path = BG_DIR, rng: random.Random | None = None):
        self.bg_dir = bg_dir
        self.rng = rng or random.Random()
        self.last_category = ""

    def pick(self, dur: float) -> Background | None:
        items = [it for it in load_manifest(self.bg_dir) if it.get("duration", 0) > dur + 2]
        if not items:
            return None
        fresh = [it for it in items if it.get("category") != self.last_category] or items
        cats = sorted({it["category"] for it in fresh})
        cat = self.rng.choice(cats)
        it = self.rng.choice([x for x in fresh if x["category"] == cat])
        self.last_category = cat
        offset = self.rng.uniform(0, it["duration"] - dur - 1)
        return Background(self.bg_dir / it["file"], round(offset, 2), cat, it.get("credit", ""))


def prepare(src: Path, dst: Path) -> float:
    """Center-crop a 16:9 gameplay video to the 1080x960 panel, 60 fps, no audio. Returns duration."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = (f"crop='min(iw,ih*{PANEL_W}/{PANEL_H})':ih,scale={PANEL_W}:{PANEL_H}:flags=lanczos,"
          f"fps=60,format=yuv420p")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", "-vf", vf, "-c:v", "h264_nvenc",
           "-preset", "p5", "-rc", "vbr", "-cq", "25", "-b:v", "0", "-maxrate", "8M", "-bufsize", "16M",
           "-g", "60", "-movflags", "+faststart", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=BELOW_NORMAL | NO_WINDOW)
    if r.returncode != 0:
        cmd[cmd.index("h264_nvenc"):cmd.index("-g")] = ["libx264", "-preset", "medium", "-crf", "23"]
        subprocess.run(cmd, check=True, capture_output=True, creationflags=BELOW_NORMAL | NO_WINDOW)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(dst)], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    return float(out or 0)
