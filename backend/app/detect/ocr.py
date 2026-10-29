"""Thin wrapper around RapidOCR so the engine loads once and lazily."""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

_engine = None
_lock = threading.Lock()


@dataclass
class TextBox:
    text: str
    score: float
    x: float  # centre x in pixels of the crop
    y: float


def _get_engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            # By default the detector upscales every image so its short side is 736 px,
            # which makes small HUD crops ~6x slower to read with no gain in accuracy.
            _engine = RapidOCR(det_limit_side_len=160)
        return _engine


def read_text(img: np.ndarray) -> list[TextBox]:
    engine = _get_engine()
    # Tags and scores are always horizontal, so skip the rotation classifier.
    result, _ = engine(img, use_cls=False)
    boxes: list[TextBox] = []
    for box, text, score in result or []:
        pts = np.asarray(box, dtype=float)
        boxes.append(TextBox(str(text), float(score), float(pts[:, 0].mean()), float(pts[:, 1].mean())))
    return boxes


def read_line(img: np.ndarray) -> tuple[str, float] | None:
    """Recognise a crop that holds a single line of text (no text detection pass)."""
    result, _ = _get_engine()(img, use_det=False, use_cls=False)
    if not result:
        return None
    text, score = result[0][0], result[0][1]
    return str(text), float(score)


def crop(frame: np.ndarray, roi: list[float]) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = roi
    return frame[int(y0 * h):max(int(y1 * h), int(y0 * h) + 1), int(x0 * w):max(int(x1 * w), int(x0 * w) + 1)]
