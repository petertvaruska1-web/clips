"""Clip window choice and final scoring (spec §6.4 event timing, §6.6 final score)."""
from __future__ import annotations

import numpy as np

from .audio import reaction_end, snap_event
from .config import ClipCfg
from .transcribe import Word

WEIGHTS = {"hype": 0.35, "burst": 0.15, "viewer_clips": 0.20, "audio": 0.10, "ai": 0.20}


def _sentence_starts(words: list[Word]) -> list[float]:
    out = []
    for i, w in enumerate(words):
        if i == 0 or words[i - 1].text[-1:] in ".?!" or w.start - words[i - 1].end >= 0.35:
            out.append(w.start)
    return out


def choose_window(words: list[Word], t: np.ndarray, db: np.ndarray, ev_guess: float, peak_rel: float,
                  rise_time: float, cfg: ClipCfg, raw_len: float) -> tuple[float, float, float, float]:
    """All times are seconds into the raw clip. peak_rel is the chat peak already shifted by chat lag.
    Returns (start, end, event, audio_strength)."""
    ev, strength = snap_event(t, db, ev_guess) if len(t) else (ev_guess, 0.0)
    pre = cfg.pre_roll_slow if rise_time > 6 else cfg.pre_roll
    s0 = max(0.0, ev - pre)
    starts = [x for x in _sentence_starts(words) if s0 - 4 <= x <= s0 + 2 and ev - x >= cfg.keep_before_event]
    if starts:
        s = min(starts, key=lambda x: abs(x - s0))
    else:
        inside = [w for w in words if w.start < s0 < w.end]
        s = inside[0].start if inside else s0
    s = max(0.0, s)

    e_min = max(ev + 6.0, peak_rel + 2.0, s + cfg.min_len)
    e_max = min(raw_len, s + cfg.max_len)
    e_min = min(e_min, e_max)
    e = reaction_end(t, db, ev, e_min, e_max) if len(t) else e_min
    for w in words:
        if w.start < e < w.end:
            e = min(e_max, w.end + 0.2)
            break
    if e - s > cfg.target_max:
        s = max(s, e - cfg.target_max)
        s = min(s, max(0.0, ev - cfg.keep_before_event))
        e = min(e, s + cfg.target_max)
    if e - s < cfg.min_len:
        e = min(raw_len, s + cfg.min_len)
    return round(s, 2), round(e, 2), round(ev, 2), strength


def final_score(hype: float, burst: float, viewer_clips: float | None, audio: float | None,
                watchability: float | None, weight: float) -> float:
    vals = {"hype": hype, "burst": burst, "viewer_clips": viewer_clips, "audio": audio,
            "ai": None if watchability is None else watchability / 10.0}
    used = {k: v for k, v in vals.items() if v is not None}
    total_w = sum(WEIGHTS[k] for k in used)
    base = sum(WEIGHTS[k] * float(np.clip(v, 0, 1)) for k, v in used.items()) / total_w if total_w else 0.0
    return float(np.clip(base * (1 + 0.3 * (weight - 1)), 0, 1))
