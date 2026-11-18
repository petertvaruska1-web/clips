"""Profanity masking and slur detection for captions and titles."""
from __future__ import annotations

import re

# Slurs are always masked in captions and block a clip from posting.
_SLUR_PATTERNS = [r"n[i1!]gg+(?:a|er|uh|ah|az|ers)?s?", r"f[a@]gg?(?:ot|it|y)?s?", r"r[e3]t[a@]rd(?:ed|s)?",
                  r"tr[a@]nn(?:y|ie)s?", r"ch[i1]nks?", r"sp[i1]cs?", r"k[i1]kes?", r"c[o0]{2}ns?"]
SLUR_RE = re.compile(r"\b(?:" + "|".join(_SLUR_PATTERNS) + r")\b", re.I)
# Ordinary swearing: kept in captions, removed from titles/hooks.
PROFANITY_RE = re.compile(r"\b(?:fuck\w*|shit\w*|bitch\w*|motherfuck\w*|dick\w*|pussy|cunt\w*|ass(?:hole)?s?|damn)\b",
                          re.I)


def has_slur(text: str) -> bool:
    return bool(SLUR_RE.search(text or ""))


def mask_slurs(text: str) -> str:
    return SLUR_RE.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), text)


def mask_profanity(text: str, drop: bool = False) -> str:
    text = mask_slurs(text)
    if drop:
        return re.sub(r"\s{2,}", " ", PROFANITY_RE.sub("", text)).strip()
    return PROFANITY_RE.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), text)
