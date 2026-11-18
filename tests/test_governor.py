from clipforge.governor import Governor


class Probe:
    def __init__(self):
        self.gpu = 5.0
        self.cpu = 10.0
        self.fullscreen = False
        self.ours_busy = False


def gov(p, t):
    return Governor(probe_gpu=lambda: p.gpu, probe_cpu=lambda: p.cpu, probe_fullscreen=lambda: p.fullscreen,
                    ours_busy=lambda: p.ours_busy, clock=lambda: t[0])


def test_normal_when_idle():
    p, t = Probe(), [0.0]
    assert gov(p, t).state() == "normal"


def test_busy_when_foreign_gpu_load():
    p, t = Probe(), [0.0]
    p.gpu = 80
    assert gov(p, t).state() == "busy"


def test_own_gpu_work_does_not_count():
    p, t = Probe(), [0.0]
    p.gpu, p.ours_busy = 80, True
    assert gov(p, t).state() == "normal"


def test_busy_when_fullscreen_app_and_stays_busy_for_two_minutes():
    p, t = Probe(), [0.0]
    g = gov(p, t)
    p.fullscreen = True
    assert g.state() == "busy"
    p.fullscreen = False
    t[0] = 60
    assert g.state() == "busy"
    t[0] = 200
    assert g.state() == "normal"


def test_live_capacity_capped_when_busy():
    p, t = Probe(), [0.0]
    g = gov(p, t)
    p.gpu = 90
    assert g.live_capacity(normal=8, busy=3) == 3
