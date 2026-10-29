"""Captions of what you say: transcribe the mic track, cut it into short lines, and
write them as ASS subtitles for ffmpeg to burn in.

Transcription is faster-whisper (local; GPU when it works, CPU otherwise). Cues are
kept in source-video seconds so one set serves every timeline the moment appears in.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Callable

import numpy as np

from . import media
from .config import DATA_DIR

MODELS_DIR = DATA_DIR / "models"
# Download sizes, shown before fetching (the models are too big to ship in the repo).
MODEL_SIZES = {"base.en": "~150 MB", "small.en": "~480 MB", "medium.en": "~1.5 GB",
               "distil-large-v3.5": "~1.5 GB", "large-v3-turbo": "~1.6 GB", "large-v3": "~3 GB"}
# A caption is a sentence (or part of a long one): up to MAX_WORDS words (about two
# lines on screen), split at sentence ends and at pauses.
MAX_WORDS = 8
MAX_LINE_SECONDS = 3.5
PAUSE_BREAK = 0.6
# Extra audio around a clip: a few seconds before give the model the start of the
# sentence (only words inside the clip are kept); a little after catches cut-off words.
_PAD_BEFORE = 3.0
_PAD_AFTER = 1.0
# Whisper continues from its prompt: written in punctuated sentences, it nudges the
# model to punctuate (captions split at sentence ends), and it spells Rocket League
# terms the way players write them.
PROMPT = ("Rocket League gameplay commentary. What a save! Nice shot, that was a flip reset into a musty flick. "
          "Ceiling shot, air dribble, double tap, demo, boost, kickoff, overtime, backboard, half-flip, "
          "wavedash, speed flip, pinch, bump, rotation.")

Word = tuple[float, float, str]  # (start, end, text) in source-video seconds
Progress = Callable[[float, str], None]


# ---------------------------------------------------------------- cues

def new_cue(start: float, end: float, text: str, words: list[dict] | None = None) -> dict:
    cue = {"id": uuid.uuid4().hex[:8], "start": round(start, 2), "end": round(end, 2), "text": text}
    if words:
        cue["words"] = words
    return cue


def chunk_words(words: list[Word], max_words: int = MAX_WORDS) -> list[dict]:
    """Group words into captions of at most ``max_words`` / MAX_LINE_SECONDS, breaking
    at pauses and at the end of sentences. Each cue keeps its words' timings."""
    lines: list[list[Word]] = []
    for w in words:
        if not w[2].strip():
            continue
        cur = lines[-1] if lines else None
        if (cur is None or len(cur) >= max_words or w[1] - cur[0][0] > MAX_LINE_SECONDS
                or w[0] - cur[-1][1] > PAUSE_BREAK or re.search(r"[.?!]$", cur[-1][2].strip())):
            lines.append([w])
        else:
            cur.append(w)
    cues = []
    for i, line in enumerate(lines):
        start, end = line[0][0], line[-1][1]
        # Linger a little after the last word, but never into the next line.
        nxt = lines[i + 1][0][0] if i + 1 < len(lines) else end + 0.3
        end = min(max(end + 0.15, start + 0.4), max(nxt, end))
        timed = [{"start": round(a, 2), "end": round(b, 2), "text": t.strip()} for a, b, t in line]
        cues.append(new_cue(start, end, " ".join(w["text"] for w in timed), timed))
    return cues


def cue_words(cue: dict) -> list[dict]:
    """The cue's words with timings: as spoken when the text is still what Whisper heard,
    otherwise (edited text) spread evenly over the cue."""
    tokens = cue["text"].split()
    words = cue.get("words") or []
    if [w["text"] for w in words] == tokens:
        return words
    if not tokens:
        return []
    step = (cue["end"] - cue["start"]) / len(tokens)
    return [{"start": round(cue["start"] + i * step, 2), "end": round(cue["start"] + (i + 1) * step, 2), "text": t}
            for i, t in enumerate(tokens)]


def merge(existing: list[dict], new: list[dict], ranges: list[tuple[float, float]]) -> list[dict]:
    """Replace the cues touching freshly transcribed ``ranges``; keep every other cue."""
    def inside(c: dict) -> bool:
        return any(c["end"] > a and c["start"] < b for a, b in ranges)

    return sorted([c for c in existing if not inside(c)] + new, key=lambda c: c["start"])


