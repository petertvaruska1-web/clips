import numpy as np

from clipforge.config import ClipCfg
from clipforge.pipeline import choose_window, final_score
from clipforge.transcribe import Word


def speech(start, end, step=0.4, sentence_every=6):
    words, t, i = [], start, 0
    while t < end:
        i += 1
        words.append(Word(t, t + 0.3, "word." if i % sentence_every == 0 else "word"))
        t += step
    return words


def curve(event=30.0, react_end=36.0, total=70.0):
    t = np.arange(0, total, 0.1)
    db = np.full_like(t, -38.0) + np.random.default_rng(1).normal(0, 0.8, len(t))
    db[(t >= event) & (t < react_end)] = -12.0
    return t, db


def test_window_starts_about_20s_before_event_on_sentence_start():
    t, db = curve()
    words = speech(0, 60)
    s, e, ev, strength = choose_window(words, t, db, ev_guess=31.0, peak_rel=38.0, rise_time=2.0,
                                       cfg=ClipCfg(), raw_len=70.0)
    assert abs(ev - 30.0) < 0.5 and strength > 10
    assert 8.0 <= s <= 13.0
    starts_sentence = any(abs(w.start - s) < 0.05 and (i == 0 or words[i - 1].text.endswith(".") or
                          w.start - words[i - 1].end >= 0.35) for i, w in enumerate(words))
    assert starts_sentence
    assert e >= 36.0 and 15.0 <= e - s <= 60.0


def test_window_never_exceeds_max_length():
    t, db = curve(event=30.0, react_end=69.0)
    s, e, _, _ = choose_window([], t, db, ev_guess=30.0, peak_rel=40.0, rise_time=2.0, cfg=ClipCfg(),
                               raw_len=70.0)
    assert e - s <= 45.0 + 0.01 and 30.0 - s >= 10.0


def test_window_with_no_audio_or_words_uses_defaults():
    s, e, ev, strength = choose_window([], np.zeros(0), np.zeros(0), ev_guess=25.0, peak_rel=32.0,
                                       rise_time=2.0, cfg=ClipCfg(), raw_len=50.0)
    assert ev == 25.0 and strength == 0.0 and s == 5.0 and e - s >= 15.0


def test_final_score_renormalizes_missing_ai():
    with_ai = final_score(hype=0.9, burst=0.5, viewer_clips=None, audio=0.6, watchability=8.0, weight=1.0)
    without = final_score(hype=0.9, burst=0.5, viewer_clips=None, audio=0.6, watchability=None, weight=1.0)
    assert 0 < without <= 1 and 0 < with_ai <= 1


def test_final_score_boosts_priority_streamers():
    a = final_score(hype=0.8, burst=0.5, viewer_clips=0.3, audio=0.5, watchability=6, weight=1.0)
    b = final_score(hype=0.8, burst=0.5, viewer_clips=0.3, audio=0.5, watchability=6, weight=1.5)
    assert b > a
