"""FastAPI app: REST API + the built frontend."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import captions, jobs, media, picker, replays, sequences, store
from .config import DATA_DIR, FRONTEND_DIST, UPLOADS_DIR, ensure_dirs, load_settings, save_settings
from .detect.events import Event

app = FastAPI(title="RL Clipper")
ensure_dirs()


# ---------- helpers ----------

def _project(pid: str) -> dict:
    try:
        return store.get(pid)
    except KeyError:
        raise HTTPException(404, "Project not found") from None


def _with_jobs(project: dict) -> dict:
    details = {}
    for kind, job_id in project.get("jobs", {}).items():
        job = jobs.get(job_id)
        if job:
            details[kind] = job.to_dict()
    return project | {"job_status": details}


def _find_event(project: dict, eid: str) -> dict:
    for e in project["events"]:
        if e["id"] == eid:
            return e
    raise HTTPException(404, "Event not found")


def _save_thumb(pid: str, frame: object, name: str) -> str | None:
    if frame is None:
        return None
    img = np.asarray(frame)
    h, w = img.shape[:2]
    thumb = cv2.resize(img, (320, max(int(h * 320 / w), 1)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(store.project_dir(pid) / "thumbs" / name), thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return name


# ---------- jobs ----------

def start_proxy(pid: str) -> jobs.Job:
    project = _project(pid)
    settings = load_settings()

    def work(job: jobs.Job) -> dict:
        out = store.project_dir(pid) / "proxy.mp4"
        job.update(0, "Rendering preview video")
        media.render_proxy(project["source"], str(out), project["info"], settings["game_track"],
                           settings["mic_track"], lambda p: job.update(p, f"Preview {p * 100:.0f}%"))
        store.mutate(pid, lambda p: p.update(proxy_ready=True))
        return {}

    job = jobs.submit("proxy", pid, work)
    store.mutate(pid, lambda p: p["jobs"].update(proxy=job.id))
    return job


def start_analysis(pid: str) -> jobs.Job:
    from .detect import sync  # heavy imports (OCR) only when needed
    from .detect.pipeline import analyze

    project = _project(pid)
    settings = load_settings()
    src, info = project["source"], project["info"]
    duration = info["duration"]
    ignored = set(project.get("ignored_replays", []))

    def work(job: jobs.Job) -> dict:
        report = lambda lo, hi: (lambda p, m: job.update(lo + (hi - lo) * p, m))  # noqa: E731
        new_events: list[dict] = []
        matches: list[sync.MatchSync] = []

        # 1. Replays first: exact, every player's plays.
        found = []
        if settings["use_replays"]:
            job.update(0, "Looking for Rocket League replays")
            exe = replays.rrrocket_path(settings)
            for r in replays.find_for_recording(settings, src, duration):
                if r.id not in ignored:
                    found.append((r, *replays.read_replay(exe, r)))
        if found:
            cancelled = lambda: job.cancelled  # noqa: E731
            matches = sync.sync_matches(
                found, replays.recording_start(src), duration,
                read_samples=lambda windows: sync.clock_samples(src, info, settings, windows,
                                                                report(0.02, 0.45), cancelled),
                read_goals=lambda: sync.scoreboard_goals(src, info, settings, report(0.45, 0.5), cancelled))
            me = _my_name(settings, [r for r, _, _ in found])
            events_by_replay = {r.id: ev for r, ev, _ in found}
            for m in matches:
                for e in events_by_replay[m.replay.id]:
                    t = m.to_video(e.time)
                    if t is not None and 0 <= t <= duration:
                        mine = bool(me) and e.player == me
                        new_events.append(store.make_event(
                            e.kind, t, duration, settings, source="replay", team=e.team, player=e.player,
                            mine=mine, selected=mine, text=e.player))

        # 2. The on-screen scan for whatever no replay covers.
        spans = [m.span for m in matches if m.span]
        ranges = sync.uncovered(spans, duration) if spans else None
        if ranges is None or ranges:
            job.update(0.5 if found else 0, "Loading OCR model")
            scanned: list[Event] = analyze(src, info, settings, report(0.5 if found else 0, 0.95),
                                           lambda: job.cancelled, ranges=ranges)
            for e in scanned:
                ev = store.make_event(e.type, e.time, duration, settings, confidence=e.confidence,
                                      source=e.source, team=e.team, text=e.text, mine=e.type != "goal_other")
                ev["thumb"] = _save_thumb(pid, e.frame, f"{ev['id']}.jpg")
                new_events.append(ev)

        job.update(0.96, "Making thumbnails")
        for ev in new_events:
            if ev.get("thumb") is None:
                ev["thumb"] = _grab_thumb(pid, src, ev["time"], f"{ev['id']}.jpg")

        def apply(p: dict) -> None:
            manual = [e for e in p["events"] if e["source"] == "manual"]
            old_events = p["events"]
            store.carry_edits([e for e in old_events if e["source"] != "manual"], new_events)
            p["events"] = sorted(manual + new_events, key=lambda e: e["time"])
            sequences.prune(p, old_events)
            p["matches"] = [m.to_dict() for m in matches]
            p["analyzed"] = True

        store.mutate(pid, apply)
        return {"events": len(new_events), "matches": len(matches)}

    job = jobs.submit("analysis", pid, work)
    store.mutate(pid, lambda p: p["jobs"].update(analysis=job.id))
    return job


def _my_name(settings: dict, found: list[replays.ReplayInfo]) -> str:
    """Your in-game name: the setting, else the replay owner, else whoever is in every match."""
    if settings.get("my_player_name"):
        return settings["my_player_name"]
    owners = [r.owner for r in found if r.owner]
    if owners:
        return max(set(owners), key=owners.count)
    common = set.intersection(*({pl["name"] for pl in r.players} for r in found)) if found else set()
    return next(iter(common)) if len(common) == 1 else ""


def _grab_thumb(pid: str, src: str, t: float, name: str) -> str | None:
    try:
        (store.project_dir(pid) / "thumbs" / name).write_bytes(media.grab_frame(src, t, 320))
        return name
    except media.MediaError:
        return None


def _vertical(info: dict, settings: dict, style: str | None, crop_x: float) -> dict:
    """9:16 export options; ``style`` None = the default from Settings."""
    style = style or settings["vertical_style"]
    if style not in media.VERTICAL_STYLES:
        style = "focus45"
    sharp = round(float(settings["vertical_sharp"]), 2)
    return {"info": info, "style": style, "center_x": float(crop_x),
            "zoom": float(settings["vertical_zoom"]), "blur": float(settings["vertical_blur"]),
            "mask": media.focus_mask(DATA_DIR / "masks" / f"focus_{sharp}.png", sharp)}


def _frame_for(e: dict, info: dict, settings: dict) -> dict | None:
    """9:16 export options for a clip (its own choice, else the default), or None for 16:9."""
    if (e.get("frame") or settings["frame"]) != "9:16":
        return None
    return _vertical(info, settings, e.get("style"), e.get("crop_x", 0.5))


def _unique(path: Path) -> Path:
    n, target = 2, path
    while target.exists():
        target = path.with_name(f"{path.stem}_{n}{path.suffix}")
        n += 1
    return target


def start_sequence_export(pid: str, kind: str, mode: str) -> jobs.Job:
    """Render a YouTube (16:9) or TikTok (9:16) timeline, as one video or one file per item."""
    project = _project(pid)
    settings = load_settings()
    seq = sequences.get(project, kind)
    events = {e["id"]: e for e in project["events"]}
    items = [i for i in seq["items"] if i["event_id"] in events]
    if not items:
        raise HTTPException(400, "The timeline is empty")
    out_dir = Path(settings["export_dir"]) if settings["export_dir"] else store.project_dir(pid) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    vertical = kind == "tiktok"
    size = media.VERTICAL_SIZE if vertical else (project["info"]["width"], project["info"]["height"])
    cues = project.get("captions", []) if seq.get("captions") else []
    stem = media.safe_name(Path(project["source"]).stem)

    def work(job: jobs.Job) -> dict:
        work_dir = store.project_dir(pid) / "render" / job.id
        work_dir.mkdir(parents=True, exist_ok=True)
        total = sum(i["end"] - i["start"] for i in items) or 1.0
        done_secs = 0.0
        parts: list[Path] = []
        files: list[dict] = []
        try:
            for n, item in enumerate(items, 1):
                if job.cancelled:
                    raise InterruptedError("Cancelled")
                e = events[item["event_id"]]
                frame = _vertical(project["info"], settings, item.get("style"), item.get("crop_x", 0.5)) \
                    if vertical else None
                subs = None
                if cues:
                    subs = captions.write_ass(work_dir / f"cap_{n}.ass", cues, item["start"], item["end"], size,
                                              int(settings["caption_size"]), settings["caption_position"],
                                              bool(settings["caption_upper"]), bool(settings["caption_highlight"]),
                                              str(settings["caption_color"]))
                if mode == "compiled":
                    target = work_dir / f"part_{n:03d}.mp4"
                else:
                    name = f"{stem}_{kind}_{n:02d}_{e['type']}_{media.mmss(e['time'])}.mp4"
                    target = _unique(out_dir / name)
                length = item["end"] - item["start"]
                media.export_clip(project["source"], str(target), item["start"], item["end"], project["info"],
                                  settings["game_track"], settings["mic_track"], settings["encoder"],
                                  lambda p: job.update((done_secs + p * length) / total * 0.97,
                                                       f"Rendering clip {n}/{len(items)}"),
                                  frame, subs, settings["export_quality"])
                done_secs += length
                if mode == "compiled":
                    parts.append(target)
                else:
                    files.append({"path": str(target), "name": target.name})
            if mode == "compiled":
                job.update(0.97, "Joining clips")
                target = _unique(out_dir / f"{stem}_{kind}_compiled.mp4")
                media.concat(parts, str(target), project["info"]["audio_streams"])
                files.append({"path": str(target), "name": target.name})
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        store.mutate(pid, lambda p: p.update(exports=(p.get("exports", []) + files)[-200:]))
        return {"files": files, "folder": str(out_dir)}

    job = jobs.submit(f"export_{kind}", pid, work)
    store.mutate(pid, lambda p: p["jobs"].update({f"export_{kind}": job.id}))
    return job


def start_transcribe(pid: str, item_ids: list[str] | None) -> jobs.Job:
    project = _project(pid)
    settings = load_settings()
    model = str(settings["caption_model"])
    if not captions.model_ready(model):
        raise HTTPException(400, "The caption model isn't downloaded yet")
    if project["info"]["audio_streams"] == 0:
        raise HTTPException(400, "This recording has no audio")
    items = sequences.get(project, "tiktok")["items"]
    if item_ids:
        items = [i for i in items if i["id"] in item_ids]
    if not items:
        raise HTTPException(400, "No clips to transcribe")
    ranges = [(i["start"], i["end"]) for i in items]
    track = min(int(settings["mic_track"]), project["info"]["audio_streams"] - 1)

    def work(job: jobs.Job) -> dict:
        cues = captions.transcribe(project["source"], ranges, track, model, job.update, lambda: job.cancelled,
                                   max(int(settings["caption_max_words"]), 1))
        out: dict = {}

        def apply(p: dict) -> None:
            p["captions"] = captions.merge(p.get("captions", []), cues, ranges)
            out["count"] = len(cues)

        store.mutate(pid, apply)
        return out | {"device": captions.device_in_use()}

    job = jobs.submit("transcribe", pid, work)
    store.mutate(pid, lambda p: p["jobs"].update(transcribe=job.id))
    return job


def start_export(pid: str, ids: list[str] | None) -> jobs.Job:
    project = _project(pid)
    settings = load_settings()
    events = [e for e in project["events"] if (e["id"] in ids if ids else e["selected"])]
    if not events:
        raise HTTPException(400, "No clips selected")
    out_dir = Path(settings["export_dir"]) if settings["export_dir"] else store.project_dir(pid) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)

    def work(job: jobs.Job) -> dict:
        progress = {e["id"]: 0.0 for e in events}
        lock = threading.Lock()
        files: list[dict] = []

        def one(e: dict) -> None:
            if job.cancelled:
                return
            frame = _frame_for(e, project["info"], settings)
            name = media.clip_filename(project["source"], e["type"], e["time"], vertical=frame is not None)
            target = out_dir / name
            n = 2
            while target.exists():
                target = out_dir / f"{Path(name).stem}_{n}.mp4"
                n += 1

            def cb(p: float) -> None:
                with lock:
                    progress[e["id"]] = p
                    done = sum(1 for v in progress.values() if v >= 1)
                    job.update(sum(progress.values()) / len(progress), f"Exported {done}/{len(progress)}")
                    job.result = {"clips": progress}

            media.export_clip(project["source"], str(target), e["start"], e["end"], project["info"],
                              settings["game_track"], settings["mic_track"], settings["encoder"], cb, frame,
                              quality=settings["export_quality"])
            with lock:
                files.append({"event_id": e["id"], "path": str(target), "name": target.name})

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(one, events))

        store.mutate(pid, lambda p: p.update(exports=(p.get("exports", []) + files)[-200:]))
        return {"clips": progress, "files": files, "folder": str(out_dir)}

    job = jobs.submit("export", pid, work)
    store.mutate(pid, lambda p: p["jobs"].update(export=job.id))
    return job


def _open_project(source: str) -> dict:
    try:
        info = media.probe(source)
    except media.MediaError as exc:
        raise HTTPException(400, str(exc)) from None
    project = store.create(source, info)
    start_proxy(project["id"])
    start_analysis(project["id"])
    return _with_jobs(store.get(project["id"]))


# ---------- API ----------

class PathIn(BaseModel):
    path: str


class EventPatch(BaseModel):
    start: float | None = None
    end: float | None = None
    selected: bool | None = None
    type: str | None = None
    # Per-clip framing; "" clears frame/style back to the default.
    frame: str | None = None
    style: str | None = None
    crop_x: float | None = None


class EventIn(BaseModel):
    time: float
    type: str = "manual"


class SelectIn(BaseModel):
    ids: list[str]
    selected: bool


class ExportIn(BaseModel):
    ids: list[str] | None = None


class SequenceIn(BaseModel):
    items: list[dict]
    captions: bool = False


class SequenceExportIn(BaseModel):
    mode: str = "compiled"  # compiled | separate


class TranscribeIn(BaseModel):
    item_ids: list[str] | None = None


class CaptionsIn(BaseModel):
    captions: list[dict]


@app.get("/api/health")
def health() -> dict:
    """What this machine can do. Only ffmpeg is required; everything else has a fallback."""
    settings = load_settings()
    try:
        ffmpeg = media.tool("ffmpeg")
        media.tool("ffprobe")
        error = ""
    except media.MediaError as exc:
        ffmpeg, error = None, str(exc)
    gpu_captions, gpu_reason = captions.gpu_status()
    exe, folder = replays.rrrocket_path(settings), replays.demos_dir(settings)
    return {
        "ok": ffmpeg is not None,
        "error": error,
        "platform": sys.platform,
        "ffmpeg": ffmpeg,
        "nvenc": bool(ffmpeg) and media.nvenc_available(),
        "captions_gpu": gpu_captions,
        "captions_gpu_reason": gpu_reason,
        "caption_model_ready": captions.model_ready(str(settings["caption_model"])),
        "rrrocket": str(exe) if exe else None,
        "rrrocket_downloadable": replays.rrrocket_url() is not None,
        "demos_dir": str(folder) if folder else None,
        "picker": picker.available(),
    }


@app.get("/api/settings")
def get_settings() -> dict:
    return load_settings()


@app.put("/api/settings")
def put_settings(update: dict) -> dict:
    return save_settings(update)


@app.get("/api/projects")
def list_projects() -> list[dict]:
    return store.list_all()


@app.post("/api/projects")
def create_project(body: PathIn) -> dict:
    path = body.path.strip().strip('"')
    if not os.path.isfile(path):
        raise HTTPException(400, f"File not found: {path}")
    return _open_project(os.path.abspath(path))


@app.post("/api/pick-file")
def pick_file() -> dict:
    """Open the native file dialog on this machine; ``path`` is None if cancelled."""
    try:
        return {"path": picker.choose_video()}
    except picker.PickerUnavailable as exc:
        raise HTTPException(501, str(exc)) from None


@app.post("/api/pick-folder")
def pick_folder() -> dict:
    """Native folder dialog for the export folder; ``path`` is None if cancelled."""
    try:
        return {"path": picker.choose_folder(str(load_settings()["export_dir"]))}
    except picker.PickerUnavailable as exc:
        raise HTTPException(501, str(exc)) from None


@app.post("/api/projects/upload")
def upload_project(file: UploadFile = File(...)) -> dict:
    name = media.safe_name(Path(file.filename or "video").stem) + Path(file.filename or ".mp4").suffix.lower()
    target = UPLOADS_DIR / f"{uuid.uuid4().hex[:6]}_{name}"
    with target.open("wb") as fh:
        shutil.copyfileobj(file.file, fh, length=8 * 1024 * 1024)
    return _open_project(str(target))


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict:
    return _with_jobs(_project(pid))


@app.delete("/api/projects/{pid}")
def delete_project(pid: str) -> dict:
    _project(pid)
    for job in jobs.active_for(pid):
        jobs.cancel(job.id)
    shutil.rmtree(store.project_dir(pid), ignore_errors=True)
    return {"ok": True}


@app.get("/api/replays/status")
def replay_status() -> dict:
    settings = load_settings()
    exe, folder = replays.rrrocket_path(settings), replays.demos_dir(settings)
    return {"rrrocket": str(exe) if exe else None, "demos_dir": str(folder) if folder else None,
            "version": replays.RRROCKET_VERSION}


@app.post("/api/replays/rrrocket")
def install_rrrocket() -> dict:
    try:
        replays.download_rrrocket()
    except Exception as exc:  # noqa: BLE001 - network/zip errors go to the UI
        raise HTTPException(502, f"Download failed: {exc}") from exc
    return replay_status()


class ReplayChoice(BaseModel):
    ignored: list[str]


@app.get("/api/projects/{pid}/replays")
def project_replays(pid: str) -> list[dict]:
    """Replays recorded during this video, whether or not they're in use."""
    project = _project(pid)
    ignored = set(project.get("ignored_replays", []))
    found = replays.find_for_recording(load_settings(), project["source"], project["info"]["duration"])
    return [{**r.to_dict(), "ignored": r.id in ignored} for r in found]


