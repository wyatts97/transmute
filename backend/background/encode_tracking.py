"""Live progress and cancellation for jobs running on the advanced options path.

Workers run as threads in the API process, so a process-local registry of
cancel events is enough for ``POST /api/jobs/{id}/cancel`` to reach a running
encode.
"""
from __future__ import annotations

import logging
import threading
import time

from encoding.ffmpeg_runner import Progress


logger = logging.getLogger(__name__)


class RunningJobCancels:
    """Maps running job IDs to the event that stops their encode."""

    def __init__(self) -> None:
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def register(self, job_id: str) -> threading.Event:
        event = threading.Event()
        with self._lock:
            self._events[job_id] = event
        return event

    def unregister(self, job_id: str) -> None:
        with self._lock:
            self._events.pop(job_id, None)

    def request_cancel(self, job_id: str) -> bool:
        """Signal a running job to stop. False if the job can't be cancelled."""
        with self._lock:
            event = self._events.get(job_id)
        if event is None:
            return False
        event.set()
        return True


running_job_cancels = RunningJobCancels()


class ProgressReporter:
    """Write progress to a job row at most about once per second.

    A jump of five points or the final 100% is always written so short
    encodes still show movement.
    """

    def __init__(self, job_db, job_id: str, min_interval_s: float = 1.0) -> None:
        self._job_db = job_db
        self._job_id = job_id
        self._min_interval_s = min_interval_s
        self._last_write = 0.0
        self._last_percent = -1

    def __call__(self, progress: Progress) -> None:
        now = time.monotonic()
        due = (
            progress.percent >= 100
            or progress.percent - self._last_percent >= 5
            or now - self._last_write >= self._min_interval_s
        )
        if not due or progress.percent == self._last_percent:
            return
        try:
            self._job_db.update_progress(
                self._job_id, progress.percent,
                eta_seconds=progress.eta_seconds, speed=progress.speed,
            )
        except Exception:
            # Progress is advisory; never fail an encode because of it.
            logger.exception("Failed to record progress for job %s", self._job_id)
            return
        self._last_write = now
        self._last_percent = progress.percent


def wait_for_job_to_stop(job_db, job_id: str, user_id: str, timeout_s: float = 5.0) -> dict | None:
    """Poll until a cancelled job leaves ``running`` (or the timeout passes)."""
    deadline = time.monotonic() + timeout_s
    job = job_db.get_job(job_id, user_id=user_id)
    while job is not None and job.get("status") == "running" and time.monotonic() < deadline:
        time.sleep(0.1)
        job = job_db.get_job(job_id, user_id=user_id)
    return job
