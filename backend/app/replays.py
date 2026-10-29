"""Rocket League replay files: find the ones that belong to a recording and read
every player's goals, saves and epic saves at their exact moment.

Parsing is done by rrrocket (https://github.com/nickbabcock/rrrocket), which turns a
.replay into JSON. Header-only parses are near-instant; network parses (needed for
event timings) take well under a second per match.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .config import ROOT
from .media import _NO_WINDOW

TEAM_COLORS = ("blue", "orange")
TOOLS_DIR = ROOT / "tools"
RRROCKET_VERSION = "0.11.6"
RRROCKET_EXE = "rrrocket.exe" if sys.platform == "win32" else "rrrocket"
# Release builds per platform (https://github.com/nickbabcock/rrrocket/releases).
_RRROCKET_TARGETS = {
    ("win32", "x86_64"): "x86_64-pc-windows-msvc.zip",
    ("linux", "x86_64"): "x86_64-unknown-linux-musl.tar.gz",
    ("darwin", "x86_64"): "x86_64-apple-darwin.tar.gz",
    ("darwin", "arm64"): "aarch64-apple-darwin.tar.gz",
}


def rrrocket_url() -> str | None:
    """Download URL of the pinned rrrocket build for this machine, if there is one."""
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(
        platform.machine().lower(), platform.machine().lower())
    target = _RRROCKET_TARGETS.get((sys.platform, arch))
    return (f"https://github.com/nickbabcock/rrrocket/releases/download/v{RRROCKET_VERSION}/"
            f"rrrocket-{RRROCKET_VERSION}-{target}") if target else None

# A stat event and the player's matching counter update arrive up to ~1 s apart.
_PAIR_WINDOW = 2.0
_STAT_KINDS = {"Goal": "goal", "Save": "save", "EpicSave": "epic_save"}
_COUNTER_KIND = {"TAGame.PRI_TA:MatchGoals": "goal", "TAGame.PRI_TA:MatchSaves": "save"}


@dataclass
class ReplayEvent:
    time: float  # seconds from the first replay frame
    kind: str  # goal | save | epic_save
    player: str
    team: str  # blue | orange
    score: tuple[int, int] | None = None  # (blue, orange) after a goal


@dataclass
class ReplayInfo:
    path: str
    id: str
    name: str
    map: str
    start_epoch: float
    duration: float  # seconds of play the replay covers
    score: tuple[int, int]
    owner: str
    players: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- locating things

def rrrocket_path(settings: dict) -> Path | None:
    """The setting, else the copy downloaded into tools/, else one on PATH."""
    for candidate in (settings.get("rrrocket_path") or "", TOOLS_DIR / RRROCKET_EXE, shutil.which("rrrocket") or ""):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def _demo_dirs() -> list[Path]:
    """Where Rocket League saves replays: Windows (also under OneDrive), and Linux through
    Steam's Proton (the game's Windows "Documents" lives inside its compatdata prefix)."""
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    rel = Path("My Games") / "Rocket League" / "TAGame" / "Demos"
    dirs = [home / "OneDrive" / "Documents" / rel, home / "Documents" / rel]
    proton = Path("steamapps") / "compatdata" / "252950" / "pfx" / "drive_c" / "users" / "steamuser" / "Documents" / rel
    for steam in (home / ".local" / "share" / "Steam", home / ".steam" / "steam",
                  home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"):
        dirs.append(steam / proton)
    return dirs


def demos_dir(settings: dict) -> Path | None:
    if settings.get("demos_dir"):
        p = Path(settings["demos_dir"])
        return p if p.is_dir() else None
    return next((p for p in _demo_dirs() if p.is_dir()), None)


def recording_start(path: str) -> float | None:
    """Wall-clock start of an OBS recording, from its default "YYYY-MM-DD HH-MM-SS" name."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[ _](\d{2})-(\d{2})-(\d{2})", Path(path).stem)
    if m:
        return datetime(*map(int, m.groups())).timestamp()
    try:
        return os.stat(path).st_ctime
    except OSError:
        return None


