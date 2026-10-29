"""Run the full detection pass over a recording."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2

from .events import Event, Hit, attach_scoreboard, merge_hits
from .ocr import crop, read_line, read_text
from .sampler import sample_frames
from .scoreboard import ScoreTracker, read_scores
from .tags import classify, white_ratio

ProgressCb = Callable[[float, str], None]


def analyze(src: str, info: dict, settings: dict, progress: ProgressCb | None = None,
            cancelled: Callable[[], bool] = lambda: False, debug_dir: Path | None = None,
            ranges: list[tuple[float, float]] | None = None) -> list[Event]:
    """Scan the video (or only ``ranges`` of it) for point tags and score changes."""
    fps = float(settings["sample_fps"])
    duration = info["duration"] or 1.0
    ranges = ranges if ranges is not None else [(0.0, duration)]
    total = max(int(sum(b - a for a, b in ranges) * fps), 1)
    score_every = max(int(round(float(settings["scoreboard_interval"]) * fps)), 1)
    use_scoreboard = bool(settings["use_scoreboard"])
    min_white = float(settings["tag_white_ratio"])
    tag_lead = float(settings["tag_lead"])

    hits: list[Hit] = []
    score_goals: list = []
    score_frames: dict[float, object] = {}
    ocr_calls = 0

    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)

    tracker = ScoreTracker()
    for i, (t, frame, new_range) in enumerate(_frames(src, info, settings, fps, ranges)):
        if cancelled():
            raise InterruptedError("Analysis cancelled")
        if new_range:
            # The score jumps across skipped stretches; start tracking afresh.
            score_goals.extend(tracker.goals)
            tracker = ScoreTracker()

        tag_img = crop(frame, settings["tag_roi"])
        if white_ratio(tag_img) >= min_white:
            ocr_calls += 1
            texts = [b.text for b in read_text(tag_img) if b.score > 0.5]
            found = classify(texts) if texts else None
            if found:
                kind, conf = found
                hits.append(Hit(max(t - tag_lead, 0.0), kind, conf, " ".join(texts), frame.copy()))
            if debug_dir and texts:
                cv2.imwrite(str(debug_dir / f"tag_{t:08.1f}_{'_'.join(texts)[:40]}.jpg"), tag_img)

        if use_scoreboard and i % score_every == 0:
            ocr_calls += 1
            before = len(tracker.goals)
            tracker.update(t, read_scores(crop(frame, settings["scoreboard_roi"]), read_line))
            if len(tracker.goals) > before:
                score_frames[tracker.goals[-1].time] = frame.copy()

        if progress and i % 20 == 0:
            progress(min(i / total, 0.99), f"{_clock(t)} / {_clock(duration)} · {len(hits)} tag reads")
    score_goals.extend(tracker.goals)

    events = merge_hits(hits, float(settings["merge_window"]))
    if use_scoreboard:
        events = attach_scoreboard(events, score_goals, float(settings["goal_merge_window"]), score_frames)
    if progress:
        progress(1.0, f"Found {len(events)} events ({ocr_calls} OCR passes)")
    return events


def _frames(src: str, info: dict, settings: dict, fps: float, ranges: list[tuple[float, float]]):
    """Frames from each range in turn, flagging the first frame of every range."""
    for start, end in ranges:
        for j, (t, frame) in enumerate(sample_frames(src, info["width"], info["height"], fps,
                                                     int(settings["analysis_width"]), start=start, end=end)):
            yield t, frame, j == 0


def _clock(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"
