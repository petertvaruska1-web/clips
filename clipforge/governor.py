"""PC-adaptive governor (spec §6.10): detect gaming / heavy use and back off; keep PC awake while needed."""
from __future__ import annotations

import ctypes
import logging
import os
import time
from typing import Callable

log = logging.getLogger(__name__)
BUSY_HOLD = 120.0
GPU_BUSY = 50.0
CPU_BUSY = 85.0


def gpu_util() -> float:
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
    except Exception:
        return 0.0


def cpu_util() -> float:
    import psutil
    return float(psutil.cpu_percent(interval=None))


def foreground_fullscreen() -> bool:
    """True when the foreground window covers its whole monitor and isn't the desktop/shell."""
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False

        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]

        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        mon = user32.MonitorFromWindow(hwnd, 2)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(mon, ctypes.byref(mi))
        m = mi.rcMonitor
        return r.l <= m.l and r.t <= m.t and r.r >= m.r and r.b >= m.b
    except Exception:
        return False


class Governor:
    def __init__(self, probe_gpu: Callable[[], float] = gpu_util, probe_cpu: Callable[[], float] = cpu_util,
                 probe_fullscreen: Callable[[], bool] = foreground_fullscreen,
                 ours_busy: Callable[[], bool] = lambda: False, clock: Callable[[], float] = time.time):
        self.probe_gpu, self.probe_cpu, self.probe_fullscreen = probe_gpu, probe_cpu, probe_fullscreen
        self.ours_busy, self.clock = ours_busy, clock
        self._busy_until = 0.0
        self._last = "normal"

    def state(self) -> str:
        now = self.clock()
        signals = []
        if self.probe_fullscreen():
            signals.append("fullscreen app")
        if not self.ours_busy():
            if self.probe_gpu() > GPU_BUSY:
                signals.append("GPU load")
            if self.probe_cpu() > CPU_BUSY:
                signals.append("CPU load")
        if signals:
            self._busy_until = now + BUSY_HOLD
        st = "busy" if now < self._busy_until else "normal"
        if st != self._last:
            log.info("governor: %s%s", st, f" ({', '.join(signals)})" if signals else "")
            self._last = st
        return st

    def live_capacity(self, normal: int, busy: int) -> int:
        return busy if self.state() == "busy" else normal


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake(on: bool) -> None:
    """Ask Windows not to sleep while streams are followed (no settings changed)."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def set_low_priority() -> None:
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
    except Exception:
        pass