@app.put("/api/projects/{pid}/replays")
def choose_replays(pid: str, body: ReplayChoice) -> dict:
    store.mutate(pid, lambda p: p.update(ignored_replays=body.ignored))
    return reanalyze(pid)


@app.post("/api/projects/{pid}/analyze")
def reanalyze(pid: str) -> dict:
    project = _project(pid)
    running = jobs.get(project["jobs"].get("analysis", ""))
    if running and running.status in ("queued", "running"):
        raise HTTPException(409, "Analysis already running")
    start_analysis(pid)
    return _with_jobs(store.get(pid))


@app.post("/api/projects/{pid}/proxy")
def rerender_proxy(pid: str) -> dict:
    start_proxy(pid)
    return _with_jobs(store.get(pid))


@app.post("/api/projects/{pid}/events")
def add_event(pid: str, body: EventIn) -> dict:
    if body.type not in store.EVENT_TYPES:
        raise HTTPException(400, "Unknown event type")
    settings = load_settings()
    project = _project(pid)
    ev = store.make_event(body.type, body.time, project["info"]["duration"], settings)
    ev["selected"] = True

    def apply(p: dict) -> None:
        p["events"].append(ev)
        p["events"].sort(key=lambda e: e["time"])

    store.mutate(pid, apply)
    return ev


