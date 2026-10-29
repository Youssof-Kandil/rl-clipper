"""Track the top-centre scoreboard and report score increments as goals."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import numpy as np


@dataclass
class ScoreGoal:
    time: float
    team: str  # "blue" | "orange"
    score: tuple[int, int]


# The scoreboard font is squarish: OCR reads its "0" as 口/回/O/D, "3" as B and "1" as I/l.
_LOOKALIKE = str.maketrans({"口": "0", "□": "0", "回": "0", "O": "0", "o": "0", "D": "0", "Q": "0",
                            "I": "1", "l": "1", "|": "1", "S": "5", "B": "3", "Z": "2"})

# Where the two score digits and the clock sit inside the scoreboard crop
# (x0, x1, y0, y1 as fractions). Kept clear of the box edges: the edge between the
# clock panel and a score box reads as "1".
_LEFT_BOX = (0.14, 0.28, 0.10, 0.70)
_RIGHT_BOX = (0.73, 0.87, 0.10, 0.70)
_CLOCK_BOX = (0.33, 0.67, 0.10, 0.70)
# The colour behind each score, sampled a little wider than the digits.
_LEFT_BG = (0.12, 0.30, 0.15, 0.65)

ReadLine = Callable[[np.ndarray], "tuple[str, float] | None"]


def _sub(board: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    h, w = board.shape[:2]
    x0, x1, y0, y1 = box
    return board[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def parse_score(text: str, score: float) -> int | None:
    text = text.strip().translate(_LOOKALIKE)
    if not re.fullmatch(r"\d{1,2}", text) or score <= 0.4:
        return None
    return int(text)


def left_is_orange(board: np.ndarray) -> bool:
    """Your own team's score is always on the left, so its colour depends on your team."""
    b, _, r = _sub(board, _LEFT_BG).reshape(-1, 3).mean(axis=0)
    return r > b


def read_scores(board: np.ndarray, read_line: ReadLine) -> tuple[int, int] | None:
    """Read (blue, orange) from a scoreboard crop.

    The digits always sit in the same two boxes, so each box goes straight to the
    recogniser; skipping text detection makes this ~20x faster than a full OCR pass.
    """
    scores = []
    for box in (_LEFT_BOX, _RIGHT_BOX):
        crop_ = _sub(board, box)
        if crop_.size == 0:
            return None
        line = read_line(crop_)
        value = parse_score(*line) if line else None
        if value is None:
            return None
        scores.append(value)
    left, right = scores
    return (right, left) if left_is_orange(board) else (left, right)


def parse_clock(text: str, score: float, expected: int | None = None) -> int | None:
    """Seconds shown by the match clock ("4:35" -> 275).

    Overtime counts up ("+1:05") and comes back negative (-65), the same way replay
    clock ticks store it, so it can't be confused with the regular countdown.
    OCR sometimes drops the minute (":55"); it's filled in from ``expected`` (where the
    clock should be by now) when that's known.
    """
    text = text.strip().replace(" ", "").translate(str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "S": "5", "B": "3"}))
    if score < 0.6:
        return None
    overtime = text.startswith("+")
    m = re.fullmatch(r"(\d{1,2})?[:.](\d{2})", text.lstrip("+"))
    if not m or int(m.group(2)) > 59:
        return None
    secs = int(m.group(2))
    sign = -1 if overtime else 1
    if m.group(1) is not None:
        if not overtime and int(m.group(1)) > 9:
            return None
        return sign * (int(m.group(1)) * 60 + secs)
    if expected is None:
        return None
    sign = -1 if overtime or expected < 0 else 1
    return min((sign * (mins * 60 + secs) for mins in range(10)), key=lambda v: abs(v - expected))


def read_clock(board: np.ndarray, read_line: ReadLine, expected: int | None = None) -> int | None:
    line = read_line(_sub(board, _CLOCK_BOX))
    return parse_clock(*line, expected=expected) if line else None


@dataclass
class ScoreTracker:
    """Turns noisy score reads into goals.

    A +1 for one team (or 0-0, a new match) is trusted after two reads in a row.
    Any other jump is most likely a misread ("3" -> "13"), so it only becomes the new
    baseline after many identical reads, and never counts as a goal.
    """

    confirm_reads: int = 2
    resync_reads: int = 5
    confirmed: tuple[int, int] | None = None
    pending: tuple[int, int] | None = None
    pending_time: float = 0.0
    pending_count: int = 0
    goals: list[ScoreGoal] = field(default_factory=list)

    def update(self, t: float, score: tuple[int, int] | None) -> None:
        if score is None:
            return
        if score == self.confirmed:
            self.pending, self.pending_count = None, 0
            return
        if score != self.pending:
            self.pending, self.pending_time, self.pending_count = score, t, 1
        else:
            self.pending_count += 1

        prev = self.confirmed
        delta = None if prev is None else (score[0] - prev[0], score[1] - prev[1])
        plausible = prev is None or score == (0, 0) or delta in ((1, 0), (0, 1))
        if self.pending_count < (self.confirm_reads if plausible else self.resync_reads):
            return
        self.confirmed, self.pending, self.pending_count = score, None, 0
        if delta == (1, 0):
            self.goals.append(ScoreGoal(self.pending_time, "blue", score))
        elif delta == (0, 1):
            self.goals.append(ScoreGoal(self.pending_time, "orange", score))
