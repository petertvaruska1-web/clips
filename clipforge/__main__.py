"""CLI: python -m clipforge [run|auth-youtube|check|status]"""
from __future__ import annotations

import asyncio
import logging
import logging.handlers
import sys

from .config import ROOT, load_config


def setup_logging() -> None:
    (ROOT / "logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(ROOT / "logs" / "clipforge.log", maxBytes=5_000_000, backupCount=5,
                                              encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(sh)
    for noisy in ("httpx", "googleapiclient", "faster_whisper", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def check() -> None:
    from .twitch_api import TwitchAPI
    from .youtube import YouTubeUploader
    cfg = load_config()
    api = TwitchAPI(cfg.secrets.twitch_client_id, cfg.secrets.twitch_client_secret)
    if not api.configured:
        print("Twitch: NOT configured (secrets/secrets.json)")
    else:
        gid = await api.get_game_id(cfg.game_name)
        streams = await api.get_streams(gid, cfg.language, pages=1) if gid else []
        print(f"Twitch: OK - '{cfg.game_name}' id={gid}, {len(streams)} live English streams")
        for s in streams[:10]:
            print(f"  {s['viewer_count']:>7}  {s['user_name']}")
    yt = YouTubeUploader(cfg.secrets_dir)
    print("YouTube:", f"connected to '{yt.channel_title()}'" if yt.configured else "NOT connected (run auth-youtube)")
    print("AI judge:", "groq" if cfg.secrets.groq_api_key else "", "gemini" if cfg.secrets.gemini_api_key else "",
          "" if (cfg.secrets.groq_api_key or cfg.secrets.gemini_api_key) else "templates only")
    print("YouTube privacy for new uploads:", cfg.youtube.privacy)


def status() -> None:
    from .db import Database
    cfg = load_config()
    db = Database(cfg.data_dir / "clipforge.db")
    rows = db.conn.execute("SELECT state, COUNT(*) FROM moments GROUP BY state").fetchall()
    print("moments:", {r[0]: r[1] for r in rows})
    for r in db.conn.execute("SELECT id, channel, round(score,2), state, title, note FROM moments "
                             "ORDER BY id DESC LIMIT 15").fetchall():
        print(" ", tuple(r))


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        setup_logging()
        from .app import App
        try:
            manual = sys.argv[sys.argv.index("--channels") + 1].split(",") if "--channels" in sys.argv else None
            asyncio.run(App(manual_channels=manual).run())
        except KeyboardInterrupt:
            pass
    elif cmd == "auth-youtube":
        from .youtube import YouTubeUploader
        cfg = load_config()
        print("Connected to YouTube channel:", YouTubeUploader(cfg.secrets_dir).authorize_interactive())
    elif cmd == "check":
        asyncio.run(check())
    elif cmd == "status":
        status()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