@app.patch("/api/projects/{pid}/events/{eid}")
def patch_event(pid: str, eid: str, body: EventPatch) -> dict:
    settings = load_settings()
    result: dict = {}

    def apply(p: dict) -> None:
        e = _find_event(p, eid)
        if body.type is not None:
            if body.type not in store.EVENT_TYPES:
                raise HTTPException(400, "Unknown event type")
            e["type"] = body.type
        if body.selected is not None:
            e["selected"] = body.selected
        if body.frame is not None:
            if body.frame not in ("", "16:9", "9:16"):
                raise HTTPException(400, "Unknown frame")
            e["frame"] = body.frame or None
        if body.style is not None:
            if body.style and body.style not in media.VERTICAL_STYLES:
                raise HTTPException(400, "Unknown style")
            e["style"] = body.style or None
        if body.crop_x is not None:
            e["crop_x"] = round(min(max(body.crop_x, 0.0), 1.0), 4)
        if body.start is not None or body.end is not None:
            e["start"], e["end"] = store.clamp_clip(
                e, body.start if body.start is not None else e["start"],
                body.end if body.end is not None else e["end"],
                float(settings["pre_seconds"]), float(settings["post_seconds"]), p["info"]["duration"])
        result.update(e)

    store.mutate(pid, apply)
    return result


