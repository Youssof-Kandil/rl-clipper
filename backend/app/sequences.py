"""YouTube and TikTok timelines: an ordered list of clips, each with its own trim.

An item points at a detected event and keeps its own in/out (inside the event's
window), and for TikTok its own 9:16 style and crop position.
"""

from __future__ import annotations

import uuid

from . import media, store

KINDS = ("youtube", "tiktok")


def empty(kind: str) -> dict:
    return {"items": [], "captions": kind == "tiktok"}


def get(project: dict, kind: str) -> dict:
    return (project.get("sequences") or {}).get(kind) or empty(kind)


def make_item(event: dict) -> dict:
    return {"id": uuid.uuid4().hex[:8], "event_id": event["id"], "start": event["start"],
            "end": event["end"], "crop_x": event.get("crop_x", 0.5), "style": event.get("style")}


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
        items.append({
            "id": str(raw.get("id") or uuid.uuid4().hex[:8]), "event_id": e["id"], "start": start, "end": end,
            "crop_x": round(min(max(float(raw.get("crop_x", 0.5)), 0.0), 1.0), 4),
            "style": style if style in media.VERTICAL_STYLES else None,
        })
    return {"items": items, "captions": bool(seq.get("captions", False))}


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
