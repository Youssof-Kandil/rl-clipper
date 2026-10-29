"""ffmpeg/ffprobe helpers: probing, preview proxy, clip export."""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Callable

ProgressCb = Callable[[float], None]

# Hide console windows spawned by ffmpeg on Windows.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class MediaError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def tool(name: str) -> str:
    """Locate ffmpeg/ffprobe on PATH, falling back to winget's install folder."""
    found = shutil.which(name)
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    pattern = os.path.join(local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "**", "bin", f"{name}.exe")
    matches = sorted(glob.glob(pattern, recursive=True))
    if matches:
        return matches[-1]
    hint = {"win32": "winget install Gyan.FFmpeg", "darwin": "brew install ffmpeg"}.get(
        sys.platform, "sudo apt install ffmpeg (or your distro's package)")
    raise MediaError(f"{name} not found. Install ffmpeg ({hint}) and restart.")


def _listed(kind: str, name: str) -> bool:
    try:
        out = subprocess.run([tool("ffmpeg"), "-hide_banner", f"-{kind}"], capture_output=True, text=True,
                             creationflags=_NO_WINDOW, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired, MediaError):
        return False
    return any(line.split()[1:2] == [name] for line in out.splitlines() if line.strip())


@lru_cache(maxsize=None)
def has_encoder(name: str) -> bool:
    """Whether this ffmpeg build includes an encoder (e.g. libx265 is missing from some)."""
    return _listed("encoders", name)


@lru_cache(maxsize=None)
def has_filter(name: str) -> bool:
    """Whether this ffmpeg build includes a filter. ``subtitles`` (burned-in captions)
    needs libass, which some builds leave out (Homebrew's basic ffmpeg, for one)."""
    return _listed("filters", name)


CAPTIONS_NEED_LIBASS = ("This ffmpeg can't burn in captions (it was built without libass). Install a full "
                        "ffmpeg build, or turn off \"Burn in captions\" for this export.")


def _parse_rate(rate: str | None) -> float:
    if not rate or rate == "0/0":
        return 0.0
    if "/" in rate:
        num, den = rate.split("/")
        return float(num) / float(den) if float(den) else 0.0
    return float(rate)


def probe(path: str | Path) -> dict:
    cmd = [tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)
    if out.returncode != 0:
        raise MediaError(f"ffprobe failed: {out.stderr.strip()[:500]}")
    info = json.loads(out.stdout)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise MediaError("No video stream found")
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0)
    return {
        "duration": duration,
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate")),
        "video_codec": video.get("codec_name"),
        "audio_streams": len(audio),
        "audio": [
            {"index": i, "codec": s.get("codec_name"), "channels": s.get("channels"),
             "title": (s.get("tags") or {}).get("title") or (s.get("tags") or {}).get("handler_name", "")}
            for i, s in enumerate(audio)
        ],
    }


@lru_cache(maxsize=None)
def nvenc_available() -> bool:
    cmd = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "color=black:s=256x144:d=0.2", "-c:v", "h264_nvenc", "-f", "null", "-"]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=30, creationflags=_NO_WINDOW).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# Export size / quality presets. Measured on a fast 60 fps 1080x1920 clip against a
# lossless render (VMAF, 2-minute size): best 94 / ~480 MB, balanced 93 / ~380 MB,
# small 91 / ~235 MB (HEVC). The old fixed setting was 94 / ~560 MB.
QUALITIES = ("best", "balanced", "small")
_NVENC_CQ = {"best": 21, "balanced": 23, "small": 24}
_X264_CRF = {"best": 17, "balanced": 19, "small": 23}


def video_encoder_args(encoder: str = "auto", quality: str = "balanced") -> list[str]:
    quality = quality if quality in QUALITIES else "balanced"
    use_nvenc = encoder == "nvenc" or (encoder == "auto" and nvenc_available())
    # Small = HEVC; an ffmpeg build without libx265 (CPU) gets a smaller H.264 instead.
    hevc = quality == "small" and (use_nvenc or has_encoder("libx265"))
    # hvc1 tag: Apple players and some upload sites only accept HEVC MP4s tagged that way.
    tag = ["-tag:v", "hvc1"] if hevc else []
    if use_nvenc:
        return ["-c:v", "hevc_nvenc" if hevc else "h264_nvenc", "-preset", "p7", "-tune", "hq",
                "-rc", "vbr", "-cq", str(_NVENC_CQ[quality]), "-b:v", "0",
                "-multipass", "qres", "-rc-lookahead", "32", *tag, "-pix_fmt", "yuv420p"]
    # libx265's CRF scale runs about 4-6 higher than libx264's for the same look.
    crf = _X264_CRF[quality] + (4 if hevc else 0)
    return ["-c:v", "libx265" if hevc else "libx264", "-preset", "medium", "-crf", str(crf),
            *tag, "-pix_fmt", "yuv420p"]


