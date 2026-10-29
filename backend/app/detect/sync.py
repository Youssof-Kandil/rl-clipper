"""Line replay timelines up with the recording, using the match clock.

A replay's timeline is *not* one continuous copy of real time: after every goal it
skips part of the goal-replay sequence (1-9 s each time), so a single offset drifts
by several seconds over a match. Between goals, though, the clock runs at exactly one
tick per second in both the replay and the video. So the replay's clock is split into
"runs" (kickoff to goal), and each run gets its own offset by reading the clock in
the video.

Each video reading "the clock shows C at video time v" pins the run's offset to a
1-second window: the clock showed C between replay times r(C) and r(C-1). Sampling at
a rate that isn't a whole number (1.1/s) slides the readings across that second, so
together they narrow the offset to a fraction of a second.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Callable

from ..replays import ReplayEvent, ReplayInfo
from .ocr import crop, read_line
from .sampler import sample_frames
from .scoreboard import ScoreGoal, ScoreTracker, read_clock, read_scores

CLOCK_FPS = 1.1
# Readings a run needs before its offset is trusted.
_MIN_READINGS = 3
# Video goal and replay goal times of a correct pairing agree to within this (seconds).
_CLUSTER = 3.0
# How far a goal-based offset may drift from the start-time estimate.
_MAX_DRIFT = 180.0
# How much video around a match's estimated position gets its clock read.
_WINDOW_PAD = 90.0
# Within a match the offset only grows (the replay skips part of each goal replay, a
# few seconds each time), so each run must land this close after the previous one.
# Without it, a run's clock (say 0:32 -> 0:00) can lock onto the same clock values
# at the end of the previous match, which is also inside the reading window.
_RUN_BACK = 1.5
_RUN_AHEAD = 20.0
# The first run must be this close to the match's start-time estimate.
_FIRST_RUN_SLACK = 75.0

Progress = Callable[[float, str], None]


@dataclass
class Run:
    """A stretch where the clock ticks down without stopping (kickoff to goal)."""

    ticks: list[tuple[float, int]]  # (replay time, seconds left), one per second
    offset: float | None = None
    readings: int = 0

    @property
    def start(self) -> float:
        return self.ticks[0][0]

    @property
    def end(self) -> float:
        return self.ticks[-1][0]


@dataclass
class MatchSync:
    replay: ReplayInfo
    source: str  # "clock" | "goals" | "start time" | "none"
    runs: list[Run] = field(default_factory=list)
    offset: float | None = None  # single offset when not clock-synced
    anchors: int = 0  # clock readings or goals the sync rests on

    def to_video(self, t: float) -> float | None:
        """Video time of replay time ``t``."""
        synced = [r for r in self.runs if r.offset is not None]
        if not synced:
            return None if self.offset is None else t + self.offset
        # A run's offset holds from its first tick until the clock stops (the goal
        # comes a fraction of a second after the last tick) and through the frozen
        # stretch before the next kickoff; before the first run, the first run's.
        run = synced[0]
        for r in synced:
            if r.start - 1.5 <= t:
                run = r
        return t + run.offset

    @property
    def span(self) -> tuple[float, float] | None:
        a, b = self.to_video(0.0), self.to_video(self.replay.duration)
        return None if a is None or b is None else (a, b)

    def to_dict(self) -> dict:
        offsets = [r.offset for r in self.runs if r.offset is not None]
        return {"replay": self.replay.to_dict(), "source": self.source, "anchors": self.anchors,
                "offset": offsets[0] if offsets else self.offset, "span": self.span,
                "runs": [{"start": r.start, "end": r.end, "offset": r.offset, "readings": r.readings}
                         for r in self.runs]}


# ---------------------------------------------------------------- clock runs

def clock_runs(ticks: list[tuple[float, int]]) -> list[Run]:
    runs: list[Run] = []
    current: list[tuple[float, int]] = []
    for t, value in ticks:
        if current and value == current[-1][1] - 1 and 0.5 < t - current[-1][0] < 1.6:
            current.append((t, value))
            continue
        if len(current) >= 2:
            runs.append(Run(current))
        current = [(t, value)]
    if len(current) >= 2:
        runs.append(Run(current))
    return runs


def solve_run(run: Run, samples: list[tuple[float, int]], bounds: tuple[float, float] | None = None) -> None:
    """Set ``run.offset`` from video clock readings ``(video time, seconds left)``.

    Each reading of a value the run ticks through gives an interval of possible
    offsets; the answer is where the most intervals overlap (so a misread or a reading
    from a neighbouring match can't drag it), narrowed to their common part.
    ``bounds`` limits the offsets considered.
    """
    shown = {value: (t, run.ticks[i + 1][0]) for i, (t, value) in enumerate(run.ticks[:-1])}
    intervals = [(v - shown[c][1], v - shown[c][0]) for v, c in samples if c in shown]
    if bounds:
        lo_b, hi_b = bounds
        intervals = [(max(a, lo_b), min(b, hi_b)) for a, b in intervals if b > lo_b and a < hi_b]
    if len(intervals) < _MIN_READINGS:
        return
    best_point, best = None, []
    for lo, hi in intervals:
        for point in (lo + 1e-6, hi):
            covering = [iv for iv in intervals if iv[0] < point <= iv[1]]
            if len(covering) > len(best):
                best_point, best = point, covering
    if best_point is None or len(best) < _MIN_READINGS:
        return
    lo = max(iv[0] for iv in best)
    hi = min(iv[1] for iv in best)
    run.offset = round((lo + hi) / 2, 3)
    run.readings = len(best)


def solve_runs(runs: list[Run], samples: list[tuple[float, int]], rough: float | None) -> None:
    """Solve a match's runs in order, each one only a little after the previous one."""
    prev: float | None = None
    since = 0  # runs since the last solved one (each can add its own skip)
    for run in runs:
        since += 1
        if prev is not None:
            bounds = (prev - _RUN_BACK, prev + _RUN_AHEAD * since)
        elif rough is not None:
            bounds = (rough - _FIRST_RUN_SLACK, rough + _FIRST_RUN_SLACK)
        else:
            bounds = None
        solve_run(run, samples, bounds)
        if run.offset is not None:
            prev, since = run.offset, 0


def fill_gaps(runs: list[Run]) -> None:
    """Runs the video never showed clearly borrow a neighbour's offset.

    The replay only ever *skips* time (offsets grow after each goal), so the previous
    run's offset is the better guess; the next one is used before the first solved run.
    """
    solved = [r.offset for r in runs]
    for i, r in enumerate(runs):
        if r.offset is None:
            before = next((o for o in reversed(solved[:i]) if o is not None), None)
            after = next((o for o in solved[i + 1:] if o is not None), None)
            r.offset = before if before is not None else after


def clock_samples(src: str, info: dict, settings: dict, windows: list[tuple[float, float]],
                  progress: Progress | None = None,
                  cancelled: Callable[[], bool] = lambda: False) -> list[tuple[float, int]]:
    """Read the match clock 1.1 times a second inside ``windows`` of the video."""
    out: list[tuple[float, int]] = []
    total = sum(b - a for a, b in windows) or 1.0
    done = 0.0
    for a, b in windows:
        last: tuple[float, int] | None = None
        for i, (t, frame) in enumerate(sample_frames(src, info["width"], info["height"], CLOCK_FPS,
                                                     int(settings["analysis_width"]), start=a, end=b)):
            if cancelled():
                raise InterruptedError("Analysis cancelled")
            expected = round(last[1] - (t - last[0])) if last and t - last[0] < 10 else None
            value = read_clock(crop(frame, settings["scoreboard_roi"]), read_line, expected)
            if value is not None:
                out.append((t, value))
                last = (t, value)
            if progress and i % 30 == 0:
                progress(min((done + t - a) / total, 0.99), "Reading the match clock")
        done += b - a
    return out


def merge_windows(windows: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for a, b in sorted((max(a, 0.0), min(b, duration)) for a, b in windows):
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


# ---------------------------------------------------------------- goal fallback

def scoreboard_goals(src: str, info: dict, settings: dict, progress: Progress | None = None,
                     cancelled: Callable[[], bool] = lambda: False) -> list[ScoreGoal]:
    """One cheap pass over the video reading only the score boxes, once a second."""
    tracker = ScoreTracker()
    duration = info["duration"] or 1.0
    for i, (t, frame) in enumerate(sample_frames(src, info["width"], info["height"], 1.0,
                                                 int(settings["analysis_width"]))):
        if cancelled():
            raise InterruptedError("Analysis cancelled")
        tracker.update(t, read_scores(crop(frame, settings["scoreboard_roi"]), read_line))
        if progress and i % 30 == 0:
            progress(min(t / duration, 0.99), f"Reading the scoreboard · {len(tracker.goals)} goals")
    return tracker.goals


def solve_offset(replay_goals: list[ReplayEvent], video_goals: list[ScoreGoal],
                 rough: float | None) -> tuple[float | None, int]:
    """Offset that lines up the most replay goals with video goals (same team and score)."""
    candidates = [v.time - g.time for g in replay_goals for v in video_goals
                  if v.team == g.team and v.score == g.score
                  and (rough is None or abs(v.time - g.time - rough) <= _MAX_DRIFT)]
    if not candidates:
        return None, 0
    best: list[float] = []
    for c in candidates:
        cluster = [x for x in candidates if abs(x - c) <= _CLUSTER]
        if len(cluster) > len(best):
            best = cluster
    return statistics.median(best), len(best)


# ---------------------------------------------------------------- putting it together

def rough_offset(info: ReplayInfo, rec_start: float | None) -> float | None:
    return info.start_epoch - rec_start if rec_start is not None and info.start_epoch else None


def sync_matches(found: list[tuple[ReplayInfo, list[ReplayEvent], list[tuple[float, int]]]],
                 rec_start: float | None, duration: float,
                 read_samples: Callable[[list[tuple[float, float]]], list[tuple[float, int]]],
                 read_goals: Callable[[], list[ScoreGoal]]) -> list[MatchSync]:
    """Clock sync where the match's rough position is known, goals otherwise."""
    windows = []
    for info, _, _ in found:
        rough = rough_offset(info, rec_start)
        if rough is not None and -info.duration < rough < duration:
            windows.append((rough - _WINDOW_PAD, rough + info.duration + _WINDOW_PAD))
    samples = read_samples(merge_windows(windows, duration)) if windows else []

    out: list[MatchSync] = []
    goals: list[ScoreGoal] | None = None
    for info, events, ticks in found:
        rough = rough_offset(info, rec_start)
        runs = clock_runs(ticks)
        if rough is not None and runs:
            lo, hi = rough - _WINDOW_PAD, rough + info.duration + _WINDOW_PAD
            near = [(v, c) for v, c in samples if lo <= v <= hi]
            solve_runs(runs, near, rough)
            readings = sum(r.readings for r in runs)
            if readings:
                fill_gaps(runs)
                out.append(MatchSync(info, "clock", runs, anchors=readings))
                continue
        # No clock lock: line up goals instead (one offset for the whole match).
        if goals is None:
            goals = read_goals()
        offset, anchors = solve_offset([e for e in events if e.kind == "goal"], goals, rough)
        if offset is not None:
            out.append(MatchSync(info, "goals", offset=offset, anchors=anchors))
        elif rough is not None and -info.duration < rough < duration:
            out.append(MatchSync(info, "start time", offset=rough))
        else:
            out.append(MatchSync(info, "none"))
    return out


def uncovered(spans: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """Parts of [0, duration] no synced match covers (these still get the on-screen scan)."""
    gaps, pos = [], 0.0
    for a, b in sorted(spans):
        if a > pos + 1.0:
            gaps.append((pos, min(a, duration)))
        pos = max(pos, b)
    if pos < duration - 1.0:
        gaps.append((pos, duration))
    return [(a, b) for a, b in gaps if b - a > 1.0]
