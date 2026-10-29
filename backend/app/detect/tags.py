"""Recognise Rocket League point tags ("SAVE +50", "EPIC SAVE +75", "GOAL +100")."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

import numpy as np

# Points the game awards with each tag; used to boost confidence.
POINTS = {"epic_save": 75, "save": 50, "goal": 100}

# OCR often swaps letters and digits in bold game fonts.
_DIGIT_TO_LETTER = str.maketrans({"5": "S", "0": "O", "1": "I", "4": "A", "3": "E", "8": "B", "6": "G"})
_WORDS = ("EPIC", "SAVE", "GOAL", "SHOT")


# Column headers on the end-of-match scoreboard, not tags.
_IGNORE = {"SAVES", "GOALS"}


def _fuzzy_word(token: str) -> str | None:
    token = token.translate(_DIGIT_TO_LETTER)
    if token in _IGNORE:
        return None
    best, best_score = None, 0.0
    for word in _WORDS:
        score = SequenceMatcher(None, token, word).ratio()
        if score > best_score:
            best, best_score = word, score
    return best if best_score >= 0.75 else None


def classify(texts: list[str]) -> tuple[str, float] | None:
    """Map OCR text lines from one tag crop to (event_type, confidence)."""
    joined = " ".join(texts).upper()
    raw_tokens = re.findall(r"[A-Z0-9]+", joined)
    words = {w for t in raw_tokens if not t.isdigit() for w in [_fuzzy_word(t)] if w}
    # Glued tokens like "EPICSAVE".
    for t in raw_tokens:
        if t.translate(_DIGIT_TO_LETTER) in _IGNORE:
            continue
        for word in _WORDS:
            if len(t) > len(word) and word in t.translate(_DIGIT_TO_LETTER):
                words.add(word)
    points = {int(p) for p in re.findall(r"\+\s*(\d{2,3})", joined)}

    if "SAVE" in words and "EPIC" in words:
        kind = "epic_save"
    elif "SAVE" in words:
        kind = "epic_save" if 75 in points else "save"
    elif "GOAL" in words and "SHOT" not in words:  # "SHOT ON GOAL" is not a goal
        kind = "goal"
    else:
        return None

    confidence = 0.7
    if POINTS[kind] in points:
        confidence = 0.95
    elif points:
        confidence = 0.55
    return kind, confidence


def white_ratio(img: np.ndarray) -> float:
    """Share of bright, unsaturated pixels: the tag text is white."""
    b, g, r = img[..., 0].astype(np.int16), img[..., 1].astype(np.int16), img[..., 2].astype(np.int16)
    lo = np.minimum(np.minimum(b, g), r)
    hi = np.maximum(np.maximum(b, g), r)
    mask = (lo >= 215) & (hi - lo <= 30)
    return float(mask.mean())
