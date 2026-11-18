# GTA 6 Shorts Clipper ("ClipForge") — Design

- Date: 2026-11-18
- Status: draft, waiting for the user's approval
- Builder: Claude (inline, in this project folder)
- Location: `C:\Users\petko\Desktop\clips`

---

## 1. What this is and why

ClipForge is an always-on program on the user's Windows PC. It watches the biggest English-speaking Twitch streams of Grand Theft Auto VI and finds the moments viewers react to most. It turns each moment into a polished vertical Short with captions and publishes it to the user's YouTube channel automatically.

GTA 6 launched on 19 Nov 2026 at midnight local time, on PS5 and Xbox Series only. Launch weeks are the biggest window a GTA clip channel will ever get. What matters most is finding genuinely good moments, being among the first to post them, and needing almost no babysitting.

**Assumed goal** (the user didn't say; this is Claude's assumption): grow a GTA 6 Shorts channel fast, and monetize it later. If the goal is different, the streamer weights (§7) and the posting volume (§6.8) change.

## 2. Goals, non-goals, anti-goals

### Goals
- **G1: Accurate moment finding.** Combine several chat and stream signals, each judged against the channel's own normal level. A single "chat got fast" threshold is not enough.
- **G2: Clips that make sense on their own.** Start before the cause: by default, ~20 s before the estimated event, which is the user's rule. End when the reaction is over. Never cut mid-word.
- **G3: Clean, consistent edits.** 9:16 format, facecam above gameplay, word-by-word pop captions, a hook line, a credit tag.
- **G4: Fully automatic publishing** to YouTube Shorts, at a sensible pace.
- **G5: $0 running cost.** Free tools, free API tiers, the user's PC.
- **G6: Minimal babysitting.** ClipForge picks streamers itself, starts with Windows, and adapts to however the PC is being used. It recovers missed hours from replays (VODs) and reports to the user's phone (Phase 2).

### Non-goals (for now)
- TikTok, Instagram, or other platforms. The output format already fits them, so they can be added later.
- Non-English streams.
- Kick or YouTube Live as sources. Some launch streams happen there, so these are candidates for later.
- Heavy edits: music, sound effects, memes, AI voice-over.

### Anti-goals (a failure even if it technically works)
- Posting broken or confusing clips: the cause cut off, mid-sentence starts, wrong crops.
- Posting story spoilers, slurs, sexual content, or private information. Strikes and takedowns kill a channel.
- Spam behavior: near-duplicate uploads, or dozens of uploads an hour.
- Making the PC unpleasant to use: lag while gaming, a full disk.
- Anything that quietly starts costing money.

## 3. Constraints

- **Free only.** No paid APIs or services, ever.
- **Host is the user's PC:**
  - Ryzen 5 5500 (6 cores / 12 threads), 32 GB RAM.
  - RTX 3050 8 GB, which provides NVENC hardware encoding and CUDA.
  - ~37 GB free on C:, 1 Gbps network card. Internet speed is unknown and gets measured at setup.
  - Already installed: Python 3.14, ffmpeg 8.1 (gyan "full" build with libass and NVENC), git, Node.
  - ClipForge uses its own Python 3.12 environment (via `uv`) so that every library has working Windows wheels.
- **PC use is unpredictable** (stated by the user). At any moment the PC may be off, asleep, idle, or running a game. The design must cope with all of these without the user doing anything.
- **Platform facts** (checked 2026-11-18):
  - YouTube Data API: an upload costs 1 unit from a 100-uploads-per-day bucket. Unverified projects are not forced to private.
  - Twitch: Helix API (free app token, 800 points per minute) plus anonymous IRC chat reading.
  - VODs are kept ~60 days for Partners and ~7 days for regular accounts, and only if the streamer keeps them on.
- **Rights.** The footage belongs to the streamers. Rockstar's policy tolerates fan videos but takes down story spoilers. Mitigations: credit, real editing, a spoiler guard, and an automatic blocklist after claims.
- **Time.** The end-to-end workflow must run today (2026-11-18). Refinements follow in the next days.

## 4. Approaches considered

### How moments are captured

