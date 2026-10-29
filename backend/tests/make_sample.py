"""Generate a fake 'Rocket League' recording for end-to-end tests.

60 s, 1920x1080, a scoreboard at the top, point tags in the centre and two audio
tracks (game = 440 Hz tone, mic = 880 Hz tone).

    python tests/make_sample.py out.mkv
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.media import tool  # noqa: E402

FONT = "C\\:/Windows/Fonts/arialbd.ttf"

# (start, end, text) — tags drawn centre screen
TAGS = [
    (12.0, 14.5, "EPIC SAVE"), (12.0, 14.5, "+75"),
    (27.0, 29.5, "SAVE"), (27.0, 29.5, "+50"),
    (41.0, 43.5, "GOAL"), (41.0, 43.5, "+100"),
    (50.0, 52.5, "CLEAR"), (50.0, 52.5, "+20"),
]
# Expected events, used by the tests.
EXPECTED = [(12.0, "epic_save"), (27.0, "save"), (41.0, "goal"), (55.0, "goal_other")]


def build_filter() -> str:
    parts = ["[0:v]drawbox=x=820:y=0:w=280:h=80:color=0x202020@0.9:t=fill"]
    # Scoreboard: blue score, clock, orange score.  Blue scores at 41 s, orange at 55 s.
    parts.append(f"drawtext=fontfile='{FONT}':text='5\\:00':fontcolor=white:fontsize=44:x=910:y=18")
    for start, end, value in ((0, 41, 0), (41, 99, 1)):
        parts.append(f"drawtext=fontfile='{FONT}':text='{value}':fontcolor=white:fontsize=48:x=845:y=16"
                     f":enable='between(t,{start},{end})'")
    for start, end, value in ((0, 55, 0), (55, 99, 1)):
        parts.append(f"drawtext=fontfile='{FONT}':text='{value}':fontcolor=white:fontsize=48:x=1050:y=16"
                     f":enable='between(t,{start},{end})'")
    for i, (start, end, text) in enumerate(TAGS):
        # Same place and size as the real HUD: just under the scoreboard.
        y = 160 if not text.startswith("+") else 205
        size = 40 if not text.startswith("+") else 30
        parts.append(f"drawtext=fontfile='{FONT}':text='{text}':fontcolor=white:fontsize={size}"
                     f":borderw=4:bordercolor=black:x=(w-text_w)/2:y={y}:enable='between(t,{start},{end})'")
    return ",".join(parts) + "[v]"


def main(out: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write(build_filter())
        script = fh.name
    cmd = [tool("ffmpeg"), "-hide_banner", "-y", "-loglevel", "error",
           "-f", "lavfi", "-i", "gradients=s=1920x1080:r=60:d=60:c0=0x335577:c1=0x557733",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
           "-f", "lavfi", "-i", "sine=frequency=880:duration=60",
           "-/filter_complex", script,
           "-map", "[v]", "-map", "1:a", "-map", "2:a",
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-metadata:s:a:0", "title=Game", "-metadata:s:a:1", "title=Mic", out]
    subprocess.run(cmd, check=True)
    Path(script).unlink(missing_ok=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sample.mkv")
