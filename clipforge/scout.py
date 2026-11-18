"""Stream selection (spec §6.1): Tier A = live recorded, Tier B = chat only."""
from __future__ import annotations

from dataclasses import dataclass, field

HOLD_SECONDS = 15 * 60


@dataclass
class Tiers:
    a: list[str] = field(default_factory=list)
    b: list[str] = field(default_factory=list)
    since: dict[str, float] = field(default_factory=dict)   # channel -> time it entered tier A
    info: dict[str, dict] = field(default_factory=dict)      # channel -> latest stream record


def choose_tiers(streams: list[dict], weights: dict[str, float], n_a: int, n_b: int,
                 current: Tiers, now: float, min_viewers: int = 0,
                 blocklist: set[str] | None = None) -> Tiers:
    blocklist = blocklist or set()
    live = {}
    for st in streams:
        login = st["user_login"].lower()
        if login in blocklist or st.get("viewer_count", 0) < min_viewers:
            continue
        live[login] = st
    prio = {c: live[c]["viewer_count"] * weights.get(c, 1.0) for c in live}
    ranked = sorted(prio, key=prio.get, reverse=True)

    keep = [c for c in current.a if c in live and now - current.since.get(c, now) < HOLD_SECONDS]
    a = keep[:n_a]
    for c in ranked:
        if len(a) >= n_a:
            break
        if c not in a:
            a.append(c)
    a.sort(key=lambda c: prio[c], reverse=True)
    b = [c for c in ranked if c not in a][:n_b]
    since = {c: current.since.get(c, now) if c in current.a else now for c in a}
    return Tiers(a=a, b=b, since=since, info={c: live[c] for c in a + b})
