from __future__ import annotations

import tempfile
import threading
import time
import unittest

from src.simulation_upload.job_manager import SimulationJobManager
from src.simulation_upload.workspace import RunWorkspaceManager


class JobManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = RunWorkspaceManager(self.temp.name).create()
        self.manager = SimulationJobManager()

    def wait_for(self, states: set[str], timeout: float = 2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = self.manager.poll(self.workspace)
            if record.status in states:
                return record
            time.sleep(0.01)
        self.fail(f"Job did not reach {states}")

    def test_completion_and_duplicate_launch_prevention(self) -> None:
        release = threading.Event()

        def operation():
            release.wait(1)
            return {"exit_code": 0}

        self.manager.submit(self.workspace, operation)
        self.wait_for({"running"})
        with self.assertRaises(RuntimeError):
            self.manager.submit(self.workspace, operation)
        release.set()
        record = self.wait_for({"completed"})
        self.assertEqual(record.result, {"exit_code": 0})

    def test_failure_is_recorded(self) -> None:
        def operation():
            raise RuntimeError("simulation failed")

        self.manager.submit(self.workspace, operation)
        record = self.wait_for({"failed"})
        self.assertIn("simulation failed", record.message)

    def test_timeout_marks_state_without_unsafe_kill(self) -> None:
        release = threading.Event()

        def operation():
            release.wait(1)
            return {}

        self.manager.submit(self.workspace, operation, timeout_seconds=0.01)
        self.wait_for({"running", "timed_out"})
        time.sleep(0.03)
        record = self.manager.poll(self.workspace)
        self.assertEqual(record.status, "timed_out")
        self.assertFalse(self.manager.cancel(self.workspace))
        release.set()

    def test_explicit_validation_states_are_persisted(self) -> None:
        for status in ("uploaded", "validating", "validation_failed"):
            record = self.manager.set_status(self.workspace, status)
            self.assertEqual(record.status, status)
        self.assertTrue(
            (self.workspace.metadata_dir / "job_status.json").is_file()
        )


if __name__ == "__main__":
    unittest.main()
