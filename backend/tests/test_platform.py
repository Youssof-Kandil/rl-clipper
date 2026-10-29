"""Cross-platform bits: rrrocket builds, replay folders, the system check."""

import pytest
from fastapi.testclient import TestClient

from app import main, media, replays


@pytest.mark.parametrize("plat,machine,suffix", [
    ("win32", "AMD64", "x86_64-pc-windows-msvc.zip"),
    ("linux", "x86_64", "x86_64-unknown-linux-musl.tar.gz"),
    ("darwin", "x86_64", "x86_64-apple-darwin.tar.gz"),
    ("darwin", "arm64", "aarch64-apple-darwin.tar.gz"),
    ("linux", "aarch64", None),  # no build: replays are skipped, OCR still works
])
def test_rrrocket_url_per_platform(monkeypatch, plat, machine, suffix):
    monkeypatch.setattr(replays.sys, "platform", plat)
    monkeypatch.setattr(replays.platform, "machine", lambda: machine)
    url = replays.rrrocket_url()
    assert (url is None) if suffix is None else url.endswith(f"rrrocket-{replays.RRROCKET_VERSION}-{suffix}")


def test_demo_dirs_include_windows_and_proton(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    dirs = [d.relative_to(tmp_path).as_posix() for d in replays._demo_dirs()]
    assert "Documents/My Games/Rocket League/TAGame/Demos" in dirs
    assert any(d.startswith(".local/share/Steam/steamapps/compatdata/252950/") for d in dirs)


def test_demos_dir_found_under_proton(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    proton = [d for d in replays._demo_dirs() if "compatdata" in d.as_posix()][0]
    proton.mkdir(parents=True)
    assert replays.demos_dir({}) == proton


def test_small_falls_back_to_h264_without_libx265(monkeypatch):
    monkeypatch.setattr(media, "has_encoder", lambda name: False)
    args = media.video_encoder_args("x264", "small")
    assert args[args.index("-c:v") + 1] == "libx264" and "-tag:v" not in args


def test_health_reports_capabilities():
    data = TestClient(main.app).get("/api/health").json()
    for key in ("ok", "ffmpeg", "nvenc", "captions_gpu", "caption_model_ready", "rrrocket", "demos_dir", "picker"):
        assert key in data
