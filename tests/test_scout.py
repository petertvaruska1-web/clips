from clipforge.scout import Tiers, choose_tiers


def s(login, viewers):
    return {"user_login": login, "viewer_count": viewers, "language": "en"}


def test_priority_uses_viewers_times_weight():
    streams = [s("a", 10000), s("b", 8000), s("c", 3000)]
    t = choose_tiers(streams, {"b": 1.5}, n_a=1, n_b=5, current=Tiers(), now=0, min_viewers=0)
    assert t.a == ["b"] and t.b == ["a", "c"]


def test_blocklist_and_min_viewers():
    streams = [s("a", 10000), s("b", 800)]
    t = choose_tiers(streams, {}, n_a=2, n_b=2, current=Tiers(), now=0, min_viewers=1000, blocklist={"a"})
    assert t.a == [] and t.b == []


def test_hysteresis_keeps_live_channel_for_15_minutes():
    cur = Tiers(a=["old"], since={"old": 0})
    streams = [s("new", 20000), s("old", 5000)]
    t = choose_tiers(streams, {}, n_a=1, n_b=0, current=cur, now=600, min_viewers=0)
    assert t.a == ["old"]
    t2 = choose_tiers(streams, {}, n_a=1, n_b=0, current=cur, now=1000, min_viewers=0)
    assert t2.a == ["new"]


def test_channel_that_left_is_dropped_immediately():
    cur = Tiers(a=["old"], since={"old": 0})
    t = choose_tiers([s("new", 20000)], {}, n_a=1, n_b=0, current=cur, now=10, min_viewers=0)
    assert t.a == ["new"]
