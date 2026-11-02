"""YouTube and TikTok timelines: an ordered list of clips, each with its own trim.

An item points at a detected event and keeps its own in/out (inside the event's
window), and for TikTok its own 9:16 style and crop position. Items also carry effect
and sound markers, timed in source seconds like the trim so trimming never moves them.
"""

from __future__ import annotations

import uuid

from . import media, sounds, store

KINDS = ("youtube", "tiktok")
EFFECTS = media.EFFECTS
MAX_MARKERS = 20


def empty(kind: str) -> dict:
    return {"items": [], "captions": kind == "tiktok"}


def get(project: dict, kind: str) -> dict:
    return (project.get("sequences") or {}).get(kind) or empty(kind)


def make_item(event: dict) -> dict:
    return {"id": uuid.uuid4().hex[:8], "event_id": event["id"], "start": event["start"],
            "end": event["end"], "crop_x": event.get("crop_x", 0.5), "style": event.get("style"),
            "effects": [], "sounds": []}


def _num(value: object, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        v = default
    return round(min(max(v, lo), hi), 3)


def _markers(raw: dict, lo: float, hi: float) -> tuple[list[dict], list[dict]]:
    effects = [{"id": str(m.get("id") or uuid.uuid4().hex[:8]), "t": _num(m.get("t"), lo, lo, hi),
                "type": m["type"], "strength": _num(m.get("strength"), 0.7, 0.2, 1.0)}
               for m in raw.get("effects") or [] if isinstance(m, dict) and m.get("type") in EFFECTS]
    found = [{"id": str(m.get("id") or uuid.uuid4().hex[:8]), "t": _num(m.get("t"), lo, lo, hi),
              "sound": m["sound"], "volume": _num(m.get("volume"), 1.0, 0.0, 2.0)}
             for m in raw.get("sounds") or [] if isinstance(m, dict) and sounds.path(str(m.get("sound") or ""))]
    return effects[:MAX_MARKERS], found[:MAX_MARKERS]


def clean(project: dict, seq: dict, settings: dict) -> dict:
    """Validate a sequence sent by the UI: known events only, trims inside each event's
    window, sane crop and style."""
    events = {e["id"]: e for e in project["events"]}
    before, after = float(settings["pre_seconds"]), float(settings["post_seconds"])
    items = []
    for raw in seq.get("items", []):
        e = events.get(raw.get("event_id"))
        if not e:
            continue
        start, end = store.clamp_clip(e, float(raw.get("start", e["start"])), float(raw.get("end", e["end"])),
                                      before, after, project["info"]["duration"])
        style = raw.get("style")
        lo = max(e["time"] - before, 0.0)
        hi = min(e["time"] + after, project["info"]["duration"] or e["time"] + after)
        effects, found = _markers(raw, lo, hi)
        items.append({
            "id": str(raw.get("id") or uuid.uuid4().hex[:8]), "event_id": e["id"], "start": start, "end": end,
            "crop_x": round(min(max(float(raw.get("crop_x", 0.5)), 0.0), 1.0), 4),
            "style": style if style in media.VERTICAL_STYLES else None,
            "effects": effects, "sounds": found,
        })
    out = {"items": items, "captions": bool(seq.get("captions", False))}
    name = media.file_name(str(seq.get("name") or ""))
    if name:
        out["name"] = name  # the compiled export's file name
    return out


def prune(project: dict, old_events: list[dict] | None = None) -> None:
    """After events change: re-point items at the matching new event (same type, within
    1.5 s; a re-analysis gives every event a new id) and drop items whose event is gone."""
    by_id = {e["id"]: e for e in project["events"]}
    old = {e["id"]: e for e in old_events or []}
    for seq in (project.get("sequences") or {}).values():
        kept = []
        for item in seq.get("items", []):
            if item["event_id"] not in by_id and item["event_id"] in old:
                was = old[item["event_id"]]
                match = min((e for e in project["events"]
                             if e["type"] == was["type"] and abs(e["time"] - was["time"]) <= 1.5),
                            key=lambda e: abs(e["time"] - was["time"]), default=None)
                if match:
                    item["event_id"] = match["id"]
            if item["event_id"] in by_id:
                kept.append(item)
        seq["items"] = kept
