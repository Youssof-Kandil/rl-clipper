"""Stream downscaled frames out of ffmpeg at a fixed rate (no seeking)."""

from __future__ import annotations

import subprocess
from typing import Iterator

import numpy as np

from ..media import _NO_WINDOW, tool


def frame_size(src_w: int, src_h: int, width: int) -> tuple[int, int]:
    width = min(width, src_w) // 2 * 2
    height = max(int(round(src_h * width / src_w / 2)) * 2, 2)
    return width, height


def sample_frames(src: str, src_w: int, src_h: int, fps: float, width: int = 1280,
                  hwaccel: bool = True, start: float = 0.0,
                  end: float | None = None) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (timestamp_seconds, BGR frame) pairs, optionally only for [start, end)."""
    w, h = frame_size(src_w, src_h, width)
    cmd = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error"]
    if hwaccel:
        cmd += ["-hwaccel", "auto"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    if end is not None:
        cmd += ["-t", f"{max(end - start, 0.0):.3f}"]
    cmd += ["-i", src, "-map", "0:v:0", "-an", "-sn",
            "-vf", f"fps={fps},scale={w}:{h}", "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            bufsize=w * h * 3 * 4, creationflags=_NO_WINDOW)
    assert proc.stdout is not None
    size = w * h * 3
    i = 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield start + i / fps, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()
