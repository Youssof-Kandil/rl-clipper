"""Turn raw per-frame hits into a clean, de-duplicated event list."""

from __future__ import annotations

from dataclasses import dataclass, field

from .scoreboard import ScoreGoal

# Higher wins when two types collide on the same tag (e.g. a frame read as "SAVE"
# while the full tag is "EPIC SAVE").
_RANK = {"epic_save": 3, "goal": 2, "save": 1}


@dataclass
class Hit:
    time: float
    type: str
    confidence: float
    text: str = ""
    frame: object = None  # numpy frame kept for the thumbnail


@dataclass
class Event:
    time: float
    type: str  # goal | save | epic_save | goal_other
    confidence: float
    source: str  # tag | scoreboard | tag+scoreboard | manual
    team: str | None = None
    text: str = ""
    hits: int = 1
    frame: object = field(default=None, repr=False)


def merge_hits(hits: list[Hit], window: float) -> list[Event]:
    """Cluster hits that are within `window` seconds of the previous hit.

    A cluster becomes one event at its first appearance, typed by the strongest
    type seen (weighted by how often each type was read).
    """
    events: list[Event] = []
    cluster: list[Hit] = []

    def flush() -> None:
        if not cluster:
            return
        votes: dict[str, float] = {}
        for h in cluster:
            votes[h.type] = votes.get(h.type, 0.0) + h.confidence
        # An epic-save read anywhere in the cluster beats plain-save reads.
        best = max(votes, key=lambda k: (k == "epic_save" and "save" in votes, votes[k], _RANK[k]))
        first = next(h for h in cluster if h.type == best)
        conf = max(h.confidence for h in cluster if h.type == best)
        # Several consistent reads make us more sure.
        conf = min(conf + 0.02 * (len(cluster) - 1), 0.99)
        events.append(Event(first.time, best, round(conf, 2), "tag", text=first.text,
                            hits=len(cluster), frame=first.frame))
        cluster.clear()

    for h in sorted(hits, key=lambda h: h.time):
        if cluster and h.time - cluster[-1].time > window:
            flush()
        # Same tag position but a different family (goal vs save) means a new event.
        if cluster and _family(h.type) != _family(cluster[-1].type):
            flush()
        cluster.append(h)
    flush()
    return events


def _family(kind: str) -> str:
    return "save" if kind in ("save", "epic_save") else kind


def attach_scoreboard(events: list[Event], goals: list[ScoreGoal], window: float,
                      frames: dict[float, object] | None = None) -> list[Event]:
    """Merge scoreboard goals into GOAL tags; unmatched ones become goal_other."""
    out = list(events)
    tag_goals = [e for e in out if e.type == "goal"]
    for g in goals:
        match = min(tag_goals, key=lambda e: abs(e.time - g.time), default=None)
        if match is not None and abs(match.time - g.time) <= window and match.team is None:
            match.team = g.team
            match.source = "tag+scoreboard"
            match.confidence = max(match.confidence, 0.97)
            continue
        out.append(Event(g.time, "goal_other", 0.8, "scoreboard", team=g.team,
                         text=f"{g.score[0]}-{g.score[1]}",
                         frame=(frames or {}).get(g.time)))
    out.sort(key=lambda e: e.time)
    return out
