from clipforge.config import Posting
from clipforge.scheduler import Candidate, Scheduler

H = 3600.0
NOW = 1_000_000.0


def up(channel, ago_h, exceptional=False):
    return {"channel": channel, "published_at": NOW - ago_h * H, "exceptional": int(exceptional)}


def c(mid, channel, score, age_h=0.1):
    return Candidate(moment_id=mid, channel=channel, score=score, event_time=NOW - age_h * H)


def test_picks_best_fresh_candidate():
    s = Scheduler(Posting())
    pick = s.pick([c(1, "a", 0.6), c(2, "b", 0.8), c(3, "c", 0.85, age_h=12)], NOW, [])
    assert pick.moment_id == 2


def test_daily_budget_blocks_ninth_normal_post():
    s = Scheduler(Posting())
    hist = [up(f"s{i}", 23 - i * 2) for i in range(8)]
    assert s.pick([c(1, "new", 0.7)], NOW, hist) is None


def test_exceptional_bypasses_budget_up_to_three():
    s = Scheduler(Posting())
    hist = [up(f"s{i}", 23 - i * 2) for i in range(8)]
    assert s.pick([c(1, "new", 0.95)], NOW, hist).moment_id == 1
    hist += [up("x", 0.5, True), up("y", 0.4, True), up("z", 0.3, True)]
    assert s.pick([c(1, "new", 0.95)], NOW, hist) is None


def test_min_gap_between_normal_posts():
    s = Scheduler(Posting())
    assert s.pick([c(1, "a", 0.7)], NOW, [up("b", 0.5)]) is None
    assert s.pick([c(1, "a", 0.7)], NOW, [up("b", 1.1)]).moment_id == 1


def test_not_same_streamer_twice_in_a_row():
    s = Scheduler(Posting())
    assert s.pick([c(1, "a", 0.7)], NOW, [up("a", 2)]) is None


def test_per_streamer_daily_cap():
    s = Scheduler(Posting())
    hist = [up("a", 20), up("b", 15), up("a", 10), up("b", 8), up("a", 5), up("b", 2)]
    assert s.pick([c(1, "a", 0.8)], NOW, hist) is None


def test_below_min_score_never_posts():
    s = Scheduler(Posting())
    assert s.pick([c(1, "a", 0.3)], NOW, []) is None
