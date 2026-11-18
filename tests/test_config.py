from pathlib import Path
from clipforge.config import load_config


def test_defaults(tmp_path: Path):
    p = tmp_path / "config.yaml"
    p.write_text("streamers:\n  KaiCenat: 1.5\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.posting.per_day == 8
    assert cfg.clip.pre_roll == 20
    assert cfg.clip.chat_lag == 7
    assert cfg.streamers == {"kaicenat": 1.5}
    assert cfg.youtube.privacy == "private"


def test_override_nested(tmp_path: Path):
    p = tmp_path / "config.yaml"
    p.write_text("posting:\n  per_day: 5\ncapacity:\n  live: 4\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.posting.per_day == 5
    assert cfg.posting.min_gap_minutes == 60
    assert cfg.capacity.live == 4
