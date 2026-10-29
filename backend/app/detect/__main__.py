"""CLI: python -m app.detect <video> [--debug DIR]  — print detected events."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from ..config import load_settings
from ..media import probe
from .pipeline import analyze


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect goals/saves/epic saves in a Rocket League recording")
    parser.add_argument("video")
    parser.add_argument("--debug", type=Path, help="save every OCR'd tag crop here")
    parser.add_argument("--fps", type=float, help="override sample fps")
    args = parser.parse_args()
    # OCR can return CJK look-alikes; don't crash on a cp1252 Windows console.
    sys.stdout.reconfigure(errors="replace")

    settings = load_settings()
    if args.fps:
        settings["sample_fps"] = args.fps
    info = probe(args.video)
    print(f"{args.video}: {info['width']}x{info['height']} @ {info['fps']:.2f}fps, "
          f"{info['duration']:.0f}s, {info['audio_streams']} audio track(s)")

    started = time.time()

    def progress(p: float, msg: str) -> None:
        sys.stdout.write(f"\r{p * 100:5.1f}%  {msg}      ")
        sys.stdout.flush()

    events = analyze(args.video, info, settings, progress, debug_dir=args.debug)
    print(f"\n\nDone in {time.time() - started:.0f}s\n")
    for e in events:
        m, s = divmod(int(e.time), 60)
        team = f" ({e.team})" if e.team else ""
        print(f"  {m:3d}:{s:02d}  {e.type:<11}{team:<9} conf={e.confidence:.2f}  src={e.source:<15} {e.text}")


if __name__ == "__main__":
    main()
