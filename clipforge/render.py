"""Render a 1080x1920 Short with ffmpeg in one pass (spec §6.7)."""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .background import PANEL_H, PANEL_W, Background
from .captions import build_ass
from .facecam import inset_box
from .config import ROOT
from .recorder import BELOW_NORMAL, NO_WINDOW
from .transcribe import Word

log = logging.getLogger(__name__)
FONTS_DIR = ROOT / "assets" / "fonts"
TOP_H = 672           # stack layout: facecam panel height (35%)
BOT_H = 1920 - TOP_H  # gameplay panel
PUNCH = 1.08
PUNCH_HOLD = 1.6
CAM_W = 400            # split layout: webcam inset width
CAM_MARGIN = 30
CAM_BORDER = 5
GAME_ZOOM = 1.15      # split layout: zoom on the stream gameplay
INSET_ZOOM = 0.62      # inset shows the central 62% of the facecam crop


@dataclass
class RenderJob:
    raw_path: Path
    a: float                       # clip start, seconds into raw file
    b: float                       # clip end
    t_event: float                 # event time, seconds into raw file
    layout: str                    # "stack" | "fill" (original style) | "split" (needs bg)
    out_path: Path
    facecam: tuple[int, int, int, int] | None = None   # x, y, w, h in source pixels
    words: list[Word] = field(default_factory=list)   # times in raw-file seconds
    hook: str = ""
    credit: str = ""
    prefer_nvenc: bool = True
    bg: Background | None = None   # split layout: satisfying gameplay for the bottom half
    face: tuple[int, int, int] | None = None   # streamer's face (cx, cy, face_w) in source pixels


def cam_side(job: RenderJob, src_w: int) -> str:
    if not job.facecam:
        return ""
    fx, _, fw, _ = job.facecam
    return "left" if fx + fw / 2 < src_w / 2 else "right"


def split_ass_layout(job: RenderJob, src_w: int) -> dict:
    """Caption/hook/credit placement for the split layout: captions sit on the seam."""
    side = cam_side(job, src_w)
    cam_h = _even(CAM_W / (1080 / 672))
    return {"cap_y": PANEL_H, "hook_y": CAM_MARGIN + cam_h + 110 if side else 200,
            "credit_an": 9 if side == "left" else 7}