def audio_map_args(n_audio: int, game: int, mic: int, mixed_only: bool = False) -> list[str]:
    """Build the audio part of an ffmpeg command.

    Two or more source tracks -> Mixed (game+mic), Game, Mic.
    One track -> that track only. None -> no audio.
    """
    if n_audio == 0:
        return ["-an"]
    if n_audio == 1:
        return ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
    game = min(max(game, 0), n_audio - 1)
    mic = min(max(mic, 0), n_audio - 1)
    if game == mic:
        mic = 1 if game == 0 else 0
    mix = f"[0:a:{game}][0:a:{mic}]amix=inputs=2:duration=longest:normalize=0[mix]"
    args = ["-filter_complex", mix, "-map", "[mix]"]
    if not mixed_only:
        args += ["-map", f"0:a:{game}", "-map", f"0:a:{mic}"]
        # MP4 shows track names from handler_name; MKV-aware tools read title.
        for i, name in enumerate(("Mixed", "Game", "Mic")):
            args += [f"-metadata:s:a:{i}", f"title={name}", f"-metadata:s:a:{i}", f"handler_name={name}"]
    return args + ["-c:a", "aac", "-b:a", "192k"]


# ---------------------------------------------------------------- vertical (9:16) framing

VERTICAL_SIZE = (1080, 1920)
VERTICAL_STYLES = ("focus45", "focus", "crop", "fit")
# Styles that blend a sharp and a blurred copy through a mask image.
MASKED_STYLES = ("focus",)
# focus45's sharp layer: 4:5 at the full 1080 width.
FOCUS45_SIZE = (1080, 1350)


def _even(x: float) -> int:
    return max(int(round(x / 2)) * 2, 2)


def vertical_crop(width: int, height: int, center_x: float = 0.5, zoom: float = 1.0,
                  aspect: float = 9 / 16) -> tuple[int, int, int, int]:
    """A tall window (w, h, x, y) of shape ``aspect`` (w/h) cut from a wide frame,
    centred on ``center_x`` (0-1). Full height unless zoomed."""
    zoom = min(max(zoom, 1.0), 2.0)
    h = _even(height / zoom)
    w = min(_even(h * aspect), _even(width))
    x = int(round(min(max(center_x * width - w / 2, 0), width - w)))
    y = (height - h) // 2
    return w, h, x, y


def focus_mask(path: Path, sharp: float = 0.55, size: tuple[int, int] = VERTICAL_SIZE) -> Path:
    """Grey mask for the focus-blur style: white (sharp) in an oval round the middle,
    fading to black (blurred) towards the top, bottom and corners."""
    import cv2
    import numpy as np

    if path.exists():
        return path
    w, h = size
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    # The sharp oval spans the full width and ``sharp`` of the height.
    d = np.sqrt(((xs - w / 2) / (w * 0.62)) ** 2 + ((ys - h / 2) / (h * max(sharp, 0.1) / 2)) ** 2)
    feather = 0.45
    a = np.clip((1 + feather - d) / feather, 0, 1)
    a = a * a * (3 - 2 * a)  # smoothstep: no visible edge where the blur starts
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), (a * 255).astype(np.uint8))
    return path


