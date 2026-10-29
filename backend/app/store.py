"""Projects on disk: data/projects/<id>/project.json plus proxy, thumbs, exports."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from .config import PROJECTS_DIR, ensure_dirs

_lock = threading.RLock()

EVENT_TYPES = ("goal", "save", "epic_save", "goal_other", "manual")


def project_dir(pid: str) -> Path:
    if not pid.isalnum():
        raise KeyError(pid)
    return PROJECTS_DIR / pid


def _file(pid: str) -> Path:
    return project_dir(pid) / "project.json"


def create(source: str, info: dict) -> dict:
    ensure_dirs()
    pid = uuid.uuid4().hex[:10]
    d = project_dir(pid)
    (d / "thumbs").mkdir(parents=True)
    (d / "exports").mkdir()
    project = {
        "id": pid,
        "name": Path(source).stem,
        "source": source,
        "created": time.time(),
        "info": info,
        "analyzed": False,
        "proxy_ready": False,
        "jobs": {},
        "events": [],
        "exports": [],
    }
    save(project)
    return project


def get(pid: str) -> dict:
    with _lock:
        f = _file(pid)
        if not f.exists():
            raise KeyError(pid)
        return json.loads(f.read_text("utf-8"))


def save(project: dict) -> dict:
    with _lock:
        f = _file(project["id"])
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(project, indent=2), "utf-8")
        tmp.replace(f)
        return project


def mutate(pid: str, fn) -> dict:
    """Read-modify-write under the lock."""
    with _lock:
        project = get(pid)
        fn(project)
        return save(project)


def list_all() -> list[dict]:
    ensure_dirs()
    out = []
    for f in PROJECTS_DIR.glob("*/project.json"):
        try:
            p = json.loads(f.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({k: p.get(k) for k in ("id", "name", "source", "created", "analyzed")}
                   | {"event_count": len(p.get("events", [])), "duration": p.get("info", {}).get("duration")})
    return sorted(out, key=lambda p: p["created"] or 0, reverse=True)


def make_event(kind: str, t: float, duration: float, settings: dict, **extra) -> dict:
    start = max(t - float(settings["pre_seconds"]), 0.0)
    end = min(t + float(settings["post_seconds"]), duration) if duration else t + float(settings["post_seconds"])
    return {
        "id": uuid.uuid4().hex[:8],
        "type": kind,
        "time": round(t, 2),
        "start": round(start, 2),
        "end": round(end, 2),
        "selected": kind in ("goal", "epic_save", "save"),
        "confidence": 1.0,
        "source": "manual",
        "team": None,
        "text": "",
        "thumb": None,
        **extra,
    }


_KEPT_EDITS = ("selected", "frame", "style", "crop_x")


def carry_edits(old_events: list[dict], new_events: list[dict], window: float = 1.5) -> None:
    """After a re-analysis: give each new event the edits (tick, trim, framing) of the
    old event for the same play (same type and player, within ``window`` seconds)."""
    used: set[str] = set()
    for e in new_events:
        best = min((o for o in old_events
                    if o["id"] not in used and o["type"] == e["type"] and o.get("player") == e.get("player")
                    and abs(o["time"] - e["time"]) <= window),
                   key=lambda o: abs(o["time"] - e["time"]), default=None)
        if not best:
            continue
        used.add(best["id"])
        shift = e["time"] - best["time"]
        e["start"], e["end"] = round(best["start"] + shift, 2), round(best["end"] + shift, 2)
        e.update({k: best[k] for k in _KEPT_EDITS if k in best})


def clamp_clip(event: dict, start: float, end: float, before: float, after: float,
               duration: float) -> tuple[float, float]:
    """Keep in/out inside [time - before, time + after] and the video."""
    lo = max(event["time"] - before, 0.0)
    hi = event["time"] + after
    if duration:
        hi = min(hi, duration)
    start = min(max(start, lo), hi)
    end = min(max(end, lo), hi)
    if end - start < 0.5:
        end = min(start + 0.5, hi)
        start = min(start, end - 0.5)
    return round(start, 3), round(end, 3)
