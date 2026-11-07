import hashlib
import subprocess
import threading

import pytest

from app import media
from app.detect import sampler


def _ffmpeg_ok() -> bool:
    try:
        media.tool("ffmpeg")
        return True
    except media.MediaError:
        return False


needs_ffmpeg = pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """6 s of 60 fps moving test pattern, HEVC like OBS recordings (H.264 if no HEVC encoder)."""
    if not _ffmpeg_ok():
        pytest.skip("ffmpeg not installed")
    out = tmp_path_factory.mktemp("sampler") / "clip.mp4"
    for codec in ("libx265", "libx264"):
        r = subprocess.run([media.tool("ffmpeg"), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=size=1920x1080:rate=60:duration=6", "-c:v", codec, "-pix_fmt", "yuv420p",
                            str(out)], capture_output=True)
        if r.returncode == 0:
            return str(out)
    pytest.skip("no HEVC/H.264 encoder")


def _hashes(frames):
    return [(round(t, 3), hashlib.md5(f.tobytes()).hexdigest()) for t, f in frames]


def test_cuda_thins_on_the_gpu_before_copying():
    cuda = sampler.build_cmd("in.mp4", 1280, 720, 2.0, "cuda", start=5, end=9)
    assert cuda[cuda.index("-hwaccel") + 1] == "cuda" and "-hwaccel_output_format" in cuda
    assert cuda[cuda.index("-vf") + 1] == "fps=2.0,hwdownload,format=nv12,scale=1280:720"
    assert cuda[cuda.index("-ss") + 1] == "5.000" and cuda[cuda.index("-t") + 1] == "4.000"
    auto = sampler.build_cmd("in.mp4", 1280, 720, 2.0, "auto")
    assert auto[auto.index("-hwaccel") + 1] == "auto" and auto[auto.index("-vf") + 1] == "fps=2.0,scale=1280:720"
    assert "-hwaccel" not in sampler.build_cmd("in.mp4", 1280, 720, 2.0, "cpu")


@needs_ffmpeg
def test_every_way_gives_the_same_frames(clip, monkeypatch):
    """The scan's accuracy rests on this: the faster path must hand OCR the same pixels."""
    expected = _hashes(sampler.sample_frames(clip, 1920, 1080, 2.0, 1280, hwaccel=False, start=1.0, end=5.0))
    assert len(expected) == 8 and expected[0][0] == 1.0 and expected[-1][0] == 4.5

    def only(mode):
        real = sampler.build_cmd
        monkeypatch.setattr(sampler, "build_cmd", lambda *a, **k: real(*a[:4], mode, *a[5:], **k))
        try:
            return _hashes(sampler.sample_frames(clip, 1920, 1080, 2.0, 1280, start=1.0, end=5.0))
        finally:
            monkeypatch.setattr(sampler, "build_cmd", real)

    assert only("auto") == expected
    if media.nvenc_available():
        assert only("cuda") == expected


@needs_ffmpeg
def test_falls_back_when_the_gpu_path_fails(clip, monkeypatch):
    real = sampler.build_cmd
    tried = []

    def broken_cuda(src, w, h, fps, decode, *a, **k):
        tried.append(decode)
        cmd = real(src, w, h, fps, decode, *a, **k)
        return [*cmd[:-1], "-c:v", "no_such_encoder", "-"] if decode == "cuda" else cmd

    monkeypatch.setattr(sampler, "nvenc_available", lambda: True)
    monkeypatch.setattr(sampler, "build_cmd", broken_cuda)
    frames = list(sampler.sample_frames(clip, 1920, 1080, 1.0, 640))
    assert tried == ["cuda", "auto"] and len(frames) == 6


@needs_ffmpeg
def test_stopping_early_ends_ffmpeg_and_the_reader(clip):
    before = {t.ident for t in threading.enumerate()}
    gen = sampler.sample_frames(clip, 1920, 1080, 10.0, 640)
    next(gen)
    gen.close()
    left = [t for t in threading.enumerate() if t.name == "rlc-frames" and t.ident not in before]
    assert not any(t.is_alive() for t in left)