@app.delete("/api/projects/{pid}/events/{eid}")
def delete_event(pid: str, eid: str) -> dict:
    def apply(p: dict) -> None:
        _find_event(p, eid)
        p["events"] = [e for e in p["events"] if e["id"] != eid]
        sequences.prune(p)

    store.mutate(pid, apply)
    return {"ok": True}


@app.post("/api/projects/{pid}/select")
def bulk_select(pid: str, body: SelectIn) -> dict:
    ids = set(body.ids)

    def apply(p: dict) -> None:
        for e in p["events"]:
            if e["id"] in ids:
                e["selected"] = body.selected

    return _with_jobs(store.mutate(pid, apply))


@app.post("/api/projects/{pid}/export")
def export(pid: str, body: ExportIn) -> dict:
    job = start_export(pid, body.ids)
    return job.to_dict()


def _kind(kind: str) -> str:
    if kind not in sequences.KINDS:
        raise HTTPException(404, "Unknown timeline")
    return kind


@app.get("/api/projects/{pid}/sequences/{kind}")
def get_sequence(pid: str, kind: str) -> dict:
    return sequences.get(_project(pid), _kind(kind))


@app.put("/api/projects/{pid}/sequences/{kind}")
def put_sequence(pid: str, kind: str, body: SequenceIn) -> dict:
    _kind(kind)
    settings = load_settings()
    out: dict = {}

    def apply(p: dict) -> None:
        seq = sequences.clean(p, body.model_dump(), settings)
        p.setdefault("sequences", {})[kind] = seq
        out.update(seq)

    store.mutate(pid, apply)
    return out


