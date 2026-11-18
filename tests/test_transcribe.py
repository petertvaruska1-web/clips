from pathlib import Path

from clipforge.transcribe import Transcriber

FIX = Path(__file__).parent / "fixtures" / "speech.wav"


def test_transcribe_returns_timed_words():
    words = Transcriber().transcribe(FIX)
    texts = [w.text.lower().strip(".,") for w in words]
    assert "police" in texts and "insane" in texts
    assert all(b.start >= a.start for a, b in zip(words, words[1:]))


def test_transcribe_silence_returns_empty(tmp_path):
    import subprocess
    p = tmp_path / "s.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "3", str(p)],
                   check=True)
    assert Transcriber().transcribe(p) == []
