"""Configuration: config.yaml (user-editable) + secrets/*.json, with defaults from the design spec."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Capacity:
    live: int = 8            # Tier A: live recorded streams
    chat_only: int = 25      # Tier B: chat-only streams
    busy_live: int = 3       # Tier A cap while the PC is busy / gaming
    min_viewers: int = 1500  # ignore tiny streams


@dataclass
class ClipCfg:
    pre_roll: float = 20.0
    pre_roll_slow: float = 27.0
    chat_lag: float = 7.0
    min_len: float = 15.0
    max_len: float = 60.0
    target_max: float = 45.0
    keep_before_event: float = 10.0
    quality: str = "1080p60,720p60,best"


@dataclass
class Posting:
    per_day: int = 8
    min_gap_minutes: int = 60
    exceptional_extra: int = 3
    exceptional_score: float = 0.9
    per_streamer_day: int = 3
    min_score: float = 0.45
    min_watchability: float = 5.0
    half_life_hours: float = 6.0


@dataclass
class YouTubeCfg:
    privacy: str = "private"   # dry run first; switch to "public"
    category_id: str = "20"
    extra_hashtags: list[str] = field(default_factory=lambda: ["#GTA6", "#GTAVI", "#Shorts"])


@dataclass
class DiskCfg:
    max_gb: float = 15.0
    min_free_gb: float = 5.0
    keep_uploaded_days: float = 3.0


@dataclass
class Secrets:
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    groq_api_key: str = ""
    gemini_api_key: str = ""


@dataclass
class Config:
    streamers: dict[str, float] = field(default_factory=dict)
    blocklist: list[str] = field(default_factory=list)
    bots: list[str] = field(default_factory=lambda: [
        "nightbot", "streamelements", "fossabot", "moobot", "sery_bot", "streamlabs",
        "wizebot", "botrixoficial", "soundalerts", "pokemoncommunitygame", "kofistreambot"])
    game_name: str = "Grand Theft Auto VI"
    language: str = "en"
    capacity: Capacity = field(default_factory=Capacity)
    clip: ClipCfg = field(default_factory=ClipCfg)
    posting: Posting = field(default_factory=Posting)
    youtube: YouTubeCfg = field(default_factory=YouTubeCfg)
    disk: DiskCfg = field(default_factory=DiskCfg)
    secrets: Secrets = field(default_factory=Secrets)
    data_dir: Path = ROOT / "data"
    secrets_dir: Path = ROOT / "secrets"


def _merge(dc: Any, values: dict) -> Any:
    for f in fields(dc):
        if f.name not in values:
            continue
        cur = getattr(dc, f.name)
        val = values[f.name]
        if is_dataclass(cur) and isinstance(val, dict):
            _merge(cur, val)
        elif isinstance(cur, Path):
            setattr(dc, f.name, Path(val))
        else:
            setattr(dc, f.name, val)
    return dc


def load_config(path: Path | str = ROOT / "config.yaml") -> Config:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    cfg = _merge(Config(), raw or {})
    cfg.streamers = {k.lower(): float(v) for k, v in (cfg.streamers or {}).items()}
    cfg.blocklist = [b.lower() for b in cfg.blocklist]
    cfg.bots = [b.lower() for b in cfg.bots]
    sfile = Path(cfg.secrets_dir) / "secrets.json"
    if sfile.exists():
        _merge(cfg.secrets, json.loads(sfile.read_text(encoding="utf-8")))
    return cfg
