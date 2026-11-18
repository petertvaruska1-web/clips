"""Anonymous Twitch IRC chat reader (spec §6.2)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import websockets

log = logging.getLogger(__name__)
IRC_URL = "wss://irc-ws.chat.twitch.tv:443"


@dataclass
class ChatEvent:
    kind: str                # msg | raid | subgift | sub | roomstate | clear | ping
    channel: str = ""
    ts: float = 0.0          # server time (tmi-sent-ts) in seconds
    user: str = ""           # hashed user id
    text: str = ""
    emotes: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


def _hash(uid: str) -> str:
    return hashlib.sha1(uid.encode()).hexdigest()[:12]


def _unescape(v: str) -> str:
    return v.replace(r"\s", " ").replace(r"\:", ";").replace(r"\\", "\\")


def parse_irc(line: str) -> ChatEvent | None:
    line = line.rstrip("\r\n")
    if line.startswith("PING"):
        return ChatEvent(kind="ping", text=line[5:])
    tags: dict[str, str] = {}
    if line.startswith("@"):
        raw, _, line = line.partition(" ")
        for kv in raw[1:].split(";"):
            k, _, v = kv.partition("=")
            tags[k] = _unescape(v)
    prefix = ""
    if line.startswith(":"):
        prefix, _, line = line[1:].partition(" ")
    cmd, _, rest = line.partition(" ")
    params, _, trailing = rest.partition(" :")
    channel = params.split(" ")[0].lstrip("#").lower() if params.startswith("#") else ""
    ts = int(tags.get("tmi-sent-ts", "0") or 0) / 1000.0 or time.time()
    uid = tags.get("user-id") or prefix.split("!")[0]
    if cmd == "PRIVMSG":
        emotes = []
        if tags.get("emotes"):
            for spec in tags["emotes"].split("/"):
                _, _, ranges = spec.partition(":")
                a, _, b = ranges.split(",")[0].partition("-")
                if a.isdigit() and b.isdigit():
                    emotes.append(trailing[int(a):int(b) + 1])
        badges = tags.get("badges", "")
        return ChatEvent(kind="msg", channel=channel, ts=ts, user=_hash(uid), text=trailing,
                         emotes=emotes, extra={
                             "login": prefix.split("!")[0].lower(),
                             "sub": tags.get("subscriber") == "1",
                             "mod": tags.get("mod") == "1",
                             "broadcaster": "broadcaster/" in badges,
                             "first": tags.get("first-msg") == "1",
                             "bits": int(tags.get("bits", "0") or 0),
                             "source_room": tags.get("source-room-id", ""),
                             "room": tags.get("room-id", ""),
                         })
    if cmd == "USERNOTICE":
        mid = tags.get("msg-id", "")
        if mid == "raid":
            return ChatEvent(kind="raid", channel=channel, ts=ts,
                             extra={"viewers": int(tags.get("msg-param-viewerCount", "0") or 0)})
        if mid == "submysterygift":
            return ChatEvent(kind="subgift", channel=channel, ts=ts,
                             extra={"count": int(tags.get("msg-param-mass-gift-count", "1") or 1)})
        if mid in ("sub", "resub", "subgift"):
            return ChatEvent(kind="sub", channel=channel, ts=ts)
        return None
    if cmd == "ROOMSTATE":
        return ChatEvent(kind="roomstate", channel=channel, ts=ts, extra=dict(tags))
    if cmd in ("CLEARCHAT", "CLEARMSG"):
        return ChatEvent(kind="clear", channel=channel, ts=ts)
    return None


Handler = Callable[[ChatEvent], Awaitable[None] | None]


class ChatClient:
    """One anonymous connection; join/part any number of channels (≤20 joins / 10 s)."""

    def __init__(self, on_event: Handler):
        self.on_event = on_event
        self.wanted: set[str] = set()
        self.joined: set[str] = set()
        self._ws = None
        self._join_times: list[float] = []

    def set_channels(self, channels: set[str]) -> None:
        self.wanted = {c.lower() for c in channels}

    async def _sync(self) -> None:
        ws = self._ws
        if ws is None:
            return
        for ch in list(self.joined - self.wanted):
            await ws.send(f"PART #{ch}")
            self.joined.discard(ch)
        for ch in list(self.wanted - self.joined):
            now = time.monotonic()
            self._join_times = [t for t in self._join_times if now - t < 10.5]
            if len(self._join_times) >= 18:
                break
            await ws.send(f"JOIN #{ch}")
            self._join_times.append(now)
            self.joined.add(ch)

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(IRC_URL, ping_interval=60, max_size=2**22) as ws:
                    self._ws, self.joined = ws, set()
                    await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
                    await ws.send("PASS SCHMOOPIIE")
                    await ws.send(f"NICK justinfan{random.randint(10000, 99999)}")
                    backoff = 1.0
                    syncer = asyncio.create_task(self._sync_loop())
                    try:
                        async for raw in ws:
                            for line in str(raw).split("\r\n"):
                                if not line:
                                    continue
                                ev = parse_irc(line)
                                if ev is None:
                                    continue
                                if ev.kind == "ping":
                                    await ws.send("PONG :tmi.twitch.tv")
                                    continue
                                r = self.on_event(ev)
                                if asyncio.iscoroutine(r):
                                    await r
                    finally:
                        syncer.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # network errors: reconnect
                log.warning("chat connection lost: %s; reconnecting in %.0fs", e, backoff)
            self._ws = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _sync_loop(self) -> None:
        while True:
            try:
                await self._sync()
            except Exception as e:
                log.warning("join sync failed: %s", e)
            await asyncio.sleep(2)
