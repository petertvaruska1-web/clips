"""Word-level transcription with faster-whisper (GPU large-v3-turbo, CPU small fallback)."""
from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


def _add_cuda_dll_dirs() -> None:
    """pip-installed nvidia-* wheels put DLLs under site-packages/nvidia/*/bin."""
    if os.name != "nt":
        return
    base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not base.exists():
        return
    for d in base.glob("*/bin"):
        try:
            os.add_dll_directory(str(d))
        except OSError:
            pass
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


_add_cuda_dll_dirs()


@dataclass
class Word:
    start: float
    end: float
    text: str


class Transcriber:
    def __init__(self, gpu_model: str = "large-v3-turbo", cpu_model: str = "small"):
        self.gpu_model, self.cpu_model = gpu_model, cpu_model
        self._models: dict[str, object] = {}
        self._lock = threading.Lock()

    def _model(self, prefer_gpu: bool):
        from faster_whisper import WhisperModel
        key = "gpu" if prefer_gpu else "cpu"
        if key in self._models:
            return self._models[key]
        if prefer_gpu:
            try:
                m = WhisperModel(self.gpu_model, device="cuda", compute_type="int8_float16")
                self._models["gpu"] = m
                return m
            except Exception as e:
                log.warning("GPU whisper unavailable (%s); using CPU", e)
        m = WhisperModel(self.cpu_model, device="cpu", compute_type="int8", cpu_threads=4)
        self._models["cpu"] = m
        return m

    @staticmethod
    def load_audio(path: Path, sr: int = 16000):
        import subprocess

        import numpy as np
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
                            "-f", "f32le", "pipe:1"], capture_output=True,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        return np.frombuffer(r.stdout, dtype=np.float32).copy()

    def transcribe(self, path: Path, prefer_gpu: bool = True) -> list[Word]:
        audio = self.load_audio(path)
        if audio.size < 1600:
            return []
        with self._lock:
            model = self._model(prefer_gpu)
            try:
                segments, _ = model.transcribe(audio, language="en", word_timestamps=True,
                                               vad_filter=True, beam_size=1,
                                               condition_on_previous_text=False)
                words = [Word(w.start, w.end, w.word.strip()) for s in segments for w in (s.words or [])]
            except RuntimeError as e:  # e.g. CUDA failure mid-run
                if not prefer_gpu:
                    raise
                log.warning("GPU transcription failed (%s); retrying on CPU", e)
                self._models.pop("gpu", None)
                return self.transcribe(path, prefer_gpu=False)
        return [w for w in words if w.text]
