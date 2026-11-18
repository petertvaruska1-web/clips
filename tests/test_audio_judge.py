import numpy as np

from clipforge.audio import reaction_end, snap_event
from clipforge.judge import JudgeContext, judge, clean_title


def curve(seconds=40, loud=((12, 15),), base=-40.0, peak=-10.0):
    t = np.arange(0, seconds, 0.1)
    db = np.full_like(t, base) + np.random.default_rng(0).normal(0, 1, len(t))
    for a, b in loud:
        db[(t >= a) & (t < b)] = peak
    return t, db


def test_snap_event_finds_transient_in_window():
    t, db = curve()
    snapped, strength = snap_event(t, db, t_guess=14.0)
    assert abs(snapped - 12.0) <= 0.3 and strength > 15


def test_snap_event_keeps_guess_when_nothing_loud():
    t, db = curve(loud=())
    assert snap_event(t, db, t_guess=14.0) == (14.0, 0.0)


def test_reaction_end_after_energy_returns_to_baseline():
    t, db = curve(loud=((12, 20),))
    end = reaction_end(t, db, t_event=12.0, t_min_end=16.0, t_max_end=35.0)
    assert 20.0 <= end <= 23.0


def test_judge_without_keys_uses_template():
    v = judge(JudgeContext(streamer="kaicenat", display="Kai Cenat", category="funny",
                           transcript="bro what is he doing", chat_lines=["KEKW", "LMAO"]), keys={})
    assert "Kai Cenat" in v.title and "GTA 6" in v.title
    assert v.watchability is None and v.hook


def test_clean_title_strips_profanity_and_limits_length():
    t = clean_title("Kai Cenat says fuck this shit in GTA 6 " + "x" * 120)
    assert "fuck" not in t.lower() and "shit" not in t.lower() and len(t) <= 90