def clean(cues: list[dict]) -> list[dict]:
    out = []
    for c in cues:
        text = str(c.get("text", "")).strip()
        start, end = float(c["start"]), float(c["end"])
        if not text or end <= start:
            continue
        cue = {"id": str(c.get("id") or uuid.uuid4().hex[:8]), "start": round(start, 2),
               "end": round(end, 2), "text": text}
        words = [{"start": round(float(w["start"]), 2), "end": round(float(w["end"]), 2), "text": str(w["text"])}
                 for w in c.get("words") or [] if isinstance(w, dict) and {"start", "end", "text"} <= w.keys()]
        if words:
            cue["words"] = words
        out.append(cue)
    return sorted(out, key=lambda c: c["start"])


# ---------------------------------------------------------------- ASS subtitles

# Where the caption's centre sits, as a fraction of the frame height.
# 9:16 focus45: the sharp 4:5 band spans 285-1635 of 1920; lines stay inside it.
_POSITIONS = {
    "vertical": {"upper": 0.27, "middle": 0.5, "lower": 0.70},
    "wide": {"upper": 0.18, "middle": 0.5, "lower": 0.84},
}
FONT = "Arial Black"


def _ass_time(t: float) -> str:
    t = max(t, 0.0)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_text(text: str, upper: bool) -> str:
    text = text.upper() if upper else text
    # Braces start override blocks and backslashes escapes in ASS.
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ass_color(hex_rgb: str) -> str:
    """"#2EA8FF" -> ASS "&H00FFA82E&" (ASS colours are BGR)."""
    h = hex_rgb.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        h = "2EA8FF"
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _segments(cue: dict, highlight: bool) -> list[tuple[float, float, int]]:
    """(start, end, highlighted word index or -1) pieces of a cue: before the first word
    nothing is highlighted, then each word stays lit until the next one starts."""
    if not highlight:
        return [(cue["start"], cue["end"], -1)]
    words = cue_words(cue)
    if not words:
        return [(cue["start"], cue["end"], -1)]
    out = []
    first = max(min(words[0]["start"], cue["end"]), cue["start"])
    if first > cue["start"]:
        out.append((cue["start"], first, -1))
    for i, w in enumerate(words):
        a = max(w["start"], cue["start"]) if i else first
        b = words[i + 1]["start"] if i + 1 < len(words) else cue["end"]
        b = min(max(b, a), cue["end"])
        if b > a:
            out.append((a, b, i))
    return out


def caption_y(size: tuple[int, int], position: str) -> int:
    w, h = size
    return int(h * _POSITIONS["vertical" if h > w else "wide"].get(position, 0.70 if h > w else 0.84))


def write_ass(path: Path, cues: list[dict], clip_start: float, clip_end: float,
              size: tuple[int, int], font_size: int = 78, position: str = "lower",
              upper: bool = False, highlight: bool = True, color: str = "#2EA8FF") -> Path:
    """Subtitles for one clip: the cues overlapping [clip_start, clip_end], timed from
    the clip's first frame. With ``highlight`` the word being said is drawn in
    ``color`` (one subtitle event per word, the rest of the sentence white)."""
    w, h = size
    y = caption_y(size, position)
    outline = max(round(font_size / 12), 3)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{FONT},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,"
        f"-1,0,0,0,100,100,1,0,1,{outline},{max(outline // 2, 2)},5,60,60,0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lit = _ass_color(color)
    for c in cues:
        if c["end"] <= clip_start or c["start"] >= clip_end:
            continue
        words = c["text"].split()
        for seg_a, seg_b, idx in _segments(c, highlight):
            a, b = max(seg_a, clip_start) - clip_start, min(seg_b, clip_end) - clip_start
            if b <= a:
                continue
            text = " ".join(f"{{\\c{lit}}}{_ass_text(t, upper)}{{\\c&H00FFFFFF&}}" if i == idx else _ass_text(t, upper)
                            for i, t in enumerate(words))
            lines.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Cap,,0,0,0,,"
                         f"{{\\an5\\pos({w // 2},{y})}}{text}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", "utf-8")
    return path


# ---------------------------------------------------------------- transcription

_model_lock = threading.Lock()
_model: tuple[str, str, object] | None = None  # (name, device, WhisperModel)


def model_path(name: str) -> Path:
    return MODELS_DIR / f"whisper-{name}"


def model_ready(name: str) -> bool:
    return (model_path(name) / "model.bin").is_file()


_download_lock = threading.Lock()


