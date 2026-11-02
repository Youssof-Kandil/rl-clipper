"""Sound effects library (data/sounds): files the user adds, or downloads from Freesound.

A sound is named by its file name, e.g. "bruh.mp3". Freesound downloads keep their
author and licence in credits.json, so attribution (needed for "Attribution" sounds)
is one look away.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

import httpx

from . import media
from .config import DATA_DIR

USER_DIR = DATA_DIR / "sounds"
CREDITS = USER_DIR / "credits.json"
EXTS = (".wav", ".mp3", ".ogg", ".m4a")
MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 15.0
FREESOUND = "https://freesound.org/apiv2"
# Freesound licence name -> short label. Free-to-use (CC0) results are listed first.
LICENSES = {"Creative Commons 0": "CC0", "Attribution": "CC BY", "Attribution NonCommercial": "CC BY-NC"}

_seconds: dict[tuple[str, float], float] = {}


class SoundError(ValueError):
    pass


def _credits() -> dict:
    try:
        return json.loads(CREDITS.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def seconds(path: Path) -> float:
    key = (str(path), path.stat().st_mtime)
    if key not in _seconds:
        out = subprocess.run([media.tool("ffprobe"), "-v", "error", "-select_streams", "a:0", "-print_format", "json",
                              "-show_entries", "format=duration:stream=codec_type", str(path)],
                             capture_output=True, text=True, creationflags=media._NO_WINDOW)
        info = json.loads(out.stdout or "{}") if out.returncode == 0 else {}
        if not info.get("streams"):
            raise SoundError("That file has no audio")
        _seconds[key] = round(float(info.get("format", {}).get("duration") or 0), 2)
    return _seconds[key]


def list_sounds() -> list[dict]:
    if not USER_DIR.is_dir():
        return []
    credits = _credits()
    out = []
    for p in sorted(USER_DIR.iterdir(), key=lambda p: p.name.lower()):
        if p.suffix.lower() not in EXTS or not p.is_file() or p.name.startswith("."):
            continue
        try:
            out.append({"name": p.name, "label": p.stem, "seconds": seconds(p), "credit": credits.get(p.name)})
        except (SoundError, OSError, media.MediaError):
            continue
    return out


def path(name: str) -> Path | None:
    """The file for a sound name, or None."""
    if not name or Path(name).name != name or Path(name).suffix.lower() not in EXTS or name.startswith("."):
        return None
    p = USER_DIR / name
    return p if p.is_file() else None


def add(filename: str, data: BinaryIO, credit: dict | None = None) -> dict:
    ext = Path(filename or "").suffix.lower()
    if ext not in EXTS:
        raise SoundError(f"Use a {', '.join(EXTS)} file")
    stem = media.file_name(Path(filename).stem) or "sound"
    USER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = USER_DIR / f".upload_{uuid.uuid4().hex[:8]}{ext}"
    try:
        with tmp.open("wb") as fh:
            size = 0
            while chunk := data.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise SoundError("Sound files can be up to 10 MB")
                fh.write(chunk)
        length = seconds(tmp)
        if length > MAX_SECONDS:
            raise SoundError(f"Sound effects can be up to {MAX_SECONDS:.0f} seconds (this one is {length:.0f} s)")
        target, n = USER_DIR / f"{stem}{ext}", 2
        while target.exists():
            target, n = USER_DIR / f"{stem} {n}{ext}", n + 1
        shutil.move(str(tmp), target)
    finally:
        tmp.unlink(missing_ok=True)
    if credit:
        CREDITS.write_text(json.dumps({**_credits(), target.name: credit}, indent=1), "utf-8")
    return {"name": target.name, "label": target.stem, "seconds": length, "credit": credit}


def remove(name: str) -> None:
    p = path(name)
    if p is None:
        raise SoundError("No such sound")
    p.unlink()
    credits = _credits()
    if credits.pop(name, None) is not None:
        CREDITS.write_text(json.dumps(credits, indent=1), "utf-8")


# ---------------------------------------------------------------- Freesound

def _key(settings: dict) -> str:
    key = str(settings.get("freesound_api_key") or "").strip()
    if not key:
        raise SoundError("Add a Freesound API key in Settings to search online sounds")
    return key


def _get(client: httpx.Client, url: str, key: str, **params: object) -> dict:
    r = client.get(url, params=params, headers={"Authorization": f"Token {key}"})
    if r.status_code in (401, 403):
        raise SoundError("Freesound didn't accept the API key; check it in Settings")
    if r.status_code >= 400:
        raise SoundError(f"Freesound search failed ({r.status_code})")
    return r.json()


def _result(s: dict) -> dict:
    return {"id": s["id"], "name": s["name"], "user": s.get("username", ""),
            "license": LICENSES.get(s.get("license", ""), s.get("license", "")),
            "seconds": round(float(s.get("duration") or 0), 2), "downloads": s.get("num_downloads", 0),
            "preview": (s.get("previews") or {}).get("preview-hq-mp3", ""),
            "url": f"https://freesound.org/s/{s['id']}/"}


FIELDS = "id,name,username,license,duration,previews,num_downloads"


def search(settings: dict, query: str, page: int = 1, client: httpx.Client | None = None) -> dict:
    """Short Freesound sounds for ``query``, free-to-use (CC0) first, then the rest."""
    key = _key(settings)
    with client or httpx.Client(timeout=20, follow_redirects=True) as c:
        data = _get(c, f"{FREESOUND}/search/", key, query=query.strip(), page=max(page, 1), page_size=30,
                    fields=FIELDS, filter=f"duration:[0 TO {MAX_SECONDS:g}]")
    results = [_result(s) for s in data.get("results", [])]
    results.sort(key=lambda r: r["license"] != "CC0")
    return {"results": results, "count": data.get("count", 0), "more": bool(data.get("next"))}


def add_freesound(settings: dict, sound_id: int, client: httpx.Client | None = None) -> dict:
    """Download a Freesound sound's high-quality mp3 preview into the library."""
    key = _key(settings)
    with client or httpx.Client(timeout=30, follow_redirects=True) as c:
        s = _result(_get(c, f"{FREESOUND}/sounds/{int(sound_id)}/", key, fields=FIELDS))
        if not s["preview"]:
            raise SoundError("That sound has no preview to download")
        host = urlparse(s["preview"]).hostname or ""
        # Previews come from Freesound's CDN; only ever send the key to Freesound itself.
        headers = {"Authorization": f"Token {key}"} if host == "freesound.org" or host.endswith(".freesound.org") \
            else {}
        r = c.get(s["preview"], headers=headers)
        if r.status_code >= 400:
            raise SoundError(f"Downloading the sound failed ({r.status_code})")
        if len(r.content) > MAX_BYTES:
            raise SoundError("Sound files can be up to 10 MB")
    credit = {"source": "Freesound", "id": s["id"], "title": s["name"], "user": s["user"], "license": s["license"],
              "url": s["url"]}
    return add(f"{Path(s['name']).stem}.mp3", io.BytesIO(r.content), credit)
