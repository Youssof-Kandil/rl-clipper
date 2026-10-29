"""Paths and user-editable settings (stored in data/settings.json)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("RLC_DATA_DIR", ROOT / "data"))
PROJECTS_DIR = DATA_DIR / "projects"
UPLOADS_DIR = DATA_DIR / "uploads"
SETTINGS_FILE = DATA_DIR / "settings.json"
FRONTEND_DIST = ROOT / "frontend" / "dist"

# Regions are fractions of the frame: [x0, y0, x1, y1].
DEFAULT_SETTINGS: dict = {
    # Frames per second sampled from the video for point-tag detection.
    "sample_fps": 2.0,
    # Width frames are downscaled to before detection.
    "analysis_width": 1280,
    # Where the point tags ("SAVE +50", "EPIC SAVE +75", "GOAL +100") pop up.
    # Point tags pop up just under the scoreboard (title at y≈0.17, points at y≈0.19 at default HUD scale).
    "tag_roi": [0.40, 0.12, 0.60, 0.23],
    # The score / clock box at the top centre.
    "scoreboard_roi": [0.40, 0.0, 0.60, 0.09],
    "scoreboard_interval": 1.0,
    "use_scoreboard": True,
    # Fraction of near-white pixels in the tag ROI needed before OCR runs.
    "tag_white_ratio": 0.002,
    # Same-type hits closer than this (seconds) are one event.
    "merge_window": 4.0,
    # A scoreboard goal this close to a GOAL tag is the same goal.
    "goal_merge_window": 6.0,
    # Point tags animate in about a second after the play; move tag events back by this much.
    "tag_lead": 1.0,
    # Seconds kept before/after the event. Also the limit for trimming: clips can be
    # shortened inside this range but never extended past it.
    "pre_seconds": 10.0,
    "post_seconds": 10.0,
    # Source audio track indexes (0-based, OBS track 1 = 0).
    "game_track": 0,
    "mic_track": 1,
    # "auto" picks NVENC when it works, else libx264.
    "encoder": "auto",
    # Export size: "best" (largest), "balanced", or "small" (HEVC, about 40% smaller
    # than balanced; a few old players can't open it).
    "export_quality": "balanced",
    "export_dir": "",
    # Set once you've picked where exports go (a folder, or the project folder on purpose),
    # so the first export asks and later ones don't.
    "export_dir_chosen": False,
    # Export frame: "16:9" keeps the recording as it is; "9:16" makes 1080x1920 for
    # TikTok / Shorts / Reels. Each clip can override it.
    "frame": "16:9",
    # How 9:16 is filled: "focus45" (sharp full-height 4:5 crop in the middle over a
    # blurred 9:16 crop), "focus" (sharp oval, blurring towards the edges), "crop"
    # (tall crop only) or "fit" (whole frame on a blurred background).
    "vertical_style": "focus45",
    # Focus style: blur strength (sigma at 1080p), share of the height kept sharp,
    # and extra zoom into the crop (1 = full height).
    "vertical_blur": 30.0,
    "vertical_sharp": 0.55,
    "vertical_zoom": 1.0,
    # Captions (TikTok timeline): faster-whisper model, text size in px at 1080 wide,
    # where the line sits in the focus area (upper / middle / lower), ALL CAPS.
    "caption_model": "small.en",
    "caption_size": 78,
    "caption_position": "lower",
    "caption_upper": False,
    # Colour the word being said; most words per caption (applies to new transcriptions).
    "caption_highlight": True,
    "caption_color": "#2EA8FF",
    "caption_max_words": 8,
    # Rocket League replays: matched to the recording by start time and used instead of
    # on-screen detection for every match that has one. Empty = auto-detect.
    "use_replays": True,
    "demos_dir": "",
    "rrrocket_path": "",
    # Your in-game name; your own plays are pre-ticked for export. Empty = replay owner.
    "my_player_name": "",
}

_lock = threading.Lock()


def ensure_dirs() -> None:
    for d in (DATA_DIR, PROJECTS_DIR, UPLOADS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    ensure_dirs()
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            stored = json.loads(SETTINGS_FILE.read_text("utf-8"))
            settings.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
        except (OSError, json.JSONDecodeError):
            pass
    return settings


def save_settings(update: dict) -> dict:
    with _lock:
        settings = load_settings()
        for key, value in update.items():
            if key in DEFAULT_SETTINGS:
                settings[key] = value
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), "utf-8")
        return settings