# ---------------------------------------------------------------- parsing

def _run(exe: Path, args: list[str]) -> dict:
    out = subprocess.run([str(exe), *args], capture_output=True, check=True, creationflags=_NO_WINDOW)
    return json.loads(out.stdout)


def _fix_text(s: str) -> str:
    """Header strings come out as UTF-8 decoded with cp1252 ("Ã£Æ’â€ž" for "ツ")."""
    for enc in ("cp1252", "latin-1"):
        try:
            return s.encode(enc).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return s


def read_header(exe: Path, path: Path) -> ReplayInfo:
    p = _run(exe, [str(path)])["properties"]
    players = [{"name": _fix_text(s.get("Name", "")), "team": TEAM_COLORS[int(s.get("Team", 0)) % 2],
                "goals": s.get("Goals", 0), "saves": s.get("Saves", 0)}
               for s in p.get("PlayerStats") or []]
    return ReplayInfo(
        path=str(path), id=p.get("Id", path.stem), name=_fix_text(p.get("ReplayName", "")),
        map=p.get("MapName", ""), start_epoch=float(p.get("MatchStartEpoch") or 0),
        duration=float(p.get("NumFrames", 0)) / float(p.get("RecordFPS") or 30),
        score=(int(p.get("Team0Score", 0)), int(p.get("Team1Score", 0))),
        owner=_fix_text(p.get("PlayerName", "")), players=players)


def read_replay(exe: Path, info: ReplayInfo) -> tuple[list[ReplayEvent], list[tuple[float, int]]]:
    """Every player's plays, and the match clock's ticks, from one network parse.

    Also corrects ``info.duration``: the header's frame count misses the time the
    replay skips after goals, so the real length comes from the last frame's time.
    """
    data = _run(exe, ["-n", info.path])
    frames = data["network_frames"]["frames"]
    if frames:
        info.duration = round(frames[-1]["time"] - frames[0]["time"], 3)
    return events_from_json(data), clock_ticks_from_json(data)


def clock_ticks_from_json(replay: dict) -> list[tuple[float, int]]:
    """(replay time, seconds left) each time the match clock changes.

    In overtime the same attribute counts up (1, 2, 3 …); those ticks are stored
    negative (-1, -2, -3 …), matching how the video's "+0:03" is read.
    """
    objects = replay["objects"]
    frames = replay["network_frames"]["frames"]
    if not frames:
        return []
    t0 = frames[0]["time"]
    ticks: list[tuple[float, int]] = []
    overtime = False
    for frame in frames:
        for upd in frame["updated_actors"]:
            name = objects[upd["object_id"]]
            if name == "TAGame.GameEvent_Soccar_TA:bOverTime":
                overtime = bool(upd["attribute"].get("Boolean"))
            elif name == "TAGame.GameEvent_Soccar_TA:SecondsRemaining":
                value = upd["attribute"].get("Int")
                if value is None:
                    continue
                value = -value if overtime and value > 0 else value
                if not ticks or ticks[-1][1] != value:
                    ticks.append((round(frame["time"] - t0, 3), value))
    return ticks


