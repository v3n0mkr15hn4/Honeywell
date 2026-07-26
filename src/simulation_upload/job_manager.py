"""Single-concurrency in-process job manager for dashboard MCP simulations."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .workspace import RunWorkspace


JOB_STATES = frozenset(
    {
        "uploaded",
        "validating",
        "validation_failed",
        "ready",
        "queued",
        "running",
        "completed",
        "failed",
        "timed_out",
        "cancelled",
    }
)
TERMINAL_STATES = frozenset(
    {"validation_failed", "completed", "failed", "timed_out", "cancelled"}
)


@dataclass
class JobRecord:
    run_id: str
    status: str
    created_utc: str
    updated_utc: str
    started_monotonic: float | None = None
    timeout_seconds: float = 600.0
    message: str = ""
    result: dict[str, Any] | None = None


class SimulationJobManager:
    """Runs at most one simulation in this application process.

    A running MCP simulation cannot be force-killed safely because the official
    server does not expose cancellation. A timeout marks the job and retains
    the concurrency lock until the remote call actually returns.
    """

    _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eplus-mcp")
    _lock = threading.RLock()
    _active_run_id: str | None = None

    def __init__(self) -> None:
        self._records: dict[str, JobRecord] = {}
        self._futures: dict[str, Future[dict[str, Any]]] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _status_path(workspace: RunWorkspace) -> Path:
        return workspace.metadata_dir / "job_status.json"

    def _persist(self, workspace: RunWorkspace, record: JobRecord) -> None:
        self._status_path(workspace).write_text(
            json.dumps(asdict(record), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def set_status(
        self, workspace: RunWorkspace, status: str, message: str = ""
    ) -> JobRecord:
        if status not in JOB_STATES:
            raise ValueError(f"Unknown job status: {status}")
        with self._lock:
            record = self._records.get(workspace.run_id)
            if record is None:
                record = JobRecord(
                    run_id=workspace.run_id,
                    status=status,
                    created_utc=self._now(),
                    updated_utc=self._now(),
                    message=message,
                )
                self._records[workspace.run_id] = record
            else:
                record.status = status
                record.updated_utc = self._now()
                record.message = message
            self._persist(workspace, record)
            return record

    def submit(
        self,
        workspace: RunWorkspace,
        operation: Callable[[], dict[str, Any]],
        *,
        timeout_seconds: float = 600.0,
    ) -> JobRecord:
        with self._lock:
            existing = self._records.get(workspace.run_id)
            if existing and existing.status in {"queued", "running"}:
                raise RuntimeError("This run is already queued or running")
            if self.__class__._active_run_id is not None:
                raise RuntimeError(
                    "Another EnergyPlus simulation is already active"
                )
            self.__class__._active_run_id = workspace.run_id
            record = JobRecord(
                run_id=workspace.run_id,
                status="queued",
                created_utc=self._now(),
                updated_utc=self._now(),
                timeout_seconds=timeout_seconds,
            )
            self._records[workspace.run_id] = record
            self._persist(workspace, record)

            def worker() -> dict[str, Any]:
                with self._lock:
                    record.status = "running"
                    record.started_monotonic = time.monotonic()
                    record.updated_utc = self._now()
                    self._persist(workspace, record)
                try:
                    value = operation()
                    with self._lock:
                        if record.status != "timed_out":
                            record.status = "completed"
                            record.result = value
                            record.message = ""
                    return value
                except Exception as exc:
                    with self._lock:
                        if record.status != "timed_out":
                            record.status = "failed"
                            record.message = str(exc)[:500]
                    raise
                finally:
                    with self._lock:
                        record.updated_utc = self._now()
                        self._persist(workspace, record)
                        self.__class__._active_run_id = None

            self._futures[workspace.run_id] = self._executor.submit(worker)
            return record

    def poll(self, workspace: RunWorkspace) -> JobRecord:
        with self._lock:
            record = self._records.get(workspace.run_id)
            if record is None:
                status_path = self._status_path(workspace)
                if not status_path.exists():
                    return self.set_status(workspace, "uploaded")
                record = JobRecord(**json.loads(status_path.read_text(encoding="utf-8")))
                self._records[workspace.run_id] = record
            if (
                record.status == "running"
                and record.started_monotonic is not None
                and time.monotonic() - record.started_monotonic
                > record.timeout_seconds
            ):
                record.status = "timed_out"
                record.updated_utc = self._now()
                record.message = (
                    "Client timeout elapsed. The concurrency lock remains held "
                    "until the MCP call returns."
                )
                self._persist(workspace, record)
            return record

    def cancel(self, workspace: RunWorkspace) -> bool:
        """Cancel only work that has not started; never kill a running simulation."""
        with self._lock:
            record = self.poll(workspace)
            future = self._futures.get(workspace.run_id)
            if record.status != "queued" or future is None or not future.cancel():
                return False
            record.status = "cancelled"
            record.updated_utc = self._now()
            self.__class__._active_run_id = None
            self._persist(workspace, record)
            return True

    def mark_stale_jobs(
        self, workspace: RunWorkspace, *, stale_after_seconds: float
    ) -> JobRecord:
        record = self.poll(workspace)
        if record.status not in {"queued", "running"}:
            return record
        updated = datetime.fromisoformat(record.updated_utc)
        age = (datetime.now(timezone.utc) - updated).total_seconds()
        if age > stale_after_seconds and workspace.run_id not in self._futures:
            record.status = "failed"
            record.message = "Stale job recovered after application restart"
            record.updated_utc = self._now()
            self._persist(workspace, record)
        return record
