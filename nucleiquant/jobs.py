"""Background jobs (survey, crops, training, batch) with progress reporting.

One worker thread: jobs share the GPU and the project files, so they run
one after the other.
"""

import itertools
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

__all__ = ["JobManager", "Cancelled"]


class Cancelled(Exception):
    pass


class Job:
    def __init__(self, job_id, kind, title):
        self.id = job_id
        self.kind = kind
        self.title = title
        self.status = "queued"
        self.progress = 0.0
        self.message = ""
        self.result = None
        self.error = None
        self.started = None
        self.finished = None
        self.cancel_requested = False

    def update(self, progress=None, message=None):
        if self.cancel_requested:
            raise Cancelled()
        if progress is not None:
            self.progress = float(max(0.0, min(1.0, progress)))
        if message is not None:
            self.message = message

    def to_dict(self):
        eta = None
        if self.status == "running" and self.started and self.progress > 0.02:
            elapsed = time.time() - self.started
            eta = elapsed * (1 - self.progress) / self.progress
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "status": self.status,
            "progress": self.progress, "message": self.message, "error": self.error,
            "result": self.result, "eta_seconds": eta,
            "elapsed_seconds": (time.time() - self.started) if self.started and not self.finished else
            (self.finished - self.started if self.started and self.finished else None),
        }


class JobManager:
    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._jobs = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def submit(self, kind, title, fn, *args, **kwargs):
        """Run fn(job, *args, **kwargs) in the background; returns the job dict."""
        with self._lock:
            job = Job(str(next(self._ids)), kind, title)
            self._jobs[job.id] = job

        def run():
            if job.cancel_requested:
                job.status = "cancelled"
                return
            job.status = "running"
            job.started = time.time()
            try:
                job.result = fn(job, *args, **kwargs)
                job.progress = 1.0
                job.status = "done"
            except Cancelled:
                job.status = "cancelled"
            except Exception as e:
                job.status = "error"
                job.error = str(e) or e.__class__.__name__
                traceback.print_exc()
            finally:
                job.finished = time.time()

        self._pool.submit(run)
        return job.to_dict()

    def get(self, job_id):
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def cancel(self, job_id):
        job = self._jobs.get(job_id)
        if job and job.status in ("queued", "running"):
            job.cancel_requested = True
            if job.status == "queued":
                job.status = "cancelled"
        return job.to_dict() if job else None

    def active(self):
        """The running or queued jobs, oldest first."""
        return [j.to_dict() for j in self._jobs.values() if j.status in ("queued", "running")]
