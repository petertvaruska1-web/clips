"""Minimal Twitch Helix client with an app access token (client-credentials)."""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)
HELIX = "https://api.twitch.tv/helix"


class TwitchAPI:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = ""
        self._expires = 0.0
        self.http = httpx.AsyncClient(timeout=20)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def _auth(self) -> None:
        if self._token and time.time() < self._expires - 300:
            return
        r = await self.http.post("https://id.twitch.tv/oauth2/token", params={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "grant_type": "client_credentials"})
        r.raise_for_status()
        j = r.json()
        self._token, self._expires = j["access_token"], time.time() + j.get("expires_in", 3600)

    async def get(self, path: str, params) -> dict:
        await self._auth()
        for attempt in range(3):
            r = await self.http.get(f"{HELIX}/{path}", params=params, headers={
                "Client-Id": self.client_id, "Authorization": f"Bearer {self._token}"})
            if r.status_code == 401:
                self._token = ""
                await self._auth()
                continue
            if r.status_code == 429:
                time.sleep(2)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return {}

    async def get_game_id(self, name: str) -> str | None:
        data = (await self.get("games", {"name": name})).get("data", [])
        return data[0]["id"] if data else None

    async def get_streams(self, game_id: str, language: str = "en", pages: int = 2) -> list[dict]:
        out, cursor = [], None
        for _ in range(pages):
            params = {"game_id": game_id, "type": "live", "first": 100, "language": language}
            if cursor:
                params["after"] = cursor
            j = await self.get("streams", params)
            out += j.get("data", [])
            cursor = j.get("pagination", {}).get("cursor")
            if not cursor:
                break
        return out

    async def get_streams_by_login(self, logins: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(logins), 100):
            out += (await self.get("streams", [("user_login", l) for l in logins[i:i + 100]])).get("data", [])
        return out

    async def get_latest_archive(self, user_id: str) -> dict | None:
        data = (await self.get("videos", {"user_id": user_id, "type": "archive", "first": 1})).get("data", [])
        return data[0] if data else None

    async def get_clips(self, broadcaster_id: str, started_at: str, ended_at: str) -> list[dict]:
        j = await self.get("clips", {"broadcaster_id": broadcaster_id, "started_at": started_at,
                                     "ended_at": ended_at, "first": 100})
        return j.get("data", [])