@app.post("/api/projects/{pid}/sequences/{kind}/export")
def export_sequence(pid: str, kind: str, body: SequenceExportIn) -> dict:
    if body.mode not in ("compiled", "separate"):
        raise HTTPException(400, "Unknown export mode")
    return start_sequence_export(pid, _kind(kind), body.mode).to_dict()


@app.put("/api/projects/{pid}/captions")
def put_captions(pid: str, body: CaptionsIn) -> list[dict]:
    cues = captions.clean(body.captions)
    store.mutate(pid, lambda p: p.update(captions=cues))
    return cues


@app.post("/api/projects/{pid}/captions/transcribe")
def transcribe_captions(pid: str, body: TranscribeIn) -> dict:
    return start_transcribe(pid, body.item_ids).to_dict()


@app.get("/api/captions/status")
def caption_status() -> dict:
    model = str(load_settings()["caption_model"])
    return {"model": model, "ready": captions.model_ready(model), "device": captions.device_in_use()}


@app.post("/api/captions/model")
def caption_model_download() -> dict:
    model = str(load_settings()["caption_model"])

    def work(job: jobs.Job) -> dict:
        job.update(0.05, f"Downloading the {model} speech model")
        captions.download_model(model)
        return {"model": model}

    return jobs.submit("caption_model", "", work).to_dict()


