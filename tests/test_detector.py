import random

from clipforge.chat import ChatEvent
from clipforge.config import ClipCfg
from clipforge.detector import ChannelDetector

T0 = 1_700_000_000.0


def msg(t, user, text):
    return ChatEvent(kind="msg", channel="c", ts=t, user=user, text=text, extra={"login": user})


def baseline(det, start, seconds, users=100, rate=5, rng=None):
    rng = rng or random.Random(1)
    neutral = ["hello chat", "what is this mission", "he is driving", "nice car", "gg", "where is he going",
               "chat is this real", "the map is huge", "first time here", "this game looks good"]
    for s in range(seconds):
        for k in range(rate):
            det.feed(msg(start + s + k / rate, f"u{rng.randrange(users)}", rng.choice(neutral)))
    return start + seconds


def flood(det, start, seconds, users, rate=60, text="KEKW", rng=None):
    rng = rng or random.Random(2)
    for s in range(seconds):
        for k in range(rate):
            det.feed(msg(start + s + k / rate, rng.choice(users), text))
    return start + seconds


def run_ticks(det, start, end):
    out = []
    t = start
    while t <= end:
        out += det.tick(t)
        t += 1
    return out


def test_laugh_flood_gives_one_funny_moment():
    det = ChannelDetector("c", ClipCfg())
    t = baseline(det, T0, 900)
    burst_start = t
    t = flood(det, t, 10, [f"u{i}" for i in range(50)])
    t = baseline(det, t, 60, rng=random.Random(3))
    moments = run_ticks(det, T0, t + 5)
    assert len(moments) == 1
    m = moments[0]
    assert m.category == "funny"
    assert abs(m.t_on - burst_start) <= 1.5
    assert abs(m.t_event - (m.t_on - 7)) <= 1.0


def test_raid_flood_from_new_users_is_ignored():
    det = ChannelDetector("c", ClipCfg())
    t = baseline(det, T0, 900)
    det.feed(ChatEvent(kind="raid", channel="c", ts=t, extra={"viewers": 500}))
    t = flood(det, t + 1, 10, [f"raider{i}" for i in range(50)], text="kaiRaid kaiRaid")
    t = baseline(det, t, 60, rng=random.Random(3))
    assert run_ticks(det, T0, t + 5) == []


def test_single_spammer_is_ignored():
    det = ChannelDetector("c", ClipCfg())
    t = baseline(det, T0, 900)
    t = flood(det, t, 10, ["u7"], text="KEKW")
    t = baseline(det, t, 60, rng=random.Random(3))
    assert run_ticks(det, T0, t + 5) == []


def test_two_close_bursts_merge_into_one():
    det = ChannelDetector("c", ClipCfg())
    t = baseline(det, T0, 900)
    users = [f"u{i}" for i in range(50)]
    t = flood(det, t, 8, users)
    t = baseline(det, t, 10, rng=random.Random(4))
    t = flood(det, t, 8, users, text="OMEGALUL")
    t = baseline(det, t, 70, rng=random.Random(5))
    assert len(run_ticks(det, T0, t + 5)) == 1


def test_bots_and_commands_do_not_count():
    det = ChannelDetector("c", ClipCfg(), bots={"nightbot"})
    t = baseline(det, T0, 900)
    for s in range(10):
        for k in range(60):
            det.feed(msg(t + s + k / 60, f"u{k % 50}", "!drop"))
    t = baseline(det, t + 10, 60, rng=random.Random(3))
    assert run_ticks(det, T0, t + 5) == []


def test_moment_carries_top_chat_lines():
    det = ChannelDetector("c", ClipCfg())
    t = baseline(det, T0, 900)
    t = flood(det, t, 10, [f"u{i}" for i in range(50)], text="KEKW")
    t = baseline(det, t, 60, rng=random.Random(3))
    m = run_ticks(det, T0, t + 5)[0]
    assert m.features["chat_lines"][0].lower() == "kekw"


def test_cooldown_suppresses_second_moment_within_90s():
    det = ChannelDetector("c", ClipCfg())
    t = baseline(det, T0, 900)
    users = [f"u{i}" for i in range(50)]
    t = flood(det, t, 8, users)
    t = baseline(det, t, 30, rng=random.Random(4))
    t = flood(det, t, 8, users, text="OMEGALUL")
    t = baseline(det, t, 80, rng=random.Random(5))
    assert len(run_ticks(det, T0, t + 5)) == 1
