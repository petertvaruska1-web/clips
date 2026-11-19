"""ClipForge main process: scout -> chat/record -> detect -> extract -> enrich -> render -> schedule -> upload."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .audio import loudness_curve, mean_excitement
from .chat import ChatClient, ChatEvent
from .config import ROOT, Config, load_config
from .db import Database
from .detector import ChannelDetector, Moment
from .extractor import RawClip, extract_buffer, extract_vod
from .facecam import find_facecam, sample_frames
from .governor import Governor, keep_awake, set_low_priority
from .judge import JudgeContext, frames_have_nudity, judge
from .pipeline import choose_window, final_score
from .recorder import Recorder
from .render import RenderJob, probe_video, render_short
from .scheduler import Candidate, Scheduler
from .scout import Tiers, choose_tiers
from .transcribe import Transcriber
from .twitch_api import TwitchAPI
from .youtube import YouTubeUploader, build_metadata

log = logging.getLogger("clipforge")
SCOUT_EVERY = 120
BUFFER_KEEP = 300
VOD_RETRY_FOR = 15 * 60
VOD_MIN_HYPE = 0.97
MAX_QUEUE_AGE = 30 * 60
LAYOUT_TTL = 30 * 60


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


class App:
    def __init__(self, cfg: Config | None = None, manual_channels: list[str] | None = None):
        self.cfg = cfg or load_config()
        self.manual = [c.lower() for c in (manual_channels or [])]
        d = Path(self.cfg.data_dir)
        self.dirs = {k: d / k for k in ("buffer", "raw", "out", "chat")}
        for p in self.dirs.values():
            p.mkdir(parents=True, exist_ok=True)
        self.db = Database(d / "clipforge.db")
        s = self.cfg.secrets
        self.twitch = TwitchAPI(s.twitch_client_id, s.twitch_client_secret)
        self.chat = ChatClient(self.on_chat)
        self.detectors: dict[str, ChannelDetector] = {}
        self.recorders: dict[str, Recorder] = {}
        self.tiers = Tiers()
        self.stream_info: dict[str, dict] = {}       # login -> latest Helix stream record
        self.game_id: str | None = None
        self.transcriber = Transcriber()
        self.youtube = YouTubeUploader(self.cfg.secrets_dir)
        self.scheduler = Scheduler(self.cfg.posting)
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline")
        self._working = False
        self.governor = Governor(ours_busy=lambda: self._working)
        self.pending: dict[int, dict] = {}           # moment id -> extraction info
        self.raw_queue: list = []                    # (mid, RawClip, Moment) waiting for processing
        self.vod_sem = asyncio.Semaphore(2)
        self.layouts_file = d / "layouts.json"
        self.layouts: dict = json.loads(self.layouts_file.read_text()) if self.layouts_file.exists() else {}
        self.chat_log: dict[str, object] = {}
        self._warned: set[str] = set()

    # ---------------- chat ----------------
    def on_chat(self, ev: ChatEvent) -> None:
        det = self.detectors.get(ev.channel)
        if det:
            det.feed(ev)

    # ---------------- scout ----------------
    async def scout_once(self) -> None:
        if self.manual and not self.twitch.configured:
            n_a = self.governor.live_capacity(self.cfg.capacity.live, self.cfg.capacity.busy_live)
            streams = [{"user_login": c, "viewer_count": 10 ** 6 - i, "user_name": c} for i, c in enumerate(self.manual)]
            self.tiers = choose_tiers(streams, {}, n_a, self.cfg.capacity.chat_only, self.tiers, time.time())
            self.stream_info.update(self.tiers.info)
            self._apply_tiers()
            log.info("manual mode: live-recorded: %s", ", ".join(self.tiers.a))
            return
        if not self.twitch.configured:
            self._warn_once("twitch", "Twitch API keys missing (secrets/secrets.json) — scout idle")
            return
        if not self.game_id:
            self.game_id = await self.twitch.get_game_id(self.cfg.game_name)
            log.info("GTA VI category id: %s", self.game_id)
            if not self.game_id:
                return
        streams = await self.twitch.get_streams(self.game_id, self.cfg.language)
        prio = [s for s in self.cfg.streamers if s not in {x["user_login"].lower() for x in streams}]
        if prio:
            extra = await self.twitch.get_streams_by_login(prio)
            streams += [x for x in extra if x.get("game_id") == self.game_id]
        n_a = self.governor.live_capacity(self.cfg.capacity.live, self.cfg.capacity.busy_live)
        if self._free_gb() < self.cfg.disk.min_free_gb:
            n_a = 0
            self._warn_once("disk", "free disk below limit — live recording paused")
        self.tiers = choose_tiers(streams, self.cfg.streamers, n_a, self.cfg.capacity.chat_only, self.tiers,
                                  time.time(), self.cfg.capacity.min_viewers, set(self.cfg.blocklist))
        self.stream_info.update({c: self.tiers.info[c] for c in self.tiers.info})
        self._apply_tiers()
        log.info("scout: %d GTA VI streams | live-recorded: %s | chat-only: %d", len(streams),
                 ", ".join(self.tiers.a) or "-", len(self.tiers.b))

    def _apply_tiers(self) -> None:
        followed = set(self.tiers.a) | set(self.tiers.b)
        for c in followed - set(self.detectors):
            self.detectors[c] = ChannelDetector(c, self.cfg.clip, set(self.cfg.bots))
        for c in set(self.detectors) - followed:
            if not any(p["channel"] == c for p in self.pending.values()):
                del self.detectors[c]
        self.chat.set_channels(followed)
        for c in set(self.tiers.a) - set(self.recorders):
            r = Recorder(c, self.dirs["buffer"] / c, self.cfg.clip.quality)
            r.start()
            self.recorders[c] = r
        for c in set(self.recorders) - set(self.tiers.a):
            self.recorders.pop(c).stop()

    async def scout_loop(self) -> None:
        while True:
            try:
                await self.scout_once()
            except Exception as e:
                log.exception("scout failed: %s", e)
            await asyncio.sleep(SCOUT_EVERY)

    # ---------------- detection ----------------
    async def detect_loop(self) -> None:
        while True:
            now = time.time()
            for c, det in list(self.detectors.items()):
                try:
                    for m in det.tick(now):
                        self.on_moment(m)
                except Exception as e:
                    log.exception("detector %s failed: %s", c, e)
            await asyncio.sleep(1)

    def on_moment(self, m: Moment) -> None:
        cfg = self.cfg.clip
        pre = cfg.pre_roll_slow if m.rise_time > 6 else cfg.pre_roll
        a = m.t_event - pre - 6
        b = max(m.t_end_hint, m.t_peak - cfg.chat_lag + 4) + 8
        b = min(b, a + cfg.max_len + 20)
        mid = self.db.add_moment(channel=m.channel, t_event=m.t_event, t_on=m.t_on, t_peak=m.t_peak,
                                 score=m.hype_peak, category=m.category,
                                 features={**m.features, "burst_size": m.burst_size, "rise_time": m.rise_time,
                                           "hype_peak": m.hype_peak})
        self.pending[mid] = dict(channel=m.channel, a=a, b=b, moment=m, created=time.time())
        log.info("moment #%d %s %s hype=%.2f (event %s)", mid, m.channel, m.category, m.hype_peak,
                 time.strftime("%H:%M:%S", time.localtime(m.t_event)))

    # ---------------- extraction + enrichment ----------------
    async def extract_loop(self) -> None:
        while True:
            for mid, p in list(self.pending.items()):
                try:
                    await self._try_extract(mid, p)
                except Exception as e:
                    log.exception("extract #%d failed: %s", mid, e)
                    self.pending.pop(mid, None)
                    self.db.update_moment(mid, state="failed", note=f"extract: {e}"[:300])
            await asyncio.sleep(3)

    def _queue_raw(self, mid: int, raw: RawClip, m: Moment) -> None:
        self.pending.pop(mid, None)
        self.db.update_moment(mid, state="extracted", raw_path=str(raw.path))
        self.raw_queue.append((mid, raw, m))

    async def _try_extract(self, mid: int, p: dict) -> None:
        now = time.time()
        ch, a, b = p["channel"], p["a"], p["b"]
        if p.get("vod_busy"):
            return
        rec = self.recorders.get(ch)
        out = self.dirs["raw"] / f"{mid}_{ch}.ts"
        if rec is not None and not p.get("buffer_failed"):
            last = rec.index.latest_time() or 0
            if last < b and now - p["created"] < 90:
                return  # wait for the buffer to reach the clip end
            raw = await asyncio.to_thread(extract_buffer, rec.index, a, b, out)
            if raw is not None:
                self._queue_raw(mid, raw, p["moment"])
                return
            p["buffer_failed"] = True
        # no live buffer: cut from the VOD, but only for strong moments (VOD downloads are heavy)
        if p["moment"].hype_peak < VOD_MIN_HYPE:
            self.pending.pop(mid, None)
            self.db.update_moment(mid, state="dropped", note="chat-only moment below VOD threshold")
            return
        if now - p["created"] > VOD_RETRY_FOR:
            self.pending.pop(mid, None)
            self.db.update_moment(mid, state="dropped", note="no buffer and no VOD")
            return
        if now - p.get("vod_tried", 0) < 60:
            return
        p["vod_tried"], p["vod_busy"] = now, True
        asyncio.create_task(self._vod_task(mid, p, out.with_suffix(".mp4")))

    async def _vod_task(self, mid: int, p: dict, out: Path) -> None:
        try:
            async with self.vod_sem:
                raw = await self._extract_from_vod(p["channel"], p["a"], p["b"], out)
            if raw is not None and mid in self.pending:
                self._queue_raw(mid, raw, p["moment"])
        except Exception as e:
            log.warning("VOD cut #%d failed: %s", mid, e)
        finally:
            p["vod_busy"] = False

    async def process_loop(self) -> None:
        """Process the strongest waiting clip first; stale ones are dropped (we post only a few per day)."""
        while True:
            now = time.time()
            for item in list(self.raw_queue):
                if now - item[2].t_event > MAX_QUEUE_AGE:
                    self.raw_queue.remove(item)
                    item[1].path.unlink(missing_ok=True)
                    self.db.update_moment(item[0], state="dropped", note="stale before processing")
            if self.raw_queue:
                best = max(self.raw_queue, key=lambda it: it[2].hype_peak * self.cfg.streamers.get(it[2].channel, 1.0)
                           + 0.1 * min(1.0, it[2].burst_size / 15))
                self.raw_queue.remove(best)
                await asyncio.to_thread(self._process_safe, *best)
            else:
                await asyncio.sleep(2)

    async def _extract_from_vod(self, ch: str, a: float, b: float, out: Path) -> RawClip | None:
        info = self.stream_info.get(ch)
        if not info or not self.twitch.configured:
            return None
        vod = await self.twitch.get_latest_archive(info["user_id"])
        if not vod or vod.get("viewable", "public") != "public":
            return None
        vod_start = _parse_iso(vod["created_at"])
        if vod_start > a:
            return None
        return await asyncio.to_thread(extract_vod, vod["url"], vod_start, a, b, out)

    def _process_safe(self, mid: int, raw: RawClip, m: Moment) -> None:
        self._working = True
        try:
            self.process(mid, raw, m)
        except Exception as e:
            log.exception("processing #%d failed: %s", mid, e)
            self.db.update_moment(mid, state="failed", note=str(e)[:300])
        finally:
            self._working = False

    @staticmethod
    def _frames(path: Path, s: float, e: float, n: int = 5) -> list[bytes]:
        """One JPEG strip of n evenly spaced frames from [s, e] (one vision request per clip)."""
        import subprocess
        step = max(0.5, (e - s) / n)
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{s + step / 2:.2f}", "-t", f"{e - s:.2f}", "-i", str(path),
                            "-vf", f"fps=1/{step:.3f},scale=320:-2,tile={n}x1", "-frames:v", "1",
                            "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"], capture_output=True,
                           creationflags=0x08000000)
        return [r.stdout] if r.stdout else []

    def _layout(self, ch: str, raw: Path) -> tuple[str, tuple | None]:
        info = probe_video(raw)
        cached = self.layouts.get(ch)
        if cached and time.time() - cached["at"] < LAYOUT_TTL and cached.get("src") == [info["w"], info["h"]]:
            fc = tuple(cached["facecam"]) if cached["facecam"] else None
        else:
            fc = find_facecam(sample_frames(raw), info["w"], info["h"])
            self.layouts[ch] = {"facecam": list(fc) if fc else None, "at": time.time(), "src": [info["w"], info["h"]]}
            self.layouts_file.write_text(json.dumps(self.layouts, indent=1))
        return ("stack" if fc else "fill"), fc

    def process(self, mid: int, raw: RawClip, m: Moment) -> None:
        cfg = self.cfg.clip
        busy = self.governor.state() == "busy"
        t, db = loudness_curve(raw.path)
        raw_len = float(t[-1]) if len(t) else 0.0
        if raw_len < cfg.min_len:
            self.db.update_moment(mid, state="rejected", note="raw clip too short")
            return
        words = self.transcriber.transcribe(raw.path, prefer_gpu=not busy)
        ev_guess = m.t_event - raw.t0
        peak_rel = m.t_peak - cfg.chat_lag - raw.t0
        s, e, ev, strength = choose_window(words, t, db, ev_guess, peak_rel, m.rise_time, cfg, raw_len)
        clip_words = [w for w in words if s <= w.start < e]
        transcript = " ".join(w.text for w in clip_words)
        info = self.stream_info.get(m.channel, {})
        display = info.get("user_name") or m.channel
        keys = {"groq": self.cfg.secrets.groq_api_key, "gemini": self.cfg.secrets.gemini_api_key}
        verdict = judge(JudgeContext(streamer=m.channel, display=display, category=m.category,
                                     transcript=transcript, chat_lines=m.features.get("chat_lines", [])), keys)
        audio = mean_excitement(t, db, s, e, ev)
        weight = self.cfg.streamers.get(m.channel, 1.0)
        score = final_score(hype=m.hype_peak, burst=min(1.0, m.burst_size / 15.0), viewer_clips=None,
                            audio=audio, watchability=verdict.watchability, weight=weight)
        reject = None
        if verdict.safety_flags:
            reject = f"safety: {verdict.safety_flags}"
        elif verdict.spoiler_risk == "high":
            reject = "spoiler risk"
        elif verdict.off_topic:
            reject = "off topic"
        elif not clip_words and strength < 6:
            reject = "no speech and no strong audio"
        if not reject:
            nude = frames_have_nudity(self._frames(raw.path, s, e), self.cfg.secrets.groq_api_key)
            if nude:
                reject = "nudity in frames"
        feats = {**m.features, "audio_strength": strength, "audio_excitement": audio,
                 "watchability": verdict.watchability, "judge": verdict.source, "words": len(clip_words),
                 "window": [s, e], "event_rel": ev}
        if reject:
            self.db.update_moment(mid, state="rejected", note=reject, score=score, features=feats,
                                  title=verdict.title)
            log.info("moment #%d rejected: %s", mid, reject)
            raw.path.unlink(missing_ok=True)
            return
        layout, fc = self._layout(m.channel, raw.path)
        out = self.dirs["out"] / f"{mid}_{m.channel}.mp4"
        render_short(RenderJob(raw_path=raw.path, a=s, b=e, t_event=ev, layout=layout, facecam=fc,
                               words=clip_words, hook=verdict.hook, credit=f"twitch.tv/{m.channel}", out_path=out))
        raw.path.unlink(missing_ok=True)
        self.db.update_moment(mid, state="ready", score=score, out_path=str(out), title=verdict.title,
                              hook=verdict.hook, hashtags=json.dumps(verdict.hashtags), category=verdict.category,
                              clip_start=raw.t0 + s, clip_end=raw.t0 + e, features=feats)
        log.info("moment #%d ready: score=%.2f %s | %s", mid, score, layout, verdict.title)

    # ---------------- viewer clips + scheduling + upload ----------------
    async def refresh_viewer_clips(self) -> None:
        if not self.twitch.configured:
            return
        now = time.time()
        for row in self.db.moments_in_state("ready"):
            f = row["features"]
            if f.get("viewer_clips_checked", 0) >= 2 or now - row["t_event"] < 300 * (1 + f.get("viewer_clips_checked", 0)):
                continue
            info = self.stream_info.get(row["channel"])
            if not info:
                continue
            clips = await self.twitch.get_clips(info["user_id"], _iso(row["t_event"] - 5), _iso(row["t_event"] + 150))
            n = sum(1 for c in clips if row["t_event"] <= _parse_iso(c["created_at"]) <= row["t_event"] + 150)
            vc = min(1.0, n / 3.0)
            weight = self.cfg.streamers.get(row["channel"], 1.0)
            score = final_score(hype=f.get("hype_peak", row["score"]), burst=min(1.0, f.get("burst_size", 0) / 15),
                                viewer_clips=vc, audio=f.get("audio_excitement"), watchability=f.get("watchability"),
                                weight=weight)
            if n >= 3:
                score = max(score, self.cfg.posting.exceptional_score)
            f.update(viewer_clips=n, viewer_clips_checked=f.get("viewer_clips_checked", 0) + 1)
            self.db.update_moment(row["id"], score=score, features=f)

    async def publish_loop(self) -> None:
        while True:
            try:
                await self.refresh_viewer_clips()
                await self.publish_once()
            except Exception as e:
                log.exception("publish loop failed: %s", e)
            await asyncio.sleep(60)

    async def publish_once(self) -> None:
        now = time.time()
        ready = self.db.moments_in_state("ready")
        for row in ready:
            if now - row["t_event"] > 36 * 3600:
                self.db.update_moment(row["id"], state="expired")
        cands = [Candidate(r["id"], r["channel"], r["score"], r["t_event"]) for r in ready
                 if now - r["t_event"] <= 36 * 3600 and r["out_path"] and Path(r["out_path"]).exists()]
        if not cands:
            return
        if not self.youtube.configured:
            self._warn_once("yt", "YouTube not connected yet (python -m clipforge auth-youtube) — clips queue up")
            return
        hist = self.db.uploads_since(now - 2 * 86400)
        pick = self.scheduler.pick(cands, now, hist)
        if not pick:
            return
        if self.governor.state() == "busy" and pick.score < self.cfg.posting.exceptional_score:
            return  # don't eat upload bandwidth while the user games, unless it's exceptional
        row = self.db.get_moment(pick.moment_id)
        exceptional = self.scheduler.is_exceptional(pick, now, hist)
        info = self.stream_info.get(row["channel"], {})
        body = build_metadata(row["title"], row["channel"], info.get("user_name") or row["channel"],
                              json.loads(row["hashtags"] or "[]"), self.cfg.youtube)
        self.db.update_moment(row["id"], state="uploading")
        try:
            vid = await asyncio.to_thread(self.youtube.upload, Path(row["out_path"]), body)
        except Exception as e:
            log.warning("upload of #%d failed: %s", row["id"], e)
            self.db.update_moment(row["id"], state="ready")
            return
        self.db.add_upload(row["id"], video_id=vid, title=body["snippet"]["title"], channel=row["channel"],
                           published_at=time.time(), exceptional=exceptional)
        self.db.update_moment(row["id"], state="uploaded", note=f"https://youtube.com/shorts/{vid}")
        log.info("UPLOADED #%d -> https://youtube.com/shorts/%s (%s)", row["id"], vid, self.cfg.youtube.privacy)

    # ---------------- housekeeping ----------------
    def _free_gb(self) -> float:
        return shutil.disk_usage(self.cfg.data_dir).free / 1e9

    def _warn_once(self, key: str, msg: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(msg)

    async def housekeeping_loop(self) -> None:
        while True:
            try:
                now = time.time()
                pins = [(p["a"], p["b"]) for p in self.pending.values()]
                for c, r in list(self.recorders.items()):
                    r.index.prune(now, BUFFER_KEEP, pins)
                    if not r.alive():
                        log.warning("recorder %s stalled; restarting", c)
                        r.stop()
                        r.start()
                for d in self.dirs["buffer"].iterdir():
                    if d.is_dir() and d.name not in self.recorders:
                        shutil.rmtree(d, ignore_errors=True)
                keep_s = self.cfg.disk.keep_uploaded_days * 86400
                for f in self.dirs["out"].glob("*.mp4"):
                    if now - f.stat().st_mtime > keep_s:
                        f.unlink(missing_ok=True)
                for f in self.dirs["raw"].glob("*"):
                    if now - f.stat().st_mtime > 3600:
                        f.unlink(missing_ok=True)
                keep_awake(bool(self.detectors))
            except Exception as e:
                log.exception("housekeeping failed: %s", e)
            await asyncio.sleep(30)

    async def run(self) -> None:
        set_low_priority()
        log.info("ClipForge starting (privacy=%s, %d posts/day)", self.cfg.youtube.privacy, self.cfg.posting.per_day)
        # resume: moments rendered before a restart stay in the queue
        for row in self.db.moments_in_state("uploading"):
            self.db.update_moment(row["id"], state="ready")
        for st in ("detected", "extracted"):
            for row in self.db.moments_in_state(st):
                self.db.update_moment(row["id"], state="failed", note="interrupted by restart")
        tasks = [asyncio.create_task(x) for x in (self.chat.run(), self.scout_loop(), self.detect_loop(),
                                                    self.extract_loop(), self.process_loop(), self.publish_loop(), self.housekeeping_loop())]
        try:
            await asyncio.gather(*tasks)
        finally:
            for r in self.recorders.values():
                r.stop()
            keep_awake(False)
