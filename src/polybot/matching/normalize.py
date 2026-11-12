"""Name normalization used everywhere names are compared."""

from __future__ import annotations

import re
import unicodedata

_DROP_TOKENS = {"fc", "afc", "cf", "sc", "the", "club"}
_KEEP_SHORT = {"st", "la", "ny"}
_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_name(raw: str, *, drop_generic: bool = True) -> str:
    text = strip_accents(raw).lower().replace("&", " and ").replace("'", "")
    text = text.replace("saint ", "st ").replace("st. ", "st ")
    text = _PUNCT.sub(" ", text)
    tokens = [t for t in _SPACES.sub(" ", text).strip().split(" ") if t]
    if drop_generic:
        kept = [t for t in tokens if t not in _DROP_TOKENS]
        tokens = kept or tokens
    return " ".join(tokens)


_SEPARATORS = [
    (re.compile(r"\s+@\s+"), "at"),
    (re.compile(r"\s+at\s+", re.IGNORECASE), "at"),
    (re.compile(r"\s+vs\.?\s+", re.IGNORECASE), "vs"),
    (re.compile(r"\s+v\.?\s+", re.IGNORECASE), "vs"),
    (re.compile(r"\s+-\s+"), "vs"),
]
_TRAILERS = re.compile(r"\s*(\?|:.*$|\(.*?\)|\bwinner\b|\bmoneyline\b|\bgame\s*\d+\b).*$", re.IGNORECASE)


def split_matchup(title: str) -> tuple[str, str, str] | None:
    """Split "Lakers vs. Celtics" / "LAL @ BOS" / "Los Angeles L at Boston Winner?".

    Returns ``(left, right, kind)``; for ``kind == "at"`` left is the away team, right the home team.
    """
    cleaned = title.strip()
    for rx, kind in _SEPARATORS:
        parts = rx.split(cleaned, maxsplit=1)
        if len(parts) == 2:
            left = _TRAILERS.sub("", parts[0]).strip(" .")
            right = _TRAILERS.sub("", parts[1]).strip(" .")
            if left and right:
                return left, right, kind
    return None
