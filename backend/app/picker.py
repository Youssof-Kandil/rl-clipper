"""Native "Open file" / "Choose folder" dialogs, so the browser UI can get real paths.

A browser file input only hands over the file's contents (or a fake path), never
where it lives. The server runs on the same machine, so it opens the dialog itself.
The dialog runs in its own Python process: Tk wants the main thread, and a dialog
left open must not hold up the server.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SCRIPT = r"""
import sys, tkinter as tk
from tkinter import filedialog
mode, start = sys.argv[1], sys.argv[2] or None
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
if mode == "folder":
    path = filedialog.askdirectory(parent=root, title="Choose where exports go", initialdir=start, mustexist=False)
else:
    path = filedialog.askopenfilename(
        parent=root, title="Choose a recording", initialdir=start,
        filetypes=[("Videos", "*.mkv *.mp4 *.mov *.flv *.ts"), ("All files", "*.*")])
sys.stdout.write(path or "")
"""

_last_dir: str | None = None


def _videos_dir() -> str:
    videos = Path(os.environ.get("USERPROFILE", Path.home())) / "Videos"
    return str(videos) if videos.is_dir() else ""


def available() -> bool:
    """Tk is installed and there's a desktop to show a dialog on."""
    import importlib.util

    if importlib.util.find_spec("tkinter") is None:
        return False
    return sys.platform in ("win32", "darwin") or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


class PickerUnavailable(RuntimeError):
    """No desktop dialog here: Tk isn't installed, or there's no display (a server)."""


def _ask(mode: str, start: str) -> str | None:
    out = subprocess.run([sys.executable, "-c", _SCRIPT, mode, start],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise PickerUnavailable("No file dialog available on this machine (needs a desktop and Tk). "
                                "Paste the path instead.")
    path = out.stdout.strip()
    return os.path.normpath(path) if path else None


def choose_video() -> str | None:
    """Show the file dialog and wait; the chosen path, or None if it was cancelled."""
    global _last_dir
    start = _last_dir if _last_dir and os.path.isdir(_last_dir) else _videos_dir()
    path = _ask("file", start)
    if path:
        _last_dir = os.path.dirname(path)
    return path


def choose_folder(current: str = "") -> str | None:
    """Show the folder dialog (starting at ``current`` if it exists); None if cancelled."""
    return _ask("folder", current if current and os.path.isdir(current) else _videos_dir())
