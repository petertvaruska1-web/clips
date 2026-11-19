"""Word-pop captions, hook and credit as an ASS subtitle file (spec §6.7)."""
from __future__ import annotations

import re

from .safety import mask_slurs
from .transcribe import Word

W, H = 1080, 1920
YELLOW = "&H00E1FF&"    # ASS is &HBBGGRR& -> #FFE100
WHITE = "&HFFFFFF&"
FONT = "Montserrat ExtraBold"

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,1,0,1,9,4,5,60,60,0,1
Style: Hook,{font},64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,18,0,5,60,60,0,1
Style: Credit,{font},34,&H4DFFFFFF,&H4DFFFFFF,&H80000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,7,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(text: str) -> str:
    text = mask_slurs(text).upper()
    return re.sub(r"[{}\\]", "", text).strip()


def chunk_words(words: list[Word], max_words: int = 3, max_gap: float = 0.6, max_dur: float = 1.3) -> list[list[Word]]:
    chunks: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur and (len(cur) >= max_words or w.start - cur[-1].end > max_gap
                    or w.end - cur[0].start > max_dur or cur[-1].text[-1:] in ".!?"):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words: list[Word], clip_start: float, hook: str, credit: str, layout: str,
              clip_len: float | None = None, hook_dur: float = 2.5, cap_y: int | None = None,
              hook_y: int | None = None, credit_an: int = 7) -> str:
    cap_y = cap_y if cap_y is not None else int(H * 0.62)
    if hook_y is None:
        hook_y = 672 if layout == "stack" else 300
    lines = [HEADER.format(font=FONT)]
    chunks = chunk_words(words)
    for k, chunk in enumerate(chunks):
        texts = [_clean(w.text) for w in chunk]
        nxt = chunks[k + 1][0].start if k + 1 < len(chunks) else None
        chunk_end = chunk[-1].end + 0.5
        if nxt is not None:
            chunk_end = min(chunk_end, nxt)
        chunk_end = max(chunk_end, chunk[-1].start + 0.3)
        for i, w in enumerate(chunk):
            start = w.start - clip_start
            end = (chunk[i + 1].start if i + 1 < len(chunk) else chunk_end) - clip_start
            if clip_len is not None:
                if start >= clip_len:
                    continue
                end = min(end, clip_len)
            if end <= 0 or end <= start:
                continue
            parts = []
            for j, t in enumerate(texts):
                if j == i:
                    parts.append("{\\c" + YELLOW + "\\fscx112\\fscy112}" + t + "{\\c" + WHITE + "\\fscx100\\fscy100}")
                else:
                    parts.append(t)
            pop = "{\\pos(540," + str(cap_y) + ")" + ("\\fscx115\\fscy115\\t(0,80,\\fscx100\\fscy100)" if i == 0 else "") + "}"
            lines.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{pop}{' '.join(parts)}")
    if hook:
        lines.append(f"Dialogue: 2,{_ts(0)},{_ts(hook_dur)},Hook,,0,0,0,,"
                     "{\\pos(540," + str(hook_y) + ")\\fad(0,200)}" + _clean(hook))
    if credit:
        end = clip_len if clip_len else 3600
        an = "" if credit_an == 7 else "{\\an" + str(credit_an) + "}"
        lines.append(f"Dialogue: 0,{_ts(0)},{_ts(end)},Credit,,0,0,0,,{an}{credit.replace('{', '')}")
    return "\n".join(lines) + "\n"
