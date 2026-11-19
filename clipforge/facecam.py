"""Find a streamer's facecam: a face that stays put across frames (spec §6.7)."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .config import ROOT
from .recorder import NO_WINDOW

log = logging.getLogger(__name__)
MODEL = ROOT / "assets" / "models" / "face_detection_yunet_2023mar.onnx"
PANEL_ASPECT = 1080 / 672


def sample_frames(path: Path, count: int = 12, width: int = 960) -> list[np.ndarray]:
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(path)], capture_output=True, text=True, creationflags=NO_WINDOW).stdout or 0)
    frames = []
    for i in range(count):
        t = dur * (i + 0.5) / count
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                            "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                           capture_output=True, creationflags=NO_WINDOW)
        if r.stdout:
            img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                frames.append(img)
    return frames


def find_facecam(frames: list[np.ndarray], src_w: int, src_h: int) -> tuple[int, int, int, int] | None:
    """Return (x, y, w, h) in source pixels for the facecam crop, or None."""
    face = find_face(frames, src_w, src_h)
    return facecam_box(face, src_w, src_h) if face else None


def facecam_box(face: tuple[int, int, int], src_w: int, src_h: int) -> tuple[int, int, int, int]:
    """Wide crop (for the full-width stack panel) around a face given as (cx, cy, face_w) in source px."""
    cx, cy, fw = face
    cw = min(fw * 4.3, src_w * 0.5)
    ch = cw / PANEL_ASPECT
    x = int(np.clip(cx - cw / 2, 0, src_w - cw))
    y = int(np.clip(cy - ch * 0.45, 0, src_h - ch))
    return x, y, int(min(cw, src_w)), int(min(ch, src_h))


def inset_box(face: tuple[int, int, int], src_w: int, src_h: int, aspect: float = PANEL_ASPECT,
              zoom: float = 2.8) -> tuple[int, int, int, int]:
    """Tight crop centred on the face, for the small webcam inset of the split layout."""
    cx, cy, fw = face
    cw = min(fw * zoom, src_w * 0.35)
    ch = cw / aspect
    x = int(np.clip(cx - cw / 2, 0, src_w - cw))
    y = int(np.clip(cy - ch * 0.45, 0, src_h - ch))
    return x, y, int(cw) // 2 * 2, int(ch) // 2 * 2


def find_face(frames: list[np.ndarray], src_w: int, src_h: int) -> tuple[int, int, int] | None:
    """Return the streamer's face as (center_x, center_y, face_width) in source pixels, or None."""
    if not frames or not MODEL.exists():
        return None
    h, w = frames[0].shape[:2]
    det = cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), 0.75, 0.3, 50)
    hits = []
    for img in frames:
        if img.shape[:2] != (h, w):
            img = cv2.resize(img, (w, h))
        _, faces = det.detect(img)
        if faces is None:
            continue
        for f in faces:
            fx, fy, fw, fh, score = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14])
            if 0.03 * w <= fw <= 0.25 * w:
                hits.append((fx + fw / 2, fy + fh / 2, fw, fh, score))
    if not hits:
        return None
    arr = np.array(hits)
    best = None
    for cx, cy, fw, fh, _ in hits:          # cluster: faces whose center stays within 6% of frame width
        near = arr[np.hypot(arr[:, 0] - cx, arr[:, 1] - cy) < 0.06 * w]
        if best is None or len(near) > len(best):
            best = near
    if best is None or len(best) < max(3, 0.5 * len(frames)):
        return None
    cx, cy, fw = float(np.median(best[:, 0])), float(np.median(best[:, 1])), float(np.median(best[:, 2]))
    scale = src_w / w
    return int(cx * scale), int(cy * scale), int(fw * scale)
