"""Per-channel moment detector (spec §6.4).

Chat is binned per second. Every signal is judged against the channel's own recent
baseline (robust median/MAD, burst seconds excluded), so small and huge chats are
treated alike. Per-user counting (each chatter counts once per window) makes a few
spammers unable to fake a moment; users first seen right after a raid are ignored.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field

import numpy as np

from .chat import ChatEvent
from .config import ClipCfg
from .lexicon import categorize, normalize

WINDOW = 5            # seconds for short-window signals
CLIP_WINDOW = 10      # seconds for "clip it" demand
BASELINE_SECONDS = 900
WARMUP_SECONDS = 300
LATE_SECONDS = 2      # wait for late messages before closing a second
THRESH_FLOOR = 0.9
THRESH_PCT = 99.3
COOLDOWN = 90
OPEN_SECONDS = 2
CLOSE_SECONDS = 4
MERGE_GAP = 20
MAX_BURST = 45
RAID_WINDOW = 120
GIFT_WINDOW = 45
BIAS = 4.0
W = dict(z_unique=1.0, z_velocity=0.6, react=0.8, clip=0.9, unison=0.5, caps=0.3)
STOP = {"the", "a", "is", "i", "he", "it", "to", "and", "this", "that", "you", "of", "in", "chat", "bro"}


@dataclass
class Moment:
    channel: str
    t_on: float
    t_peak: float
    t_event: float
    t_end_hint: float
    hype_peak: float
    burst_size: float
    category: str
    rise_time: float
    features: dict = field(default_factory=dict)


@dataclass
class _Sec:
    msgs: int = 0
    per_user: Counter = field(default_factory=Counter)
    cats: dict = field(default_factory=lambda: defaultdict(set))     # user -> categories
    tokens: dict = field(default_factory=lambda: defaultdict(set))   # user -> tokens
    caps: set = field(default_factory=set)
    punct: set = field(default_factory=set)
    texts: list = field(default_factory=list)


def _robust(hist: deque, x: float, floor: float) -> float:
    if len(hist) < 10:
        return 0.0
    arr = np.fromiter(hist, float)
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med))) * 1.4826
    return (x - med) / max(mad, floor)


def _median(hist: deque) -> float:
    return float(np.median(np.fromiter(hist, float))) if hist else 0.0


class ChannelDetector:
    def __init__(self, channel: str, cfg: ClipCfg, bots: set[str] | None = None,
                 broadcaster: str | None = None):
        self.channel = channel
        self.cfg = cfg
        self.bots = {b.lower() for b in (bots or set())}
        self.broadcaster = (broadcaster or channel).lower()
        self.secs: dict[int, _Sec] = defaultdict(_Sec)
        self.next_sec: int | None = None
        self.first_seen: dict[str, float] = {}
        self.raids: list[tuple[float, int]] = []
        self.gifts: list[tuple[float, int]] = []
        self.hist = {k: deque(maxlen=BASELINE_SECONDS) for k in
                     ("lrate", "luniq", "uniq1", "unison", "caps", "react_any")}
        self.cat_hist: dict[str, deque] = defaultdict(lambda: deque(maxlen=BASELINE_SECONDS))
        self.h_hist: deque = deque(maxlen=3600)
        self.learned: dict[str, str] = {}
        self.series: dict[int, dict] = {}     # sec -> computed features (kept ~10 min)
        self._above = 0
        self._below = 0
        self.burst: dict | None = None
        self.pending: dict | None = None      # closed burst waiting for merge gap
        self.last_emit_end = -1e18

    # ---------- input ----------
    def feed(self, ev: ChatEvent) -> None:
        if ev.kind == "raid":
            self.raids.append((ev.ts, int(ev.extra.get("viewers", 0))))
            return
        if ev.kind == "subgift":
            self.gifts.append((ev.ts, int(ev.extra.get("count", 1))))
            return
        if ev.kind != "msg":
            return
        login = str(ev.extra.get("login", "")).lower()
        if login in self.bots or login == self.broadcaster or ev.extra.get("broadcaster"):
            return
        text = ev.text.strip()
        if not text or text.startswith("!"):
            return
        if ev.user not in self.first_seen:
            self.first_seen[ev.user] = ev.ts
        if self._is_raider(ev.user, ev.ts):
            return
        s = int(ev.ts)
        if self.next_sec is not None and s < self.next_sec:
            return  # too late, second already closed
        sec = self.secs[s]
        sec.per_user[ev.user] += 1
        if len(sec.texts) < 40 and sec.per_user[ev.user] == 1:
            sec.texts.append(text[:120])
        if sec.per_user[ev.user] <= 2:
            sec.msgs += 1
        toks = normalize(text)
        cats = categorize(toks, self.learned)
        sec.cats[ev.user] |= cats
        sec.tokens[ev.user] |= {t for t in toks if t not in STOP and len(t) <= 25}
        letters = [c for c in text if c.isalpha()]
        if len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.8:
            sec.caps.add(ev.user)
        if "???" in toks or "!!!" in toks:
            sec.punct.add(ev.user)

    def _is_raider(self, user: str, ts: float) -> bool:
        for rts, _ in self.raids:
            if rts - 1 <= self.first_seen.get(user, 0) <= rts + RAID_WINDOW and ts <= rts + RAID_WINDOW:
                return True
        return False

    # ---------- per-second computation ----------
    def _window(self, s: int, n: int):
        users: set = set()
        msgs = 0
        cats: dict = defaultdict(set)
        tokens: dict = defaultdict(set)
        caps: set = set()
        for k in range(s - n + 1, s + 1):
            sec = self.secs.get(k)
            if not sec:
                continue
            msgs += sec.msgs
            users |= set(sec.per_user)
            for u, c in sec.cats.items():
                cats[u] |= c
            for u, t in sec.tokens.items():
                tokens[u] |= t
            caps |= sec.caps | sec.punct
        return users, msgs, cats, tokens, caps

    def _penalty(self, t: float) -> float:
        p = 0.0
        for rts, viewers in self.raids:
            if 0 <= t - rts <= RAID_WINDOW:
                p += min(4.0, 1.2 * math.log10(1 + viewers)) * (1 - (t - rts) / RAID_WINDOW)
        for gts, count in self.gifts:
            if 0 <= t - gts <= GIFT_WINDOW:
                p += min(3.0, 0.8 * math.log2(1 + count)) * (1 - (t - gts) / GIFT_WINDOW)
        return p

    def _compute(self, s: int) -> dict:
        users, msgs, cats, tokens, caps = self._window(s, WINDOW)
        n_users = max(len(users), 1)
        lrate = math.log1p(msgs / WINDOW)
        luniq = math.log1p(len(users) / WINDOW)
        uniq1 = len(self.secs[s].per_user) if s in self.secs else 0
        cat_share = {c: sum(1 for u in users if c in cats.get(u, ())) / n_users
                     for c in ("funny", "hype", "shock", "fail", "scare", "wholesome")}
        react_any = sum(1 for u in users if cats.get(u, set()) - {"clip"}) / n_users
        tok_count = Counter(t for u in users for t in tokens.get(u, ()))
        top_tok, top_n = (tok_count.most_common(1)[0] if tok_count else ("", 0))
        unison = top_n / n_users
        caps_share = len(caps & users) / n_users
        c_users, _, c_cats, _, _ = self._window(s, CLIP_WINDOW)
        clip_users = sum(1 for u in c_users if "clip" in c_cats.get(u, ()))

        z_u = max(-3.0, min(8.0, _robust(self.hist["luniq"], luniq, 0.12)))
        z_v = max(-3.0, min(8.0, _robust(self.hist["lrate"], lrate, 0.12)))
        lifts = {c: max(0.0, min(4.0, (v - _median(self.cat_hist[c])) / 0.12)) for c, v in cat_share.items()}
        react = max(lifts.values()) if lifts else 0.0
        clip = min(3.0, 1.2 * math.log1p(clip_users))
        uni = max(0.0, min(4.0, (unison - _median(self.hist["unison"])) / 0.12))
        capl = max(0.0, min(3.0, (caps_share - _median(self.hist["caps"])) / 0.15))
        pen = self._penalty(s)
        lin = (W["z_unique"] * z_u + W["z_velocity"] * z_v + W["react"] * react + W["clip"] * clip
               + W["unison"] * uni + W["caps"] * capl - pen - BIAS)
        # reaction signals only count when more people than usual are actually chatting
        if z_u < 1.0:
            lin = min(lin, -1.0)
        h = 1 / (1 + math.exp(-lin))
        return dict(h=h, z_u=z_u, z_v=z_v, react=react, clip=clip, unison=uni, caps=capl, pen=pen,
                    lrate=lrate, luniq=luniq, uniq1=uniq1, cat_share=cat_share, react_any=react_any,
                    unison_raw=unison, caps_raw=caps_share, top_token=top_tok, n_users=len(users))

    def _update_baseline(self, f: dict) -> None:
        self.hist["lrate"].append(f["lrate"])
        self.hist["luniq"].append(f["luniq"])
        self.hist["uniq1"].append(f["uniq1"])
        self.hist["unison"].append(f["unison_raw"])
        self.hist["caps"].append(f["caps_raw"])
        for c, v in f["cat_share"].items():
            self.cat_hist[c].append(v)

    def threshold(self) -> float:
        if len(self.h_hist) < 300:
            return THRESH_FLOOR
        return max(THRESH_FLOOR, float(np.percentile(np.fromiter(self.h_hist, float), THRESH_PCT)))

    # ---------- state machine ----------
    def tick(self, now: float) -> list[Moment]:
        out: list[Moment] = []
        last = int(now) - LATE_SECONDS
        if self.next_sec is None:
            if not self.secs:
                return out
            self.next_sec = min(self.secs)
        while self.next_sec <= last:
            s = self.next_sec
            self.next_sec += 1
            f = self._compute(s)
            self.series[s] = f
            warm = len(self.hist["luniq"]) >= WARMUP_SECONDS
            thr = self.threshold()
            in_burst = self.burst is not None
            if warm and f["h"] > thr:
                self._above += 1
                self._below = 0
            else:
                self._above = 0
                self._below = self._below + 1 if in_burst and f["h"] < 0.6 * thr else 0
            cooling = s - self.last_emit_end < COOLDOWN
            if not in_burst and warm and self._above >= OPEN_SECONDS and (self.pending or not cooling):
                if self.pending and s - self.pending["end"] <= MERGE_GAP:
                    self.burst, self.pending = self.pending, None
                else:
                    self.burst = dict(start=s - OPEN_SECONDS + 1, peak=s, peak_h=f["h"], size=0.0,
                                      cats=Counter())
            if self.burst is not None:
                b = self.burst
                if f["h"] > b["peak_h"]:
                    b["peak"], b["peak_h"] = s, f["h"]
                b["size"] += max(0.0, f["h"] - 0.6 * thr)
                for c, v in f["cat_share"].items():
                    b["cats"][c] += v
                if self._below >= CLOSE_SECONDS or s - b["start"] >= MAX_BURST:
                    b["end"] = s - self._below
                    self.pending, self.burst = b, None
                    self._below = 0
            else:
                self._update_baseline(f)
                self.h_hist.append(f["h"])
            if self.pending and self.burst is None and s - self.pending["end"] > MERGE_GAP:
                out.append(self._emit(self.pending))
                self.last_emit_end = self.pending["end"]
                self.pending = None
            self._gc(s)
        return out

    def _onset(self, peak: int, start: int) -> int:
        hist = self.hist["uniq1"]
        med = _median(hist)
        mad = float(np.median(np.abs(np.fromiter(hist, float) - med))) * 1.4826 if hist else 1.0
        level = med + 2 * max(mad, 1.0)
        s = min(peak, start + OPEN_SECONDS)
        while s - 1 >= peak - 30:
            f = self.series.get(s - 1)
            if f is None or f["uniq1"] <= level:
                break
            s -= 1
        return s

    def _emit(self, b: dict) -> Moment:
        t_on = float(self._onset(b["peak"], b["start"]))
        cats = {c: v for c, v in b["cats"].items()}
        category = max(cats, key=cats.get) if any(cats.values()) else "reaction"
        lag = self.cfg.chat_lag
        pf = self.series.get(b["peak"], {})
        lines = Counter()
        for k in range(b["start"], b["end"] + 1):
            for txt in self.secs.get(k, _Sec()).texts:
                lines[" ".join(txt.split())] += 1
        return Moment(channel=self.channel, t_on=t_on, t_peak=float(b["peak"]),
                      t_event=t_on - lag, t_end_hint=float(b["end"]) - lag + 2.0,
                      hype_peak=float(b["peak_h"]), burst_size=float(b["size"]), category=category,
                      rise_time=float(b["peak"]) - t_on,
                      features={k: pf.get(k) for k in ("z_u", "z_v", "react", "clip", "unison", "caps",
                                                       "pen", "top_token", "n_users")}
                      | {"chat_lines": [l for l, _ in lines.most_common(15)]})

    def _gc(self, s: int) -> None:
        if s % 60:
            return
        for k in [k for k in self.secs if k < s - 240]:
            del self.secs[k]
        for k in [k for k in self.series if k < s - 600]:
            del self.series[k]
        self.raids = [r for r in self.raids if s - r[0] < 3 * RAID_WINDOW]
        self.gifts = [g for g in self.gifts if s - g[0] < 3 * GIFT_WINDOW]
        if len(self.first_seen) > 200_000:
            cutoff = s - 3600
            self.first_seen = {u: t for u, t in self.first_seen.items() if t > cutoff}