def download_model(name: str) -> Path:
    """Fetch a Whisper model into data/models (once; a second caller waits for the first)."""
    from faster_whisper import download_model as fw_download

    target = model_path(name)
    with _download_lock:
        if not model_ready(name):
            target.mkdir(parents=True, exist_ok=True)
            fw_download(name, output_dir=str(target))
    return target


def _add_cuda_libs() -> None:
    """Let the speech engine find cuBLAS / cuDNN from the optional ``gpu`` dependency
    group (pip's nvidia-* packages keep their DLLs in site-packages/nvidia/*/bin)."""
    try:
        import nvidia
    except ImportError:
        return
    for root in getattr(nvidia, "__path__", []):
        for bin_dir in sorted(Path(root).glob("*/bin")):
            if str(bin_dir) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(bin_dir))


def _load(name: str, device: str):
    from faster_whisper import WhisperModel

    if device == "cuda":
        _add_cuda_libs()

    # int8 weights on both devices: same captions whichever runs them (float16 on the
    # GPU is no faster here and punctuates noticeably differently).
    compute = "int8_float32" if device == "cuda" else "int8"
    return WhisperModel(str(model_path(name)), device=device, compute_type=compute)


def _whisper(name: str):
    """The loaded model, trying the GPU first. Returns (device, model)."""
    global _model
    with _model_lock:
        if _model and _model[0] == name:
            return _model[1], _model[2]
        for device in ("cuda", "cpu"):
            try:
                m = _load(name, device)
                if device == "cuda":
                    # CUDA problems often only show up on first use.
                    list(m.transcribe(np.zeros(16000, np.float32), language="en")[0])
                _model = (name, device, m)
                return device, m
            except Exception:  # noqa: BLE001 - any CUDA/cuDNN failure means "use the CPU"
                if device == "cpu":
                    raise
        raise RuntimeError("unreachable")


def device_in_use() -> str | None:
    return _model[1] if _model else None


def gpu_status() -> tuple[bool, str]:
    """Whether captions can run on the GPU, and why not (cheap: nothing is loaded)."""
    try:
        import ctranslate2
    except ImportError:
        return False, "speech engine not installed"
    try:
        if ctranslate2.get_cuda_device_count() == 0:
            return False, "no NVIDIA GPU"
    except Exception:  # noqa: BLE001 - a broken CUDA driver is just "no GPU"
        return False, "no NVIDIA GPU"
    try:
        import nvidia.cublas  # noqa: F401
        import nvidia.cudnn  # noqa: F401
    except ImportError:
        return False, "GPU libraries missing (uv sync --group gpu)"
    return True, ""


def _audio(src: str, start: float, end: float, track: int) -> np.ndarray:
    cmd = [media.tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}",
           "-to", f"{end:.3f}", "-i", src, "-map", f"0:a:{track}", "-ac", "1", "-ar", "16000",
           "-f", "s16le", "-"]
    out = subprocess.run(cmd, capture_output=True, creationflags=media._NO_WINDOW)
    if out.returncode != 0:
        raise media.MediaError(f"Could not read the mic track: {out.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(out.stdout, np.int16).astype(np.float32) / 32768.0


def transcribe(src: str, ranges: list[tuple[float, float]], track: int, model: str,
               progress: Progress | None = None, cancelled: Callable[[], bool] = lambda: False,
               max_words: int = MAX_WORDS, prompt: bool = True) -> list[dict]:
    """Caption cues (source-video time) for what's said on ``track`` inside ``ranges``."""
    device, whisper = _whisper(model)
    cues: list[dict] = []
    for i, (a, b) in enumerate(ranges):
        if cancelled():
            raise InterruptedError("Cancelled")
        if progress:
            progress(i / len(ranges), f"Transcribing clip {i + 1}/{len(ranges)} ({device.upper()})")
        start = max(a - _PAD_BEFORE, 0.0)
        audio = _audio(src, start, b + _PAD_AFTER, track)
        if audio.size < 1600:
            continue
        segments, _ = whisper.transcribe(audio, language="en", word_timestamps=True, vad_filter=True,
                                         beam_size=5, condition_on_previous_text=False,
                                         initial_prompt=PROMPT if prompt else None)
        words = [(start + w.start, start + w.end, w.word) for s in segments for w in (s.words or [])]
        # Only keep words spoken inside the clip itself.
        words = [w for w in words if w[1] > a and w[0] < b]
        cues += chunk_words(words, max_words)
    if progress:
        progress(1.0, "Transcribed")
    return cues
