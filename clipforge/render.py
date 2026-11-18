"""Render a 1080x1920 Short with ffmpeg in one pass (spec §6.7)."""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .captions import build_ass
from .config import ROOT
from .recorder import BELOW_NORMAL, NO_WINDOW
from .transcribe import Word

log = logging.getLogger(__name__)
FONTS_DIR = ROOT / "assets" / "fonts"
TOP_H = 672           # stack layout: facecam panel height (35%)
BOT_H = 1920 - TOP_H  # gameplay panel
PUNCH = 1.08
PUNCH_HOLD = 1.6


@dataclass
class RenderJob:
    raw_path: Path
    a: float                       # clip start, seconds into raw file
    b: float                       # clip end
    t_event: float                 # event time, seconds into raw file
    layout: str                    # "stack" | "fill"
    out_path: Path
    facecam: tuple[int, int, int, int] | None = None   # x, y, w, h in source pixels
    words: list[Word] = field(default_factory=list)   # times in raw-file seconds
    hook: str = ""
    credit: str = ""
    prefer_nvenc: bool = True


def probe_video(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate", "-of", "json", str(path)],
                         capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    s = json.loads(out or "{}").get("streams", [{}])[0]
    num, _, den = str(s.get("r_frame_rate", "30/1")).partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return {"w": int(s.get("width", 1920)), "h": int(s.get("height", 1080)), "fps": fps}


def _even(x: float) -> int:
    return max(2, int(x) // 2 * 2)


def build_filter(job: RenderJob, src_w: int, src_h: int, ass_path: Path, dur: float) -> str:
    te = max(0.0, job.t_event - job.a)
    if job.layout == "stack" and job.facecam:
        fx, fy, fw, fh = job.facecam
        # gameplay crop: full height, width matching the panel aspect, centered
        gw = _even(min(src_w, src_h * 1080 / BOT_H))
        gx = _even((src_w - gw) / 2)
        base = (f"[0:v]split=2[cam][game];"
                f"[cam]crop={_even(fw)}:{_even(fh)}:{fx}:{fy},scale=1080:{TOP_H}:force_original_aspect_ratio=increase,"
                f"crop=1080:{TOP_H}[top];"
                f"[game]crop={gw}:{_even(src_h)}:{gx}:0,scale=1080:{BOT_H}[bot];"
                f"[top][bot]vstack=inputs=2[st]")
    else:
        fg_w = _even(src_w / 1.2 * 1.0)
        fg_h = _even(src_h / 1.2)
        base = (f"[0:v]split=2[bgsrc][fgsrc];"
                f"[bgsrc]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,"
                f"eq=brightness=-0.12:saturation=1.1,scale=1080:1920[bg];"
                f"[fgsrc]crop={fg_w}:{fg_h},scale=1080:-2[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[st]")
    zoom = (f";[st]split=2[n][z];[z]scale={_even(1080 * PUNCH)}:{_even(1920 * PUNCH)},crop=1080:1920[zz];"
            f"[n][zz]overlay=0:0:enable='between(t,{te:.2f},{te + PUNCH_HOLD:.2f})'[pz]")
    ass = ass_path.as_posix().replace(":", r"\:")
    fonts = FONTS_DIR.as_posix().replace(":", r"\:")
    return base + zoom + f";[pz]ass='{ass}':fontsdir='{fonts}',format=yuv420p[vout]"


def _encoders(prefer_nvenc: bool) -> list[list[str]]:
    x264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high"]
    nv = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0",
          "-maxrate", "16M", "-bufsize", "32M", "-profile:v", "high"]
    return [nv, x264] if prefer_nvenc else [x264]


def render_short(job: RenderJob) -> Path:
    info = probe_video(job.raw_path)
    dur = job.b - job.a
    fps = min(60.0, round(info["fps"])) or 30.0
    job.out_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path = job.out_path.with_suffix(".ass")
    ass_path.write_text(build_ass(job.words, job.a, job.hook, job.credit, job.layout, clip_len=dur),
                        encoding="utf-8")
    vf = build_filter(job, info["w"], info["h"], ass_path, dur)
    af = (f"[0:a]loudnorm=I=-14:TP=-1:LRA=11,aresample=48000,afade=t=in:d=0.15,"
          f"afade=t=out:st={max(0.0, dur - 0.25):.2f}:d=0.25[aout]")
    last_err = ""
    for enc in _encoders(job.prefer_nvenc):
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{job.a:.3f}", "-t", f"{dur:.3f}", "-i", str(job.raw_path),
               "-filter_complex", vf + ";" + af, "-map", "[vout]", "-map", "[aout]", "-r", str(int(fps)),
               *enc, "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
               "-t", f"{dur:.3f}", str(job.out_path)]
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=BELOW_NORMAL | NO_WINDOW)
        if r.returncode == 0 and job.out_path.exists():
            ass_path.unlink(missing_ok=True)
            return job.out_path
        last_err = r.stderr[-1500:]
        log.warning("render with %s failed: %s", enc[1], last_err)
    raise RuntimeError(f"render failed: {last_err}")
