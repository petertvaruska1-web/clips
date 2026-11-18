"""Posting rules (spec §6.8): daily budget, spacing, exceptional fast lane, diversity, freshness."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Posting

DAY = 86400.0
EXCEPTIONAL_MIN_GAP = 10 * 60


@dataclass
class Candidate:
    moment_id: int
    channel: str
    score: float
    event_time: float


class Scheduler:
    def __init__(self, cfg: Posting):
        self.cfg = cfg

    def value(self, c: Candidate, now: float) -> float:
        age_h = max(0.0, now - c.event_time) / 3600
        return c.score * 0.5 ** (age_h / self.cfg.half_life_hours)

    def pick(self, candidates: list[Candidate], now: float, history: list[dict]) -> Candidate | None:
        day = [h for h in history if now - h["published_at"] < DAY]
        normal = [h for h in day if not h.get("exceptional")]
        exceptional = [h for h in day if h.get("exceptional")]
        last = max(history, key=lambda h: h["published_at"], default=None)
        since_last = now - last["published_at"] if last else float("inf")
        last_normal = max((h["published_at"] for h in normal), default=None)
        since_normal = now - last_normal if last_normal else float("inf")
        per_ch: dict[str, int] = {}
        for h in day:
            per_ch[h["channel"]] = per_ch.get(h["channel"], 0) + 1

        ok = []
        for c in candidates:
            if c.score < self.cfg.min_score:
                continue
            if last and last["channel"] == c.channel:
                continue
            if per_ch.get(c.channel, 0) >= self.cfg.per_streamer_day:
                continue
            normal_ok = (len(normal) < self.cfg.per_day and since_normal >= self.cfg.min_gap_minutes * 60
                         and since_last >= EXCEPTIONAL_MIN_GAP)
            exc_ok = (c.score >= self.cfg.exceptional_score and len(exceptional) < self.cfg.exceptional_extra
                      and since_last >= EXCEPTIONAL_MIN_GAP)
            if normal_ok or exc_ok:
                ok.append(c)
        return max(ok, key=lambda c: self.value(c, now), default=None)

    def is_exceptional(self, c: Candidate, now: float, history: list[dict]) -> bool:
        """True when this pick only fits through the exceptional lane."""
        day = [h for h in history if now - h["published_at"] < DAY and not h.get("exceptional")]
        last_normal = max((h["published_at"] for h in day), default=None)
        normal_ok = len(day) < self.cfg.per_day and (last_normal is None or now - last_normal >= self.cfg.min_gap_minutes * 60)
        return not normal_ok
