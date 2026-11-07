"""Stream downscaled frames out of ffmpeg at a fixed rate (no seeking)."""

from __future__ import annotations

import queue
import subprocess
import threading
from typing import Iterator

import numpy as np

from ..media import _NO_WINDOW, nvenc_available, tool

# Frames decoded ahead while the caller is busy with OCR.
_AHEAD = 16


def frame_size(src_w: int, src_h: int, width: int) -> tuple[int, int]:
    width = min(width, src_w) // 2 * 2
    height = max(int(round(src_h * width / src_w / 2)) * 2, 2)
    return width, height


def build_cmd(src: str, w: int, h: int, fps: float, decode: str, start: float = 0.0,
              end: float | None = None) -> list[str]:
    """``decode``: "cuda" keeps frames on the GPU until ``fps`` has dropped the ones not
    needed, so only those get copied back (the same pixels as "auto", far less copying);
    "auto" lets ffmpeg pick a hardware decoder; "cpu" decodes in software."""
    cmd = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error"]
    vf = f"fps={fps},scale={w}:{h}"
    if decode == "cuda":
        cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        vf = f"fps={fps},hwdownload,format=nv12,scale={w}:{h}"
    elif decode == "auto":
        cmd += ["-hwaccel", "auto"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    if end is not None:
        cmd += ["-t", f"{max(end - start, 0.0):.3f}"]
    return cmd + ["-i", src, "-map", "0:v:0", "-an", "-sn", "-vf", vf, "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]


def sample_frames(src: str, src_w: int, src_h: int, fps: float, width: int = 1280,
                  hwaccel: bool = True, start: float = 0.0,
                  end: float | None = None) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (timestamp_seconds, BGR frame) pairs, optionally only for [start, end)."""
    w, h = frame_size(src_w, src_h, width)
    modes = ((["cuda"] if nvenc_available() else []) + ["auto"]) if hwaccel else ["cpu"]
    for k, mode in enumerate(modes):
        frames = _read(build_cmd(src, w, h, fps, mode, start, end), w * h * 3)
        try:
            first = next(frames)
        except StopIteration:
            continue  # nothing decoded this way (say, no CUDA for this codec): try the next
        except _Failed:
            if k == len(modes) - 1:
                return
            continue
        try:
            yield start, np.frombuffer(first, np.uint8).reshape(h, w, 3)
            for i, buf in enumerate(frames, 1):
                yield start + i / fps, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        except _Failed:
            pass  # as before: a decoder error part way through ends the stream
        finally:
            frames.close()
        return


class _Failed(Exception):
    pass


def _read(cmd: list[str], size: int) -> Iterator[bytes]:
    """Raw frames from ffmpeg, read on a thread so decoding runs while the caller works.

    Raises _Failed if ffmpeg exits with an error before producing a whole frame."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            bufsize=size * 4, creationflags=_NO_WINDOW)
    assert proc.stdout is not None
    q: queue.Queue[bytes | None] = queue.Queue(maxsize=_AHEAD)
    stop = threading.Event()

    def pump() -> None:
        try:
            while not stop.is_set():
                try:
                    buf = proc.stdout.read(size)
                except (OSError, ValueError):  # the pipe was closed under us: stopping
                    break
                if len(buf) < size:
                    break
                while not stop.is_set():
                    try:
                        q.put(buf, timeout=0.2)
                        break
                    except queue.Full:
                        continue
        finally:
            while not stop.is_set():
                try:
                    q.put(None, timeout=0.2)
                    break
                except queue.Full:
                    continue

    reader = threading.Thread(target=pump, name="rlc-frames", daemon=True)
    reader.start()
    produced = False
    try:
        while (buf := q.get()) is not None:
            produced = True
            yield buf
        if not produced and proc.wait() != 0:
            raise _Failed()
    finally:
        stop.set()
        proc.kill()
        proc.stdout.close()
        proc.wait()
        reader.join(timeout=2)