def build_split_filter(job: RenderJob, src_w: int, src_h: int, ass_path: Path, dur: float) -> str:
    """Top half: stream gameplay (+ webcam inset). Bottom half: background gameplay. Captions on the seam."""
    te = max(0.0, job.t_event - job.a)
    # slight zoom on the stream gameplay: streamers park chat, alerts and the webcam at the edges
    gh = _even(src_h / GAME_ZOOM)
    gw = _even(min(src_w, gh * PANEL_W / PANEL_H))
    gx, gy = (src_w - gw) / 2, _even((src_h - gh) / 2)
    side = cam_side(job, src_w)
    if side:   # nudge the crop a little away from the facecam so it isn't shown twice
        fx, _, fw, _ = job.facecam
        cap = 60 * src_w / 1920
        if side == "left":
            gx = min(gx + cap, max(gx, fx + fw), src_w - gw)
        else:
            gx = max(gx - cap, min(gx, fx - gw), 0)
    gx = _even(gx)
    pw, ph = _even(PANEL_W * PUNCH), _even(PANEL_H * PUNCH)
    f = (f"[0:v]trim=start={job.a:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS[vin];"
         + ("[vin]split=2[cam][game];" if side else "[vin]null[game];")
         + f"[game]crop={gw}:{gh}:{gx}:{gy},scale={PANEL_W}:{PANEL_H}:flags=lanczos,setsar=1[g0];"
         f"[g0]split=2[gn][gz];[gz]scale={pw}:{ph},crop={PANEL_W}:{PANEL_H}[gzz];"
         f"[gn][gzz]overlay=0:0:enable='between(t,{te:.2f},{te + PUNCH_HOLD:.2f})'[g1];")
    if side:
        ch = _even(CAM_W / (1080 / 672))
        if job.face:
            fx, fy, fw, fh = inset_box(job.face, src_w, src_h, aspect=CAM_W / ch)
        else:   # older cache entries: zoom into the middle of the wide facecam crop
            fx, fy, fw, fh = job.facecam
            cx, cy = fx + fw / 2, fy + fh * 0.45
            fw, fh = _even(fw * INSET_ZOOM), _even(fh * INSET_ZOOM)
            fx = int(min(max(0, cx - fw / 2), src_w - fw))
            fy = int(min(max(0, cy - fh * 0.45), src_h - fh))
        x = CAM_MARGIN if side == "left" else PANEL_W - CAM_W - CAM_MARGIN
        b = CAM_BORDER
        f += (f"[cam]crop={_even(fw)}:{_even(fh)}:{fx}:{fy},scale={CAM_W - 2 * b}:{ch - 2 * b}:"
              f"force_original_aspect_ratio=increase,crop={CAM_W - 2 * b}:{ch - 2 * b},"
              f"pad={CAM_W}:{ch}:{b}:{b}:color=white@0.9,setsar=1[ci];"
              f"[g1][ci]overlay={x}:{CAM_MARGIN}[top];")
    else:
        f += "[g1]null[top];"
    f += (f"[1:v]trim=duration={dur:.3f},setpts=PTS-STARTPTS,scale={PANEL_W}:{PANEL_H},setsar=1[bot];"
          f"[top][bot]vstack=inputs=2[st];")
    ass = ass_path.as_posix().replace(":", r"\:")
    fonts = FONTS_DIR.as_posix().replace(":", r"\:")
    return f + f"[st]ass='{ass}':fontsdir='{fonts}',format=yuv420p[vout]"


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
    # Frame-accurate cut inside the filter graph (no input seeking: Twitch keyframes are 2 s apart and
    # seeking into an MPEG-TS mid-GOP leaves the first frame frozen until the next keyframe).
    cut = f"[0:v]trim=start={job.a:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS[vin];"
    if job.layout == "stack" and job.facecam:
        fx, fy, fw, fh = job.facecam
        # gameplay crop: full height, width matching the panel aspect, centered
        gw = _even(min(src_w, src_h * 1080 / BOT_H))
        gx = _even((src_w - gw) / 2)
        base = (cut + f"[vin]split=2[cam][game];"
                f"[cam]crop={_even(fw)}:{_even(fh)}:{fx}:{fy},scale=1080:{TOP_H}:force_original_aspect_ratio=increase,"
                f"crop=1080:{TOP_H}[top];"
                f"[game]crop={gw}:{_even(src_h)}:{gx}:0,scale=1080:{BOT_H}[bot];"
                f"[top][bot]vstack=inputs=2[st]")
    else:
        fg_w = _even(src_w / 1.2 * 1.0)
        fg_h = _even(src_h / 1.2)
        base = (cut + f"[vin]split=2[bgsrc][fgsrc];"
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
    split = job.layout == "split" and job.bg is not None
    if job.layout == "split" and not split:
        job.layout = "stack" if job.facecam else "fill"
    place = split_ass_layout(job, info["w"]) if split else {}
    ass_path.write_text(build_ass(job.words, job.a, job.hook, job.credit, job.layout, clip_len=dur, **place),
                        encoding="utf-8")
    vf = (build_split_filter if split else build_filter)(job, info["w"], info["h"], ass_path, dur)
    bg_in = ["-ss", f"{job.bg.offset:.2f}", "-t", f"{dur + 1:.2f}", "-i", str(job.bg.path)] if split else []
    af = (f"[0:a]atrim=start={job.a:.3f}:duration={dur:.3f},asetpts=PTS-STARTPTS,"
          f"loudnorm=I=-14:TP=-1:LRA=11,aresample=48000,afade=t=in:d=0.15,"
          f"afade=t=out:st={max(0.0, dur - 0.25):.2f}:d=0.25[aout]")
    last_err = ""
    for enc in _encoders(job.prefer_nvenc):
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(job.raw_path), *bg_in,
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