@app.post("/api/projects/{pid}/open-exports")
def open_exports(pid: str) -> dict:
    _project(pid)
    settings = load_settings()
    folder = Path(settings["export_dir"]) if settings["export_dir"] else store.project_dir(pid) / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if hasattr(os, "startfile"):
            os.startfile(folder)  # noqa: S606 - local desktop app
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])
    except OSError:
        pass  # no file manager (e.g. a headless server): the path is still returned
    return {"folder": str(folder)}


@app.get("/api/projects/{pid}/proxy")
def proxy(pid: str) -> FileResponse:
    f = store.project_dir(pid) / "proxy.mp4"
    if not f.exists():
        raise HTTPException(404, "Preview not ready")
    return FileResponse(f, media_type="video/mp4")


@app.get("/api/projects/{pid}/thumbs/{name}")
def thumb(pid: str, name: str) -> FileResponse:
    f = store.project_dir(pid) / "thumbs" / Path(name).name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/jpeg")


@app.get("/api/projects/{pid}/frame")
def frame(pid: str, t: float = 0.0, rois: bool = True) -> Response:
    """A frame of the source with the detection regions drawn — for calibrating ROIs."""
    project = _project(pid)
    try:
        jpg = media.grab_frame(project["source"], t)
    except media.MediaError as exc:
        raise HTTPException(400, str(exc)) from None
    if rois:
        img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        settings = load_settings()
        for key, color in (("tag_roi", (0, 165, 255)), ("scoreboard_roi", (255, 160, 40))):
            x0, y0, x1, y1 = settings[key]
            cv2.rectangle(img, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), color, 3)
        jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
    return Response(jpg, media_type="image/jpeg")


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404)
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    return {"ok": jobs.cancel(job_id)}


# ---------- frontend ----------

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        f = FRONTEND_DIST / path
        if path and f.is_file() and FRONTEND_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
