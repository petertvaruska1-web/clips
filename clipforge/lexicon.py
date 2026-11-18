"""Chat text normalization and reaction categories (spec §6.4, signal 3 and 4)."""
from __future__ import annotations

import re

_REPEAT = re.compile(r"(.)\1{2,}")
_TOKEN = re.compile(r"\?{2,}|!{2,}|[\w']+|[^\w\s]", re.UNICODE)

REACTIONS: dict[str, set[str]] = {
    "funny": {"kekw", "lul", "lulw", "omegalul", "icant", "lmao", "lmfao", "lol", "😂", "🤣", "💀",
              "haha", "hahaha", "pepelaugh", "xdd", "kekl", "crying", "dead", "kek", "lmaoo", "aware",
              "pepela", "elegiggle", "jebaited", "dying", "hilarious"},
    "hype": {"pog", "pogu", "poggers", "pogchamp", "w", "ww", "www", "letsgo", "lets", "holy", "insane",
             "🔥", "ez", "clap", "goated", "goat", "peak", "cinema", "hypers", "pogg", "clean", "massive"},
    "shock": {"wtf", "???", "what", "omg", "monkas", "monkaw", "d", "😳", "😱", "bro", "nah", "noway",
              "wait", "huh", "stare", "wideeyes", "holyshit", "omgg"},
    "fail": {"l", "ll", "lll", "f", "rip", "sadge", "unlucky", "throw", "throwing", "bozo", "ratio",
             "fail", "classic", "copium", "😭"},
    "scare": {"jumpscare", "ahhh", "ahh", "scared", "monkagiga", "scary"},
    "wholesome": {"<3", "❤️", "❤", "aww", "awww", "peepohappy", "wholesome", "cute"},
    "clip": {"clip", "clipped", "clipit", "clipthat", "📸", "clips"},
}
TOKEN_CATEGORY: dict[str, str] = {}
for _cat, _toks in REACTIONS.items():
    for _t in _toks:
        TOKEN_CATEGORY.setdefault(_t, _cat)


def normalize(text: str) -> list[str]:
    """Lower-case, collapse 3+ repeated chars to 1 (LMAOOOO -> lmao), keep ??? / !!! storms."""
    out: list[str] = []
    for tok in _TOKEN.findall(text):
        if tok.startswith("??"):
            out.append("???")
        elif tok.startswith("!!"):
            out.append("!!!")
        else:
            out.append(_REPEAT.sub(r"\1", tok.lower()))
    return out


def categorize(tokens: list[str], learned: dict[str, str] | None = None) -> set[str]:
    cats: set[str] = set()
    for t in tokens:
        c = TOKEN_CATEGORY.get(t) or (learned or {}).get(t)
        if c:
            cats.add(c)
        elif t.startswith("haha") or t.startswith("lmao"):
            cats.add("funny")
        elif "clips.twitch.tv" in t:
            cats.add("clip")
    return cats
