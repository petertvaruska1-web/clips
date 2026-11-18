# ClipForge Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The whole workflow running end to end today: find GTA VI streams → watch chat and record the top streams → detect moments → cut → transcribe, judge and score → render a 9:16 Short → schedule → upload to YouTube.

**Architecture:** One asyncio Python process (`python -m clipforge run`):
- Scout, chat and detectors run in-process.
- streamlink/ffmpeg recorders run as subprocesses.
- Heavy work runs in a worker thread pool, one job at a time (transcribe, render).
- State lives in SQLite.
- Every external service sits behind a small module so it can degrade to a fallback.

**Tech Stack:**
- Python 3.12 (uv venv)
- httpx, websockets, numpy
- streamlink, yt-dlp, ffmpeg 8.1
- faster-whisper (CUDA), opencv-python (YuNet)
- google-api-python-client, google-auth-oauthlib
- psutil, nvidia-ml-py, PyYAML, pytest

**Spec:** `docs/superpowers/specs/2026-11-18-gta6-shorts-clipper-design.md`

## Global Constraints
- $0: no paid service; AI keys optional, template fallback always works.
- Windows 11 host; all subprocesses `BELOW_NORMAL_PRIORITY_CLASS`; paths via `pathlib`.
- Output video: 1080×1920 H.264 (h264_nvenc → libx264 fallback), AAC 160k, loudnorm I=-14 TP=-1, `+faststart`, 12–60 s.
- Pre-roll default 20 s; chat lag default 7 s; clip length target 25–45 s, hard 15–60 s.
- Posting: 8/day default, ≥60 min apart, +3 exceptional/day (S ≥ 0.9), ≤3 per streamer/day, never same streamer twice in a row.
- Twitch: anonymous IRC `wss://irc-ws.chat.twitch.tv:443`, ≤20 joins/10 s; Helix app token.
- Disk: working data ≤ 15 GB; recording pauses below 5 GB free.
- Secrets only in `secrets/` (git-ignored); hashed chat user IDs.
- Uploads go public only when `youtube.privacy: public` in config (dry run uses `private`).

## Review Focus
1. Stream goes offline / changes category mid-moment → pending extraction finishes from buffer or is dropped cleanly; no crash, recorder stops.
2. Raid or gift-bomb floods chat → no moment (penalty), unless reaction signals are also extreme.
3. Silent clip / no speech → captions empty, render still succeeds; score lowered.
4. YouTube token expired or quota exhausted → upload stays queued, retried later, nothing lost.
5. No GPU available / NVENC busy → CPU fallbacks for whisper and x264.

---

## File map
```
clipforge/__main__.py   CLI: run | auth-youtube | render-test | detect-replay | status
clipforge/config.py     load_config(path) -> Config (dataclasses, defaults from spec)
clipforge/db.py         Database(path): moments, clips, uploads tables
clipforge/lexicon.py    normalize(text) -> list[str]; categorize(tokens, emotes) -> set[str]
clipforge/chat.py       parse_irc(line) -> ChatEvent | None; ChatClient (asyncio)
clipforge/detector.py   ChannelDetector.feed(ev); .tick(now) -> list[Moment]
clipforge/twitch_api.py Helix: get_game_id, get_streams, get_videos, get_clips
clipforge/scout.py      choose_tiers(streams, cfg, current) -> Tiers
clipforge/recorder.py   SegmentIndex; Recorder (streamlink|ffmpeg segment)
clipforge/extractor.py  extract_buffer(index, a, b, out); extract_vod(url, a, b, out)
clipforge/audio.py      loudness_curve(wav) ; snap_event(curve, t_guess) ; reaction_end(...)
clipforge/transcribe.py transcribe(path) -> list[Word]
clipforge/judge.py      judge(ctx) -> Verdict  (Groq → Gemini → template)
clipforge/facecam.py    find_facecam(video) -> Box | None
clipforge/captions.py   build_ass(words, t0, style) -> str
clipforge/render.py     render_short(job) -> Path
clipforge/scheduler.py  Scheduler.pick(candidates, now, history) -> list[Candidate]
clipforge/youtube.py    YouTubeUploader.upload(path, meta) -> video_id
clipforge/governor.py   Governor.state() -> "normal" | "busy"; keep_awake(bool)
clipforge/app.py        App: wires everything; pipeline jobs
config.yaml, tests/…, scripts/install_autostart.ps1
```

### Task 1: Environment + config + db
- [ ] `uv venv --python 3.12`; install deps; `git init`, `.gitignore` (secrets/, data/, logs/, .venv/).
- [ ] Test `tests/test_config.py::test_defaults` — `load_config(tmp_yaml).posting.per_day == 8`, `.clip.pre_roll == 20`, `.clip.chat_lag == 7`.
- [ ] Implement `config.py`, `db.py` (tables: moments(id, channel, t_event, t_on, t_peak, score, category, state, features_json, created), uploads(moment_id, video_id, title, published_at, views)).
- [ ] Commit.

