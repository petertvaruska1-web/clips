"""YouTube Shorts upload via the official Data API v3 (spec §6.9)."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .config import YouTubeCfg

log = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]


def build_metadata(title: str, streamer: str, display: str, hashtags: list[str], cfg: YouTubeCfg) -> dict:
    tags = []
    for h in [*hashtags, *cfg.extra_hashtags]:
        h = "#" + h.lstrip("#").replace(" ", "")
        if h.lower() not in [t.lower() for t in tags]:
            tags.append(h)
    full = title if "#gta6" in title.lower() else f"{title} #GTA6"
    if len(full) > 100:
        full = title[:100]
    desc = (f"{display} live on Twitch: https://twitch.tv/{streamer}\n"
            f"Clip from {display}'s GTA 6 stream. All credit to {display} — go follow them!\n\n"
            + " ".join(tags[:8]))
    return {
        "snippet": {"title": full, "description": desc, "categoryId": cfg.category_id,
                    "tags": [t.lstrip("#") for t in tags] + [display, streamer, "GTA 6", "GTA VI", "Grand Theft Auto 6"],
                    "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": cfg.privacy, "selfDeclaredMadeForKids": False, "embeddable": True},
    }


class YouTubeUploader:
    def __init__(self, secrets_dir: Path):
        self.client_file = Path(secrets_dir) / "youtube_client.json"
        self.token_file = Path(secrets_dir) / "youtube_token.json"
        self._service = None

    @property
    def configured(self) -> bool:
        return self.token_file.exists()

    def authorize_interactive(self) -> str:
        """One-time browser sign-in. Returns the channel title."""
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(self.client_file), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
        self.token_file.write_text(creds.to_json(), encoding="utf-8")
        self._service = None
        return self.channel_title()

    def _svc(self):
        if self._service is None:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
            if not creds.valid and creds.refresh_token:
                creds.refresh(Request())
                self.token_file.write_text(creds.to_json(), encoding="utf-8")
            self._service = build("youtube", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def channel_title(self) -> str:
        items = self._svc().channels().list(part="snippet", mine=True).execute().get("items", [])
        return items[0]["snippet"]["title"] if items else "(no channel)"

    def upload(self, path: Path, body: dict) -> str:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
        req = self._svc().videos().insert(part="snippet,status", body=body, media_body=media)
        resp, retries = None, 0
        while resp is None:
            try:
                _, resp = req.next_chunk()
            except HttpError as e:
                if e.resp.status in (500, 502, 503, 504) and retries < 5:
                    retries += 1
                    time.sleep(2 ** retries)
                    continue
                raise
        return resp["id"]

    def status(self, video_ids: list[str]) -> list[dict]:
        if not video_ids:
            return []
        return self._svc().videos().list(part="status,statistics", id=",".join(video_ids[:50])).execute().get("items", [])