def events_from_json(replay: dict) -> list[ReplayEvent]:
    """Walk the network frames and pair each stat event with the player who earned it.

    ``ReplicatedStatEvent`` says *what* happened and exactly when (Goal / Save /
    EpicSave, for every player); the player's ``MatchGoals``/``MatchSaves`` counter
    going up shortly after says *who*.
    """
    objects = replay["objects"]
    frames = replay["network_frames"]["frames"]
    if not frames:
        return []
    t0 = frames[0]["time"]
    names: dict[int, str] = {}
    team_of_pri: dict[int, int] = {}
    team_actors: dict[int, int] = {}
    counters: dict[tuple[int, str], int] = {}
    stats: list[tuple[float, str]] = []  # (time, kind) not yet tied to a player
    increments: list[tuple[float, str, int]] = []  # (time, kind, pri actor)

    for frame in frames:
        t = frame["time"] - t0
        for actor in frame["new_actors"]:
            obj = objects[actor["object_id"]]
            m = re.search(r"Archetypes\.Teams\.Team([01])$", obj)
            if m:
                team_actors[actor["actor_id"]] = int(m.group(1))
        for upd in frame["updated_actors"]:
            name = objects[upd["object_id"]]
            attr = upd["attribute"]
            aid = upd["actor_id"]
            if name == "Engine.PlayerReplicationInfo:PlayerName":
                names[aid] = attr.get("String", "")
            elif name == "Engine.PlayerReplicationInfo:Team":
                team = team_actors.get(attr.get("ActiveActor", {}).get("actor"))
                if team is not None:
                    team_of_pri[aid] = team
            elif name in _COUNTER_KIND:
                value = attr.get("Int", 0)
                # Counters are re-sent often; only an increase is an event.
                if value > counters.get((aid, name), 0):
                    increments.append((t, _COUNTER_KIND[name], aid))
                counters[(aid, name)] = value
            elif name == "TAGame.GameEvent_Soccar_TA:ReplicatedStatEvent":
                event_name = objects[attr.get("StatEvent", {}).get("object_id", 0)]
                kind = _STAT_KINDS.get(event_name.rsplit(".", 1)[-1])
                if kind:
                    stats.append((t, kind))

    events: list[ReplayEvent] = []
    used: set[int] = set()
    for t, kind in stats:
        counter_kind = "goal" if kind == "goal" else "save"
        # The same save is sometimes announced twice a few frames apart.
        if events and events[-1].time > t - 1.0 and (events[-1].kind == "goal") == (kind == "goal"):
            if kind == "epic_save":
                events[-1].kind = "epic_save"
            continue
        match = next((i for i, (ti, k, _) in enumerate(increments)
                      if i not in used and k == counter_kind and t - 0.5 <= ti <= t + _PAIR_WINDOW), None)
        if match is None:
            continue
        used.add(match)
        pri = increments[match][2]
        events.append(ReplayEvent(round(t, 3), kind, names.get(pri, "?"),
                                  TEAM_COLORS[team_of_pri.get(pri, 0)]))

    score = [0, 0]
    for e in events:
        if e.kind == "goal":
            score[TEAM_COLORS.index(e.team)] += 1
            e.score = (score[0], score[1])
    return events


# ---------------------------------------------------------------- matching to a recording

def find_for_recording(settings: dict, video: str, duration: float) -> list[ReplayInfo]:
    """Replays whose match started while the recording was running, in match order."""
    exe, folder, rec_start = rrrocket_path(settings), demos_dir(settings), recording_start(video)
    if not exe or not folder or rec_start is None:
        return []
    rec_end = rec_start + duration
    found = []
    for path in folder.glob("*.replay"):
        # A replay is saved after its match ends, so anything older can't be from this video.
        if path.stat().st_mtime < rec_start:
            continue
        try:
            info = read_header(exe, path)
        except (subprocess.CalledProcessError, json.JSONDecodeError, OSError, ValueError):
            continue
        if rec_start - 120 <= info.start_epoch <= rec_end:
            found.append(info)
    found.sort(key=lambda r: r.start_epoch)
    return found


def download_rrrocket() -> Path:
    """Fetch the pinned rrrocket release for this platform into tools/."""
    import io
    import stat
    import tarfile
    import urllib.request
    import zipfile

    url = rrrocket_url()
    if not url:
        raise RuntimeError(f"No rrrocket build for {sys.platform}/{platform.machine()}. Install it yourself "
                           "(cargo install rrrocket) and set its path in Settings.")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read()
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            exe = zf.read(next(n for n in zf.namelist() if n.endswith(RRROCKET_EXE)))
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            member = next(m for m in tf.getmembers() if m.isfile() and Path(m.name).name == RRROCKET_EXE)
            exe = tf.extractfile(member).read()
    target = TOOLS_DIR / RRROCKET_EXE
    target.write_bytes(exe)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target
