"""Free AI judge + title writer (Groq -> Gemini -> template), spec §6.6."""
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field

import httpx

from .safety import has_slur, mask_profanity

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_VISION_MODEL = "qwen/qwen3.8-27b"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = "gemini-flash-lite-latest"

TEMPLATES = {
    "funny": ["{n} can't stop laughing in GTA 6 😭", "{n} lost it at this GTA 6 moment 😭",
              "This GTA 6 moment broke {n} 💀"],
    "shock": ["{n} was NOT ready for this in GTA 6 😳", "{n} can't believe what GTA 6 just did 😳"],
    "hype": ["{n} just pulled this off in GTA 6 🔥", "{n}'s chat went crazy for this GTA 6 play 🔥"],
    "fail": ["{n} instantly regretted this in GTA 6 💀", "{n} fumbled hard in GTA 6 💀"],
    "scare": ["{n} got jump scared in GTA 6 😱"],
    "wholesome": ["{n} had the sweetest GTA 6 moment ❤️"],
    "reaction": ["{n}'s chat exploded over this GTA 6 moment", "{n} reacts to GTA 6 chaos"],
}
HOOKS = {"funny": "WAIT FOR IT", "shock": "HE WAS NOT READY", "hype": "WATCH THIS", "fail": "THIS WENT WRONG",
         "scare": "TURN YOUR SOUND UP", "wholesome": "THIS IS WHOLESOME", "reaction": "CHAT WENT CRAZY"}

PROMPT = """You review short clips from a live Twitch stream of the video game GTA 6 (Grand Theft Auto VI) for a YouTube Shorts clip channel.
Streamer: {display} (twitch.tv/{streamer}). Chat reaction type: {category}.
Transcript of the clip (speech recognition, may contain errors):
\"\"\"{transcript}\"\"\"
Most common chat messages during the reaction: {chat}

Return ONLY a JSON object with these keys:
- "watchability": integer 0-10, how enjoyable and understandable this clip is for someone who doesn't follow the streamer (10 = viral, 0 = boring or makes no sense without context)
- "category": one of funny, shock, hype, fail, scare, wholesome, reaction
- "spoiler_risk": "low", "med" or "high" (high = reveals GTA 6 story twists, mission endings or character deaths)
- "safety_flags": list from ["slur", "sexual", "doxxing", "self_harm", "violence_real"] (empty if none)
- "off_topic": true if this is not about the GTA 6 gameplay (e.g. reading donations, talking about real life)
- "title": catchy YouTube Shorts title under 70 characters, must contain the streamer's name and "GTA 6", may end with one emoji, no profanity, no false claims
- "hook": 2-6 word ALL CAPS on-screen hook that makes people keep watching, no spoilers of the punchline
- "hashtags": 3-5 hashtags without spaces"""


@dataclass
class JudgeContext:
    streamer: str
    display: str
    category: str
    transcript: str
    chat_lines: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    title: str
    hook: str
    hashtags: list[str]
    category: str
    watchability: float | None = None
    spoiler_risk: str = "low"
    safety_flags: list[str] = field(default_factory=list)
    off_topic: bool = False
    source: str = "template"


def clean_title(title: str, limit: int = 90) -> str:
    t = re.sub(r"\s+", " ", mask_profanity(title, drop=True)).strip()
    return t if len(t) <= limit else t[: limit - 1].rsplit(" ", 1)[0] + "…"


def template_verdict(ctx: JudgeContext) -> Verdict:
    cat = ctx.category if ctx.category in TEMPLATES else "reaction"
    title = random.choice(TEMPLATES[cat]).format(n=ctx.display)
    flags = ["slur"] if has_slur(ctx.transcript) else []
    return Verdict(title=clean_title(title), hook=HOOKS[cat], category=cat, safety_flags=flags,
                   hashtags=["#GTA6", "#GTAVI", f"#{ctx.streamer}", "#gaming"])


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def _call_groq(key: str, prompt: str) -> dict:
    r = httpx.post(GROQ_URL, timeout=25, headers={"Authorization": f"Bearer {key}"}, json={
        "model": GROQ_MODEL, "temperature": 0.6, "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return _parse(r.json()["choices"][0]["message"]["content"])


def _call_gemini(key: str, prompt: str) -> dict:
    r = httpx.post(GEMINI_URL.format(model=GEMINI_MODEL), params={"key": key}, timeout=25, json={
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6}})
    r.raise_for_status()
    return _parse(r.json()["candidates"][0]["content"]["parts"][0]["text"])


def judge(ctx: JudgeContext, keys: dict[str, str]) -> Verdict:
    base = template_verdict(ctx)
    prompt = PROMPT.format(display=ctx.display, streamer=ctx.streamer, category=ctx.category,
                           transcript=ctx.transcript[:3000] or "(no speech)",
                           chat=", ".join(ctx.chat_lines[:15]) or "(none)")
    for name, fn in (("groq", _call_groq), ("gemini", _call_gemini)):
        key = keys.get(name)
        if not key:
            continue
        try:
            j = fn(key, prompt)
        except Exception as e:
            log.warning("judge %s failed: %s", name, e)
            continue
        title = clean_title(str(j.get("title") or base.title))
        if ctx.display.split()[0].lower() not in title.lower() or "gta" not in title.lower():
            title = base.title
        flags = [f for f in j.get("safety_flags") or [] if isinstance(f, str)]
        if has_slur(ctx.transcript) and "slur" not in flags:
            flags.append("slur")
        tags = [h if h.startswith("#") else "#" + h for h in (j.get("hashtags") or []) if isinstance(h, str)]
        try:
            watch = float(j.get("watchability"))
        except (TypeError, ValueError):
            watch = None
        return Verdict(title=title, hook=mask_profanity(str(j.get("hook") or base.hook), drop=True).upper()[:40],
                       hashtags=[t.replace(" ", "") for t in tags][:5] or base.hashtags,
                       category=str(j.get("category") or base.category), watchability=watch,
                       spoiler_risk=str(j.get("spoiler_risk") or "low"), safety_flags=flags,
                       off_topic=bool(j.get("off_topic")), source=name)
    return base


VISION_PROMPT = ("This image is a strip of frames from one video clip. Does any frame show nudity (bare buttocks, genitals or breasts), including of video game "
                 "characters? Answer only JSON {\"nudity\": true/false, \"what\": \"...\"}.")


def _call_groq_vision(key: str, jpg: bytes) -> str:
    import base64
    import time
    for attempt in range(4):
        r = httpx.post(GROQ_URL, timeout=40, headers={"Authorization": f"Bearer {key}"}, json={
            "model": GROQ_VISION_MODEL, "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()}}]}]})
        if r.status_code == 429 and attempt < 3:
            time.sleep(min(30.0, float(r.headers.get("retry-after", 5 * (attempt + 1)))))
            continue
        break
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def frames_have_nudity(frames: list[bytes], key: str, caller=_call_groq_vision) -> bool | None:
    """True if any frame shows nudity, False if all clean, None if the check couldn't run."""
    if not key or not frames:
        return None
    try:
        for jpg in frames:
            if _parse(caller(key, jpg)).get("nudity") is True:
                return True
        return False
    except Exception as e:
        log.warning("vision check failed: %s", e)
        return None