| Approach | Pros | Cons |
|---|---|---|
| **A. Live rolling recording**: keep the last few minutes of each stream, save on detection | Fastest (a Short can be public about 10 min after the moment); works even when VODs are off | ~4–8 Mbps of download per stream, so ~8 streams at once; Twitch ad breaks leave gaps in the recording |
| **B. Chat-only watching, cut from the VOD** | Scales to 30+ channels; source quality (1080p60) with no ads | Needs public VODs; runs minutes behind live; VOD audio may be muted where copyrighted music played |
| **C. Viewers' Twitch clips as the source** | Simplest to build | Every competing clip channel gets the same clips; clips are capped at 60 s and framed by the viewer; downloading them isn't officially supported |

**Chosen: A + B combined** (Claude's call; the user handed over the how). Live recording covers the top ~8 GTA 6 streams at any moment. Chat-only watching with VOD cuts covers the next ~25. From C, only the data is used: how many viewers clipped a moment becomes a scoring signal.

### Where it runs
**Chosen: the user's PC.** Oracle's Always Free cloud server was cut to 2 ARM cores / 12 GB in mid-2026 and is hard to get, and no other free host has enough power. The PC's GPU makes transcription and encoding fast. All code stays portable, so it could move later.

### Where it posts
**YouTube Shorts only** (the user's decision). TikTok's app audit is a bottleneck for automatic public posting.

## 5. Workflow overview

```
            every 2 min
 [Scout] ──picks──▶ Tier A (top ~8, live recorded)     Tier B (next ~25, chat only)
                         │                                   │
                 [Live recorder]                      (VOD on demand)
                         │                                   │
 [Chat listener] ──▶ [Moment detector] ──candidate──▶ [Clip extractor]
                                                           │ raw clip
                                                     [Enrich + score]
                                     transcript · audio · viewer clips · AI judge
                                                           │ approved
                                                      [Editor / renderer]
                                                           │ 1080×1920 MP4
                                                       [Scheduler]
                                                           │
                                                  [YouTube publisher]
                                                           │
                                                  [Tracker → learning]

 Always on: [PC governor] · [Catch-up from VODs] · [Disk guard] · [Notifier (Phase 2)]
```

**Latency target** for a top moment: 10 minutes or less from happening on stream to a public Short.

## 6. Components

### 6.1 Scout — who to watch
- Looks up the Twitch category ID once: `GET /helix/games?name=Grand Theft Auto VI`. The result is cached in config.
- Every 2 min, calls `GET /helix/streams?game_id=<id>&language=en&type=live&first=100`.
- **Priority** = live viewers × streamer weight (curated list, §7; default 1.0) × session bonus. The session bonus favors a streamer's first hours of GTA 6, which are the richest.
- **Tier A** (live recording): the top N_A channels. N_A defaults to 8 and is lowered by the governor (§6.10) and by bandwidth.
- **Tier B** (chat only + VOD cuts): the next N_B (default 25). Only channels with a public in-progress VOD qualify, checked with `GET /helix/videos?user_id=…&type=archive&first=1`.
- **Hysteresis:** a channel keeps its tier for at least 15 min unless it goes offline or leaves the category, so channels don't churn.
- A channel that leaves the GTA VI category is no longer clipped, because only GTA 6 moments are posted.
- **Blocklist:** streamers who object, or whose clip caused a claim, are never followed.
- Twitch app access token (client-credentials flow) is refreshed automatically.

### 6.2 Chat listener
- Opens one anonymous TLS IRC connection (`justinfan<random>`) with the `tags` and `commands` capabilities, and joins all Tier A and Tier B channels. Joins are kept at or below 20 per 10 s.
- **Per message, keep:**
  - `tmi-sent-ts` (server time in ms)
  - a hashed user ID (raw IDs are not stored)
  - the text, emote ranges, and badges (sub, mod, vip, broadcaster)
  - the `first-msg` flag
- **Other events tracked:**
  - `USERNOTICE`: raid (with viewer count), sub, gift bomb (with count), announcement
  - `ROOMSTATE`: emote-only and slow mode
  - `CLEARCHAT` and `CLEARMSG`
- **Emote dictionary per channel:** Twitch emotes come from the message tags. 7TV, BTTV, and FFZ channel and global sets come from their free public APIs and are refreshed hourly.
- **Ignored for scoring:**
  - known bots (Nightbot, StreamElements, Fossabot, Moobot, Sery_Bot, and a list kept in config)
  - commands starting with `!`
  - the broadcaster's own messages, which are kept separately
- **Storage:** all chat is saved as gzip JSONL per stream session, roughly tens of MB per day. It's used for tuning and catch-up.

### 6.3 Live recorder (Tier A)
- **Pipeline:** `streamlink --twitch-low-latency twitch.tv/<ch> 1080p60,720p60,best -O` is piped into `ffmpeg -c copy -f segment -segment_time 4 -strftime 1 …`.
- This produces ~4 s MPEG-TS segments named with their arrival time in wall-clock milliseconds. A segment index maps time ranges to files.
- **Ring buffer:** the last 4 minutes per channel (~200 MB at 7 Mbps). Segments that a pending moment needs are pinned until extraction.
- **Gaps:** ad breaks and reconnects are recorded as holes in the index. A moment that overlaps a hole falls back to the VOD (§6.5).
- **Bandwidth:** total recording stays at or below 60% of measured downstream. Over budget, channels drop to 720p60 first, then N_A shrinks.
- **Watchdog:** a recorder with no new segment for 20 s is restarted. A failure in one channel never affects the others.

### 6.4 Moment detector — the metrics
Everything is computed per channel on 1-second bins. Every value is compared with that channel's own recent normal, so a 3k-viewer chat and a 60k-viewer chat are judged fairly.

**Baseline:** a rolling 15-minute window that excludes seconds inside detected bursts. Uses robust statistics: median and MAD of log(1 + rate).

**Signals** (5-second windows unless noted):
1. **Chat velocity:** messages per second vs baseline (robust z-score).
2. **Unique-chatter velocity:** distinct chatters per second vs baseline. This is the main signal, because a handful of spammers can't fake it.
3. **Reaction intensity by type:** share of messages hitting a reaction lexicon, compared with the baseline share.
   - funny: KEKW, LUL/LULW, OMEGALUL, ICANT, LMAO/LMFAO, 😂 🤣 💀, HAHA…, pepeLaugh, xdd, "im crying", "dead"
   - hype: POG/PogU/Pog/POGGERS, W, "LETS GO", HOLY, INSANE, 🔥, EZ, Clap, GOATED
   - shock: WTF, "???", WHAT, "NO WAY", OMG, monkaS/monkaW, D:, 😳 😱, BRO
   - fail: L, F, RIP, Sadge, "unlucky", "throw"
   - scare: monkaS, 😱, JUMPSCARE, AHHH
   - wholesome: <3, ❤️, aww, peepoHappy
   - Text is normalized first: case-folded, and repeated letters collapsed ("LMAOOOO" → "lmao"). Emotes are recognized from the channel dictionary.
   - **Learned reaction tokens:** any token at least 4× more frequent inside this channel's past bursts than at baseline joins its lexicon automatically. This catches channel-specific emotes.
4. **"Clip it" demand:** messages containing clip, clipped, "clip that", 📸, or `clips.twitch.tv` links, plus clip-bot announcements, over a 10 s window. Chat is explicitly asking for a clip, so this is a strong signal.
5. **Chat unison:** the share of messages containing the single most common token in the window, vs baseline. When everyone spams the same reaction, something big happened.
6. **Caps and punctuation storms:** the share of ALL-CAPS messages and of "???" / "!!!" floods.
7. **Burst shape:** rise time from baseline to peak. A sudden rise means a discrete event (crash, jump-scare, punchline). A slow rise means a situation that built up (a chase). Burst shape drives pre-roll length and category.

**Penalties** that suppress false positives:
- a raid in the last 120 s, scaled by raid size
- gift-sub bombs in the last 45 s
- bits and TTS bursts
- poll and prediction results
- "AD" spam during ad breaks
- greeting and goodbye waves in the first and last 3 minutes of a session
- emote-only or slow-mode switches (these reset the baseline)
- copypasta trains: near-duplicate messages of 60 characters or more

**Hype score:**

```
H(t) = logistic( 1.0·z_unique + 0.6·z_velocity + 0.8·reaction_lift + 0.9·clip_demand
                 + 0.5·unison_lift + 0.3·caps_lift − penalties − bias )
```

These are starting weights, tuned later on launch-week data (§6.12).

**Trigger:**
- A burst opens when H(t) stays above the channel's adaptive threshold for at least 2 s. The threshold is about the top 1.5% of the last hour's H values, with a floor.
- The burst closes when H stays below 0.6 × threshold for 4 s.
- Bursts less than 20 s apart merge. A 30 s cooldown follows each burst.
- Expected volume: about 4–12 candidates per channel-hour.

**Event timing** (why the clip starts before the reaction):
- **Chat onset, `t_on`:** walk back from the peak to the first second where rate exceeds baseline + 2 MAD.
- **Chat lag, `L`:** stream latency + reaction time + typing time. Defaults to 7 s and is learned per channel. It's the median gap between chat onset and the matching audio spike, over high-confidence moments.
- **Event estimate:** `t_ev = t_on − L`. When the recording exists, `t_ev` snaps to the strongest audio transient (yell, crash, gunshot) in `[t_ev − 8 s, t_ev + 3 s]`.
- **Clip start:** `t_ev − pre-roll`.
  - Pre-roll is 20 s by default (the user's rule), and 25–30 s for slow-building moments.
  - The start then snaps back to the nearest sentence start or pause in the transcript.
- **Clip end:** reached when the reaction is over. The streamer's voice energy must be back near baseline for 1.5 s and chat below 40% of its peak; then add 1 s. The end is always at least peak + 4 s.
- **Length:** 15–60 s, aiming for 25–45 s. Over-long clips are trimmed from the front, always keeping at least 10 s before `t_ev`.
- **Category:** the dominant reaction type. It sets the title tone and the caption accent color.

### 6.5 Clip extractor
- **Tier A:**
  1. Wait until the clip end is in the buffer.
  2. Concatenate the covering segments with stream copy and 3 s margins.
  3. Trim precisely at render time.
- **Tier B, or a gap in the buffer:**
  1. Take the in-progress VOD.
  2. Compute the offset: `t − vod.created_at`.
  3. Run `yt-dlp --download-sections "*a-b"`, retrying until the VOD has advanced past `b + 30 s`. In-progress VODs trail live by a few minutes.
- If neither works (VODs off or subscriber-only, and no buffer), the moment is dropped and logged.

### 6.6 Enrichment and final score
- **Audio:**
  - short-term loudness curve
  - strength of the event transient
  - duration of the reaction
  - optional laughter and scream tags (YAMNet, Phase 3)
- **Transcript:**
  - faster-whisper `large-v3-turbo` on the GPU (int8_float16) with word timestamps and VAD
  - when the governor says the GPU is busy, falls back to `small` on the CPU
- **Viewer clips:**
  - `GET /helix/clips?broadcaster_id=…&started_at=…`, re-checked 5 and 15 min after the moment
  - counts distinct viewer clips covering `t_ev ± 15 s`, normalized by the channel's usual clip rate
  - viewer clip titles also feed the title generator
- **AI judge** (free tiers, optional):
  - **Input:** transcript, top chat lines, streamer, category. Goes to Groq (≈1,000 free requests/day) first, Gemini Flash-Lite (≈500/day) second.
  - **Output (strict JSON):**
    - `watchability` 0–10: understandable without context, and actually funny or surprising
    - `category`
    - `spoiler_risk` low/med/high
    - `safety_flags`: slurs, sexual content, doxxing, self-harm
    - `off_topic`: not GTA gameplay
    - `title` (70 characters or fewer)
    - `hook` (6 words or fewer)
    - 3–5 `hashtags`
  - **No AI available** (quota spent or no key): template titles, no judge.
- **Final score S (0–1):**

  ```
  S = (0.35·H_peak + 0.15·burst_size + 0.20·viewer_clips + 0.10·audio_excitement
       + 0.20·AI_watchability) × streamer_factor − penalties
  ```

- **Hard rejects:**
  - any safety flag
  - spoiler risk "high" during the first 30 days after launch
  - off-topic
  - shorter than 12 s
  - no speech, no strong audio, and no viewer clips all at once

### 6.7 Editor
**Output:** 1080×1920 H.264, using NVENC and falling back to x264. Keeps the source frame rate (60 fps when available). AAC 160 kbps, loudness normalized to −14 LUFS, `faststart`, 60 s or shorter.

**Layouts** are auto-chosen per streamer and cached, and can be overridden in config:
- **Stack**, when a facecam is found: the top ~35% is the facecam crop, the bottom ~65% a gameplay crop centered on the action.
- **Fill**, with no facecam: gameplay scaled to width with ~1.2× zoom, over a blurred, darkened, enlarged copy of itself.
- **Facecam detection:**
  - OpenCV's YuNet face detector runs on ~12 frames.
  - A face that stays in the same region gives the webcam box: the face box expanded and snapped to the overlay edges.
  - Re-checked every 30 minutes.

**Captions:**
- Word timings come from the transcript, shown 1–3 words at a time.
- UPPERCASE, Montserrat ExtraBold (free OFL font), white with a thick black outline and a soft shadow.
- The word being spoken pops in (110% → 100% over 80 ms) and turns yellow (#FFE100).
- Placed at ~62% of the frame height, inside the Shorts safe zone: clear of the bottom 20% and the right-side buttons.
- Slurs are masked. Ordinary swearing stays in captions but never appears in titles.

**Other elements:**
- **Hook:** shown for the first 2.5 s, centered on the line between facecam and gameplay (or in a top band in the fill layout). It's the AI or template hook in white text on a black rounded box, for example "KAI MEETS LEONIDA COPS".
- **Punch-in:** at `t_ev`, the frame zooms from 1.0 to 1.08 over 0.25 s, holds ~1.5 s, then eases out.
- **Credit:** a small `twitch.tv/<streamer>` tag, top-left at 70% opacity, for the whole clip.

**Sanity checks before posting:**
- duration within range
- audio not silent
- captions present wherever there's speech
- the facecam panel actually contains a face (stack layout)
- no black stretch longer than 1 s

**Implementation:** one ffmpeg pass using a generated filter graph plus an ASS subtitle file.

### 6.8 Scheduler
- **Daily budget:** 8 Shorts by default, configurable from 1 to 30 (the API cap is 100). Uploads are at least 60 min apart and lean toward US and EU evening peaks.
- **Exceptional moments** post immediately, ignoring the slots, up to 3 extra a day, because first to post wins. A moment is exceptional when S ≥ 0.9 or when at least 3 viewers clipped it.
- **Freshness decay:** a moment's value has a ~6-hour half-life. Fresh moments beat the backlog, and catch-up moments fill empty slots.
- **Diversity:** at most 3 per streamer per day, and never the same streamer twice in a row.
- **Dedupe:** co-streams and duo sessions can produce the same moment on several channels. Moments within ±30 s with similar transcripts are grouped and only the best one is kept.

### 6.9 YouTube publisher
- **Sign-in:** official YouTube Data API v3 with the OAuth "installed app" flow. The user signs in once in the browser and the refresh token is stored in `secrets/`.
- **OAuth app status:** "In production" (unverified), so the token doesn't expire every 7 days. The user clicks through Google's "unverified app" notice once; it's their own app.
- **Metadata:**
  - title: `{title} #GTA6`, 100 characters or fewer
  - description: a credit line with the Twitch link, then hashtags (#GTA6 #GTAVI #<streamer> #Shorts)
  - tags; category 20 (Gaming); not made for kids; language en
- **Upload mechanics:** resumable upload with retries and backoff. Respects the quota, which resets at midnight Pacific.
- **After upload:** polls the video's status (processing, rejected, removed).
  - A copyright removal blocklists that streamer automatically and alerts the user.
  - After any strike, posting pauses until the user resumes it.
- **Tracking:** views and likes at 1 h, 24 h, and 7 days.

### 6.10 PC-adaptive runtime (unpredictable PC use)
- **Autostart:** starts at Windows login through Task Scheduler (with the user's OK) and runs minimized. A supervisor restarts crashed workers.
- **Governor:** every 10 s it checks CPU load, GPU load from other processes (NVML), whether a full-screen app is in front, free disk, and network throughput.
  - **Normal:** full capacity.
  - **Busy or gaming:**
    - Tier A drops to 3 streams or fewer, at 720p.
    - Transcription moves to the CPU `small` model at low priority.
    - Non-urgent renders and uploads wait. Exceptional moments still go out.
  - All ClipForge processes always run at below-normal priority.
- **Sleep:** the PC is kept awake only while followed streams are live. This uses the Windows "system required" request, the same way video players do, and doesn't change any settings. If the user puts the PC to sleep or shuts it down, ClipForge never resists.
- **Catch-up after downtime** (Phase 2): when the PC was off or asleep, or ClipForge was closed, startup looks back at priority streamers and top GTA 6 streams that were live during the gap.
  1. Viewer clips, plus chat replay when available, become moments.
  2. Those moments are cut from the VODs.
  3. They go through the normal pipeline with freshness decay.
  Launch week is backfilled the same way on the first run.
- **Disk guard:** total working data stays at or below 15 GB.
  - Ring buffers, and raw clips deleted after render.
  - Final clips kept 3 days after upload.
  - Chat compressed, logs rotated.
  - Recording pauses below 5 GB free.

### 6.11 Notifications and control (Phase 2, free, optional)
- **Telegram bot sends:** each published Short (link, streamer, score), a daily summary, and alerts (YouTube sign-in expired, claim or strike, low disk, Twitch auth failing).
- **Commands:**
  - `/status`, `/pause`, `/resume`, `/queue`
  - `/post <id>`, `/skip <id>`
  - `/review on|off` turns on approval mode, which is off by default.

### 6.12 Learning loop
- Every moment's features and outcome are stored: viewer clips, and our Short's views at 24 h.
- **Days 2–3:** tune weights and thresholds on launch-week data. Fit a logistic model of "did viewers clip this?" on the chat features, and report precision and recall against viewer clips. This is the accuracy number.
- **Later:** weekly re-weighting from our own Shorts' performance, with bounded changes.

## 7. Streamers

**Default:** auto-discovery. ClipForge follows whoever is biggest live in Grand Theft Auto VI (English) at the moment. The curated list adds weight (×1.2–1.5) and a guaranteed slot when the streamer is live in GTA VI. Viewer numbers are from TwitchTracker, English channels, October 2026.

| Priority | Streamers |
|---|---|
| **S** (×1.5) | KaiCenat (has promised a 100% GTA 6 marathon), caseoh_ (~60k avg), xQc (GTA veteran), TheBurntPeanut (~43k), stableronaldo (~38k, warmed up with a GTA V marathon), zackrawrr (~41k), Jynxzi (~28k) |
| **A** (×1.2) | HasanAbi, jasontheween, Lacy, PlaqueBoyMax, yourragegaming, BruceDropEmOff, RDCgaming, sodapoppin, LIRIK, summit1g, MOONMOON, Emiru, QTCinderella, Schlatt, IShowSpeed |

**Why these:**
- They have the biggest English chats, so detection is reliable.
- They're reaction-heavy personalities whose moments make sense without context.
- Their names drive Shorts search.
- They have GTA history.
- Mid-tier names get extra value because fewer competing clip channels cover them.

**Context:**
- GTA RP communities can't move to GTA 6 until a PC version exists.
- Much of the GTA RP audience has moved to Kick.
- Some launch streams run on YouTube (a 24-hour launch event).
- Kick and YouTube Live are therefore future sources.

## 8. Data, config and storage

```
C:\Users\petko\Desktop\clips\
  clipforge\        Python package (one main process + worker subprocesses)
  config.yaml       streamers, weights, limits, layouts, caption style, budgets
  secrets\          Twitch app id/secret, Google OAuth client + token, AI keys, Telegram token (git-ignored)
  data\clipforge.db SQLite: channels, sessions, moments, clips, uploads, metrics
  data\buffer\      ring buffers
  data\raw\         raw clips (deleted after render)
  data\out\         rendered Shorts (kept 3 days after upload)
  data\chat\        chat logs (jsonl.gz)
  logs\             rotating logs
  assets\fonts\     Montserrat (OFL)
  assets\models\    YuNet face detector (ONNX)
  docs\             this design and the build plan
```

## 9. Tech stack (all free)

- **Core:** Python 3.12 in a `uv` virtual environment. SQLite and asyncio from the standard library.
- **Stream and video:** streamlink, yt-dlp, ffmpeg 8.1 (already installed).
- **Analysis:** faster-whisper (CUDA), OpenCV, numpy.
- **Network and APIs:** httpx, websockets, google-api-python-client, google-auth-oauthlib.
- **System and tests:** psutil, nvidia-ml-py, PyYAML, pytest.
- **Phase 2:** python-telegram-bot.
- **AI judge:** Groq free tier (primary) and Gemini free tier (fallback). Both are optional and degrade to templates.

## 10. What the user sets up (Claude guides each step in the browser pane)

1. A YouTube channel for the Shorts, existing or new.
2. A Google Cloud project with the YouTube Data API v3 enabled and an OAuth client of type Desktop. Set the consent screen to "In production", then sign in once.
3. A Twitch developer app at dev.twitch.tv (the Twitch account needs 2FA), giving a Client ID and Secret.
4. Optional: a Groq and/or Gemini API key, and a Telegram bot via @BotFather.
5. An OK for auto-start at Windows login.

## 11. Build phases

**Phase 1, today: the whole workflow running end to end.**
- scout, chat listener, live recorder, moment detector, buffer extraction
- transcription, editor (both layouts, captions, hook, credit, punch-in), AI titles
- scheduler, YouTube publisher, basic governor, auto-start, logs
- Before going public, a dry run on live GTA 6 streams with uploads set to private.

**Phase 2, the next 1–2 days:**
- Tier B VOD cutting
- catch-up and launch-week backfill
- viewer-clip scoring
- Telegram bot
- detector tuning on launch-week data, with an accuracy report

**Phase 3, later:**
- automated learning loop
- laughter and scream audio tags
- music removal, to avoid music claims
- local dashboard
- more platforms and sources (TikTok, Kick, YouTube Live)

## 12. Testing and acceptance

- **Unit tests:**
  - text normalization and lexicon matching
  - robust baselines and z-scores
  - trigger hysteresis
  - event-time estimation and clip-window math
  - segment index and gap handling
  - caption chunking and ASS generation
  - scheduler rules and governor states
- **Replay test:** a real recorded stream segment plus its chat runs through the pipeline and produces sensible moments and renders.
- **Live dry run:** 30–60 min on live GTA 6 streams with uploads set to private. Inspect the clips, then switch to public.
- **Phase 1 acceptance:**
  - (a) Followed channels follow the GTA VI directory automatically.
  - (b) At least 70% of rendered dry-run clips make sense on their own.
  - (c) A top moment reaches a public Short in 10 minutes or less.
  - (d) ClipForge survives sleep and restart and resumes by itself.
  - (e) Disk use stays within budget.

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Copyright claims or strikes | Credit, real edits, spoiler guard, auto-blocklist, posting pause after a strike |
| Rockstar spoiler takedowns | Spoiler guard (AI judge) for the first 30 days |
| Free tiers changing (AI, Twitch) | Every optional service degrades gracefully: template titles, fewer signals |
| Twitch ad gaps in recordings | VOD fallback (Phase 2) |
| Many competing GTA 6 clip channels | Speed (≤ 10 min) and mid-tier streamer coverage |
| YouTube "reused content" rules when monetizing later | Captions, hooks, and edits help, but YouTube decides |
| Unknown internet speed | Measured at setup; capacity sized automatically |

## 14. Calls Claude made (for the user to check)

1. **Capture:** live recording for the top 8 plus chat-only/VOD for the next 25. Viewer clips are used as a signal only.
2. **Hosting:** the user's PC, with automatic slow-down while gaming and VOD catch-up after downtime.
3. **Streamers:** auto-discovered from the GTA VI category, English only, with the curated S and A lists boosted.
4. **Pace:** 8 Shorts a day, at least 1 hour apart, plus up to 3 immediate posts for exceptional moments. At most 3 per streamer per day.
5. **Clip shape:** about 20 s before the event, ending after the reaction, 15–60 s long (aim 25–45 s).
6. **Look:** facecam-over-gameplay stack, or blurred fill when there's no facecam. Yellow word-pop captions, a hook line, a credit tag, a punch-in zoom.
7. **Safety:** slurs masked, swearing kept in captions but not titles, and story spoilers avoided for 30 days.
8. **Fully automatic posting**, with an optional approval mode on the phone later (Phase 2).
9. **Free AI** for titles and quality checks, with template fallback.

## 15. Left to the builder

- Exact lexicon contents, thresholds, and weights (start from the values above and tune with data).
- ffmpeg filter-graph details and font sizes per layout.
- Module boundaries, file names, and retry and backoff constants.
- The AI judge prompt wording.
