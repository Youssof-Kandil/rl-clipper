"""Tiny in-process background job runner with progress reporting."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, fields
from typing import Callable


@dataclass
class Job:
    id: str
    kind: str
    project_id: str
    status: str = "queued"  # queued | running | done | error | cancelled
    progress: float = 0.0
    message: str = ""
    error: str = ""
    result: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def update(self, progress: float | None = None, message: str | None = None) -> None:
        if progress is not None:
            self.progress = max(0.0, min(progress, 1.0))
        if message is not None:
            self.message = message

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def to_dict(self) -> dict:
        # Not asdict(): it would try to deep-copy the threading.Event.
        return {f.name: getattr(self, f.name) for f in fields(self) if not f.name.startswith("_")}


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="rlc-job")


def submit(kind: str, project_id: str, fn: Callable[[Job], dict | None]) -> Job:
    job = Job(uuid.uuid4().hex[:12], kind, project_id)
    with _lock:
        _jobs[job.id] = job

    def run() -> None:
        if job.cancelled:
            job.status = "cancelled"
            return
        job.status = "running"
        try:
            job.result = fn(job) or {}
            job.status = "cancelled" if job.cancelled else "done"
            job.progress = 1.0 if job.status == "done" else job.progress
        except InterruptedError:
            job.status = "cancelled"
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            job.status = "error"
            job.error = f"{exc}"
            traceback.print_exc()

    _pool.submit(run)
    return job


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def cancel(job_id: str) -> bool:
    job = _jobs.get(job_id)
    if job is None:
        return False
    job._cancel.set()
    return True


def active_for(project_id: str) -> list[Job]:
    return [j for j in _jobs.values() if j.project_id == project_id and j.status in ("queued", "running")]