### Task 2: Lexicon + IRC parser
**Produces:** `normalize(text:str)->list[str]`, `categorize(tokens, emote_names:set[str])->set[str]`, `ChatEvent(kind, channel, ts:float, user:str, text:str, emotes:list[str], extra:dict)`.
- [ ] Tests: `normalize("LMAOOOO KEKW")==["lmao","kekw"]`; `categorize(["kekw"])=={"funny"}`; `categorize(["clip","it"])` contains `"clip"`; `parse_irc` of a real PRIVMSG with `tmi-sent-ts=1700000000123` → `ts==1700000000.123`, raid USERNOTICE → `kind=="raid"`, `extra["viewers"]==500`.
- [ ] Implement; ChatClient joins/parts channels with rate limit, reconnects with backoff, PING/PONG.
- [ ] Commit.

### Task 3: Moment detector
**Produces:** `ChannelDetector(channel, cfg).feed(ev: ChatEvent)`, `.tick(now: float) -> list[Moment]`; `Moment(channel, t_on, t_peak, t_event, t_end_hint, hype_peak, burst_size, category, rise_time, features)`.
- [ ] Tests (synthetic chat): steady 5 msg/s for 15 min then 60 msg/s of "KEKW" from 50 users → exactly one Moment, `category=="funny"`, `t_event == t_on - 7 ± 1`; same flood preceded by a raid event → no Moment; 1 user spamming 60 msg/s → no Moment; two bursts 10 s apart → one Moment.
- [ ] Implement per spec §6.4 (1-s bins, robust baseline excluding bursts, adaptive threshold = max(floor, p98.5 of last hour), open ≥2 s, close <0.6·thr for 4 s, merge 20 s, cooldown 30 s).
- [ ] Commit.

### Task 4: Twitch API + scout
**Produces:** `TwitchAPI(client_id, secret)` async methods; `choose_tiers(streams:list[dict], weights:dict, n_a:int, n_b:int, current:Tiers, now) -> Tiers(a:list[str], b:list[str])`.
- [ ] Tests: priority ordering uses viewers×weight; hysteresis keeps an existing tier-A channel for 15 min unless it vanished.
- [ ] Implement; commit.

### Task 5: Recorder + segment index + extractor
**Produces:** `SegmentIndex(dir).covering(a,b) -> list[Path] | None (None if gap)`; `Recorder(channel, dir, quality).start()/stop()/alive()`; `extract_buffer(...)`, `extract_vod(...)`.
- [ ] Tests: index over files named `<ms>.ts` returns covering set; gap > 6 s → None; prune keeps last 240 s except pinned.
- [ ] Implement (streamlink stdout → ffmpeg segment, 4 s, strftime ms names via index-on-arrival); concat with ffmpeg concat demuxer, stream copy.
- [ ] Commit.

### Task 6: Audio + transcription + judge
- [ ] Tests: `snap_event` picks the synthetic loud transient within window; `reaction_end` returns when energy returns to baseline; `judge` with no keys returns template title containing streamer name and "GTA 6", `watchability is None`.
- [ ] Implement faster-whisper (large-v3-turbo cuda int8_float16 → small cpu int8 fallback), Groq/Gemini JSON calls with 20 s timeout.
- [ ] Commit.

### Task 7: Facecam + captions + render
- [ ] Tests: `build_ass` makes 1–3-word chunks, highlights active word with `&H00E1FF&`-style yellow tag, times relative to clip start; render of a generated 16:9 test video (ffmpeg testsrc + sine) produces 1080×1920, duration ±0.2 s, has audio.
- [ ] Implement stack/fill layouts, hook box, credit tag, punch-in zoom, loudnorm, NVENC→x264.
- [ ] Commit.

### Task 8: Scheduler + YouTube
- [ ] Tests: 9th normal post in a day refused; exceptional allowed up to +3; same streamer twice in a row refused; ≥60 min spacing; 4th from one streamer refused.
- [ ] Implement `YouTubeUploader` (installed-app OAuth, token in `secrets/youtube_token.json`, resumable upload, category 20, `selfDeclaredMadeForKids=False`).
- [ ] Commit.

### Task 9: Governor + app wiring + autostart
- [ ] Tests: governor reports `busy` when fake GPU util by foreign process > 50% or fullscreen app; n_a capped to 3 when busy.
- [ ] Implement `App` loop: scout every 120 s, detector tick 1 s, moment → wait for end → extract → enrich → score → render → queue → scheduler every 60 s → upload. Disk guard. Keep-awake via `SetThreadExecutionState` while any channel live.
- [ ] `scripts/install_autostart.ps1` (Task Scheduler on logon) — run only with user OK.
- [ ] Commit.

### Task 10: Accounts + dry run
- [ ] Guide user: Twitch app, Google OAuth client, YouTube sign-in, optional Groq key.
- [ ] Run 30–60 min with `privacy: private`; inspect clips; switch to `public`.