def vertical_filter(info: dict, style: str, center_x: float = 0.5, zoom: float = 1.0,
                    blur: float = 30.0, mask_input: int | None = None) -> str:
    """filter_complex turning input 0's video into a 1080x1920 ``[v]``.

    focus45: two layers. Behind: a 9:16 crop, blurred and darkened. In front: a sharp
             4:5 crop of the full height (scoreboard included), 1080x1350 in the middle.
    focus: tall crop filling the screen, sharp in the middle, blurred towards the edges
           (needs the mask image as input ``mask_input``).
    crop:  the tall crop alone.
    fit:   the whole wide frame in the middle, a blurred tall crop filling above and below.
    """
    W, H = VERTICAL_SIZE
    cw, ch, cx, cy = vertical_crop(info["width"], info["height"], center_x, zoom)
    tall = f"crop={cw}:{ch}:{cx}:{cy},scale={W}:{H}:flags=lanczos,setsar=1"
    # Blurring at quarter size is ~16x cheaper and looks the same once scaled back up.
    soft = f"scale={W // 4}:{H // 4},gblur=sigma={max(blur, 0.5) / 4:.2f},scale={W}:{H},setsar=1"
    if style == "crop":
        return f"[0:v]{tall}[v]"
    if style == "focus45":
        FW, FH = FOCUS45_SIZE
        fw, fh, fx, fy = vertical_crop(info["width"], info["height"], center_x, zoom, aspect=4 / 5)
        return (f"[0:v]split=2[fg][bg];"
                f"[bg]{tall},{soft},eq=brightness=-0.1[bgb];"
                f"[fg]crop={fw}:{fh}:{fx}:{fy},scale={FW}:{FH}:flags=lanczos,setsar=1[fgs];"
                f"[bgb][fgs]overlay=0:{(H - FH) // 2}[v]")
    if style == "fit":
        bw, bh, bx, by = vertical_crop(info["width"], info["height"], 0.5, 1.0)
        return (f"[0:v]split=2[fg][bg];"
                f"[bg]crop={bw}:{bh}:{bx}:{by},{soft},eq=brightness=-0.08[bgb];"
                f"[fg]scale={W}:-2:flags=lanczos,setsar=1[fgs];"
                f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2[v]")
    if mask_input is None:
        raise ValueError("focus style needs a mask input")
    return (f"[0:v]{tall},split=2[sharp][b];[b]{soft}[blurred];"
            f"[{mask_input}:v]format=gray,scale={W}:{H}[m];"
            f"[sharp][m]alphamerge[fade];"
            f"[blurred][fade]overlay=shortest=1:format=auto,format=yuv420p[v]")


def build_export_cmd(src: str, out: str, start: float, end: float, n_audio: int,
                     game: int = 0, mic: int = 1, encoder: str = "auto",
                     frame: dict | None = None, subtitles: str | None = None,
                     quality: str = "balanced") -> list[str]:
    """``frame`` set → 9:16 output: {info, style, center_x, zoom, blur, mask}.

    ``subtitles``: an ASS file name to burn in. Pass a bare name and run ffmpeg from its
    folder: Windows drive letters would need escaping inside the filter.
    """
    inputs = ["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src]
    video = ["-map", "0:v:0"]
    graph = ""
    if frame:
        mask_input = None
        if frame["style"] in MASKED_STYLES:
            inputs += ["-loop", "1", "-i", str(frame["mask"])]
            mask_input = 1
        graph = vertical_filter(frame["info"], frame["style"], frame.get("center_x", 0.5),
                                frame.get("zoom", 1.0), frame.get("blur", 30.0), mask_input)
    if subtitles:
        graph = (graph + ";[v]" if graph else "[0:v]") + f"subtitles='{subtitles}'[vs]"
        video = ["-filter_complex", graph, "-map", "[vs]"]
    elif graph:
        video = ["-filter_complex", graph, "-map", "[v]"]
    return [
        tool("ffmpeg"), "-hide_banner", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
        *inputs, *video, *audio_map_args(n_audio, game, mic),
        *video_encoder_args(encoder, quality),
        # The looped mask is endless; stop at the clip's end.
        *(["-t", f"{end - start:.3f}"] if frame else []),
        "-movflags", "+faststart", out,
    ]


def build_proxy_cmd(src: str, out: str, n_audio: int, game: int = 0, mic: int = 1,
                    encoder: str = "auto") -> list[str]:
    if encoder == "auto":
        encoder = "nvenc" if nvenc_available() else "x264"
    venc = (["-c:v", "h264_nvenc", "-preset", "p3", "-cq", "28", "-b:v", "0"] if encoder == "nvenc"
            else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28"])
    return [
        tool("ffmpeg"), "-hide_banner", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
        "-i", src, "-map", "0:v:0", *audio_map_args(n_audio, game, mic, mixed_only=True),
        "-vf", "scale=-2:720", "-pix_fmt", "yuv420p", *venc,
        # Keyframe every second keeps scrubbing in the browser snappy.
        "-g", "60", "-movflags", "+faststart", out,
    ]


_TIME_RE = re.compile(r"out_time_(?:us|ms)=(\d+)")


def run_ffmpeg(cmd: list[str], duration: float, progress: ProgressCb | None = None,
               cwd: str | Path | None = None) -> None:
    """Run ffmpeg with -progress pipe:1 and report 0..1 progress."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            creationflags=_NO_WINDOW, cwd=cwd)
    assert proc.stdout is not None
    for line in proc.stdout:
        m = _TIME_RE.search(line)
        if m and progress and duration > 0:
            progress(min(int(m.group(1)) / 1_000_000 / duration, 1.0))
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        raise MediaError(f"ffmpeg failed: {stderr.strip()[-800:]}")
    if progress:
        progress(1.0)


def render_proxy(src: str, out: str, info: dict, game: int, mic: int,
                 progress: ProgressCb | None = None) -> None:
    tmp = out + ".part.mp4"
    cmd = build_proxy_cmd(src, tmp, info["audio_streams"], game, mic)
    try:
        run_ffmpeg(cmd, info["duration"], progress)
    except MediaError:
        # NVENC can fail on odd inputs; retry on CPU once.
        cmd = build_proxy_cmd(src, tmp, info["audio_streams"], game, mic, encoder="x264")
        run_ffmpeg(cmd, info["duration"], progress)
    os.replace(tmp, out)


def export_clip(src: str, out: str, start: float, end: float, info: dict, game: int, mic: int,
                encoder: str = "auto", progress: ProgressCb | None = None,
                frame: dict | None = None, subtitles: Path | None = None, quality: str = "balanced") -> None:
    out = str(Path(out).resolve())
    sub_name = subtitles.name if subtitles else None
    cwd = subtitles.parent if subtitles else None
    cmd = build_export_cmd(src, out, start, end, info["audio_streams"], game, mic, encoder, frame, sub_name, quality)
    try:
        run_ffmpeg(cmd, end - start, progress, cwd)
    except MediaError:
        if encoder == "x264":
            raise
        cmd = build_export_cmd(src, out, start, end, info["audio_streams"], game, mic, "x264", frame, sub_name,
                               quality)
        run_ffmpeg(cmd, end - start, progress, cwd)


def build_concat_cmd(list_file: str, out: str, n_audio: int) -> list[str]:
    """Join parts rendered with identical settings, without re-encoding."""
    names = ("Mixed", "Game", "Mic") if n_audio >= 2 else ()
    meta = [arg for i, name in enumerate(names)
            for arg in (f"-metadata:s:a:{i}", f"title={name}", f"-metadata:s:a:{i}", f"handler_name={name}")]
    return [tool("ffmpeg"), "-hide_banner", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", list_file, "-map", "0", "-c", "copy", *meta, "-movflags", "+faststart", out]


def concat(parts: list[Path], out: str, n_audio: int) -> None:
    list_file = Path(out).with_suffix(".parts.txt")
    list_file.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), "utf-8")
    try:
        result = subprocess.run(build_concat_cmd(str(list_file), out, n_audio), capture_output=True,
                                text=True, creationflags=_NO_WINDOW)
        if result.returncode != 0:
            raise MediaError(f"Joining clips failed: {result.stderr.strip()[-800:]}")
    finally:
        list_file.unlink(missing_ok=True)


def grab_frame(src: str, t: float, width: int = 1280) -> bytes:
    """Return one frame at time t as JPEG bytes."""
    cmd = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", src,
           "-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "3", "-"]
    out = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)
    if out.returncode != 0 or not out.stdout:
        raise MediaError(f"Could not grab frame at {t:.1f}s")
    return out.stdout


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_") or "clip"


def mmss(t: float) -> str:
    t = max(int(t), 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}-{m:02d}-{s:02d}" if h else f"{m:02d}-{s:02d}"


def clip_filename(source: str | Path, event_type: str, time: float, vertical: bool = False) -> str:
    return f"{safe_name(Path(source).stem)}_{event_type}_{mmss(time)}{'_9x16' if vertical else ''}.mp4"
