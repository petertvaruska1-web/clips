"""Download CC-BY satisfying gameplay and cut it to 1080x960 panels for the split-screen style.

Run:  .venv\\Scripts\\python scripts\\fetch_backgrounds.py
Each source is downloaded whole (fast native downloader), trimmed + cropped, then deleted.
Already-prepared files are skipped, so it is safe to re-run or extend SOURCES.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clipforge.background import BG_DIR, prepare  # noqa: E402

YTDLP = str(ROOT / ".venv" / "Scripts" / "yt-dlp.exe")
# All Creative Commons Attribution (reuse allowed) per their YouTube license field; channels state
# the footage is free to use and monetize. Credit goes in each Short's description.
SOURCES = [  # id, file, category, start s, end s, credit channel
    ("u7kdVe8q5zs", "minecraft_parkour", "minecraft parkour", 60, 960, "Orbital - No Copyright Gameplay"),
    ("hZyjsJJ51kQ", "gta_megaramp_a", "gta mega ramp", 20, 870, "Dope Gameplays"),
    ("ZtLrNBdXT7M", "gta_megaramp_b", "gta mega ramp", 20, 740, "Dope Gameplays"),
    ("RNaEo6Zooww", "subway_surfers", "subway surfers", 120, 1020, "Orbital - No Copyright Gameplay"),
]
FMT = "bv*[height<=1080][fps>=50][vcodec^=avc1]/bv*[height<=1080][fps>=50]/bv*[height<=1080]"


def main() -> None:
    BG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "bg_src"
    tmp.mkdir(parents=True, exist_ok=True)
    man_f = BG_DIR / "manifest.json"
    manifest = json.loads(man_f.read_text()) if man_f.exists() else []
    have = {m["file"] for m in manifest}
    for vid, name, cat, a, b, channel in SOURCES:
        if f"{name}.mp4" in have and (BG_DIR / f"{name}.mp4").exists():
            continue
        print("downloading", name, flush=True)
        for old in tmp.glob(f"{name}*"):
            old.unlink()
        subprocess.run([YTDLP, "--js-runtimes", "node", "-f", FMT, "--force-overwrites",
                        "-o", str(tmp / f"{name}.%(ext)s"), f"https://youtu.be/{vid}"], check=True)
        src = next(p for p in tmp.glob(f"{name}.*") if not p.name.endswith(".part"))
        print("preparing", name, flush=True)
        cut = tmp / f"{name}_cut.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(a), "-to", str(b), "-i", str(src), "-an",
                        "-c", "copy", str(cut)], check=True)
        src.unlink()
        dur = prepare(cut, BG_DIR / f"{name}.mp4")
        cut.unlink()
        manifest = [m for m in manifest if m["file"] != f"{name}.mp4"]
        manifest.append({"file": f"{name}.mp4", "category": cat, "duration": round(dur - 1, 1),
                         "url": f"https://youtu.be/{vid}",
                         "credit": f"{channel} (CC BY) https://youtu.be/{vid}"})
        man_f.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        print("ok", name, round(dur), "s", flush=True)


if __name__ == "__main__":
    main()
