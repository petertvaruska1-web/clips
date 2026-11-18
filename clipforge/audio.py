"""Audio loudness curve, event-transient snapping and reaction-end detection (spec §6.4/§6.6)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .recorder import BELOW_NORMAL, NO_WINDOW

HOP = 0.1  # seconds


def loudness_curve(path: Path, sr: int = 16000) -> tuple[np.ndarray, np.ndarray]:
    """Return (times, dBFS) at 10 Hz for the file's first audio stream."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
                        "-f", "s16le", "pipe:1"], capture_output=True, creationflags=BELOW_NORMAL | NO_WINDOW)
    pcm = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(sr * HOP)
    n = len(pcm) // hop
    if n == 0:
        return np.zeros(0), np.zeros(0)
    frames = pcm[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-6
    return np.arange(n) * HOP, 20 * np.log10(rms)


def _smooth(db: np.ndarray, width: int) -> np.ndarray:
    if len(db) < width:
        return db
    k = np.ones(width) / width
    return np.convolve(db, k, mode="same")


def snap_event(t: np.ndarray, db: np.ndarray, t_guess: float, before: float = 8.0, after: float = 3.0,
               min_jump: float = 6.0) -> tuple[float, float]:
    """Find the strongest loudness rise in [t_guess-before, t_guess+after]."""
    if len(t) == 0:
        return t_guess, 0.0
    best_i, best_jump = -1, 0.0
    for i in np.nonzero((t >= t_guess - before) & (t <= t_guess + after))[0]:
        if i < 15:
            continue
        prior = float(np.median(db[i - 15:i - 3]))
        now = float(np.median(db[i:i + 3]))
        jump = now - prior
        if jump > best_jump + 0.5:
            best_i, best_jump = i, jump
    if best_i < 0 or best_jump < min_jump:
        return t_guess, 0.0
    return float(t[best_i]), round(best_jump, 2)


def reaction_end(t: np.ndarray, db: np.ndarray, t_event: float, t_min_end: float, t_max_end: float,
                 quiet_for: float = 1.5, margin_db: float = 4.0) -> float:
    """First time >= t_min_end when smoothed loudness stays near the pre-event baseline for quiet_for s."""
    if len(t) == 0:
        return t_min_end
    pre = db[(t >= t_event - 12) & (t < t_event - 1)]
    base = float(np.median(pre)) if len(pre) else float(np.median(db))
    sm = _smooth(db, 10)
    need = int(quiet_for / HOP)
    run = 0
    for i in np.nonzero((t >= t_min_end) & (t <= t_max_end))[0]:
        run = run + 1 if sm[i] <= base + margin_db else 0
        if run >= need:
            return float(t[i - need + 1]) + 1.0
    return float(min(t_max_end, t[-1]))


def mean_excitement(t: np.ndarray, db: np.ndarray, a: float, b: float, t_event: float) -> float:
    """0..1: how much louder the reaction is than the lead-in."""
    pre = db[(t >= a) & (t < t_event - 1)]
    post = db[(t >= t_event) & (t <= b)]
    if len(pre) < 5 or len(post) < 5:
        return 0.0
    return float(np.clip((np.percentile(post, 90) - np.median(pre)) / 20.0, 0, 1))
