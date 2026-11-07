#!/usr/bin/env python3
"""Cost-model and behaviour tests for the project scope refresh.

One refresh must list the task directory once, not once per session. These
tests pin both the cost model and the behaviour that the index must preserve.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from cli_topsailai import project_scope
from cli_topsailai.process_liveness import ProcessState


class MockCompletedProcess:
    """Minimal mock for subprocess.CompletedProcess."""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _make_task_dir(root, session_ids, pid=999999):
    """Create a task directory holding one stdout file per session."""
    task = Path(root) / "workspace" / "task"
    task.mkdir(parents=True, exist_ok=True)
    for session_id in session_ids:
        (task / f"{session_id}.{pid}.session.stdout").touch()
    return task


class CountingListdir:
    """Wrap os.listdir so the number of directory listings is observable."""

    def __init__(self):
        self.calls = []
        self._real = os.listdir

    def __call__(self, path="."):
        self.calls.append(path)
        return self._real(path)


class TestRefreshScanCost(unittest.TestCase):
    """The refresh must pay one directory listing, not one per session."""

    def test_refresh_lists_task_directory_once(self):
        """A full refresh lists the task directory exactly once."""
        with tempfile.TemporaryDirectory() as tmp:
            session_ids = [f"sid{i}" for i in range(12)]
            _make_task_dir(tmp, session_ids)
            sessions = [
                {"session_id": sid, "create_time": "2026-07-06T09:00:00"}
                for sid in session_ids
            ]
            counter = CountingListdir()
            with patch.object(project_scope.os, "listdir", side_effect=counter):
                with patch.object(
                    project_scope.subprocess,
                    "run",
                    return_value=MockCompletedProcess(stdout=json.dumps(sessions)),
                ):
                    with patch.object(
                        project_scope, "get_topsailai_home", return_value=tmp
                    ):
                        entries = project_scope.build_project_list(limit=10)

            self.assertEqual(len(entries), 12)
            self.assertEqual(
                len(counter.calls),
                1,
                f"expected 1 directory listing, got {len(counter.calls)}",
            )

    def test_enrich_running_status_lists_once(self):
        """Enriching N entries lists the task directory exactly once."""
        with tempfile.TemporaryDirectory() as tmp:
            session_ids = [f"sid{i}" for i in range(12)]
            _make_task_dir(tmp, session_ids)
            entries = [{"session_id": sid} for sid in session_ids]
            counter = CountingListdir()
            with patch.object(project_scope.os, "listdir", side_effect=counter):
                with patch.object(
                    project_scope, "get_topsailai_home", return_value=tmp
                ):
                    project_scope._enrich_running_status(entries)

            self.assertEqual(
                len(counter.calls),
                1,
                f"expected 1 directory listing, got {len(counter.calls)}",
            )

    def test_resolve_session_mtime_uses_index(self):
        """A prebuilt index removes the directory listing entirely."""
        with tempfile.TemporaryDirectory() as tmp:
            task = _make_task_dir(tmp, ["sid0"])
            index = project_scope._build_stdout_index(str(task))
            counter = CountingListdir()
            with patch.object(project_scope.os, "listdir", side_effect=counter):
                mtime = project_scope._resolve_session_mtime(
                    str(task), "sid0", index=index
                )

            self.assertIsNotNone(mtime)
            self.assertEqual(counter.calls, [])

    def test_index_lookup_does_not_scan_every_session(self):
        """A per-session lookup must not iterate over every indexed session.

        Keying the index by parsed identity forced a scan over all keys per
        lookup, which made a refresh O(N^2) in the number of sessions. The index
        is keyed by display identity so one lookup is one dictionary access.
        """
        with tempfile.TemporaryDirectory() as tmp:
            session_ids = [f"sid{i}" for i in range(50)]
            task = _make_task_dir(tmp, session_ids)
            index = project_scope._build_stdout_index(str(task))

            class CountingIndex(dict):
                """Count key reads so a full scan is observable."""

                def __init__(self, source):
                    super().__init__(source)
                    self.reads = 0

                def get(self, key, default=None):
                    self.reads += 1
                    return super().get(key, default)

                def items(self):
                    self.reads += len(self)
                    return super().items()

                def keys(self):
                    self.reads += len(self)
                    return super().keys()

                def values(self):
                    self.reads += len(self)
                    return super().values()

            counting = CountingIndex(index)
            candidates = project_scope._index_candidates(counting, "sid7")

            self.assertEqual(len(candidates), 1)
            self.assertEqual(counting.reads, 1)


class TestIndexBehaviourPreserved(unittest.TestCase):
    """The index must not change any observable behaviour."""

    def test_temp_sentinel_resolves_from_index(self):
        """A temporary session stdout file resolves for the display sentinel."""
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / "workspace" / "task"
            task.mkdir(parents=True)
            (task / "topsailai.123.session.stdout").touch()
            index = project_scope._build_stdout_index(str(task))

            self.assertIsNotNone(
                project_scope._resolve_session_mtime(
                    str(task), "topsailai", index=index
                )
            )

    def test_index_preserves_listing_order(self):
        """Candidates keep the directory listing order, which decides ties."""
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / "workspace" / "task"
            task.mkdir(parents=True)
            for pid in (111, 222, 333):
                (task / f"sid0.{pid}.session.stdout").touch()
            index = project_scope._build_stdout_index(str(task))

            expected = [
                entry
                for entry in os.listdir(str(task))
                if entry.endswith(".session.stdout")
            ]
            actual = [os.path.basename(path) for path, _ in index["sid0"]]
            self.assertEqual(actual, expected)

    def test_non_file_entry_is_ignored(self):
        """A directory named like a stdout file is not a candidate."""
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / "workspace" / "task"
            task.mkdir(parents=True)
            (task / "sid0.111.session.stdout").mkdir()
            index = project_scope._build_stdout_index(str(task))

            self.assertEqual(index, {})

    def test_unreadable_mtime_is_skipped(self):
        """A candidate whose mtime cannot be read is skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / "workspace" / "task"
            task.mkdir(parents=True)
            (task / "sid0.111.session.stdout").touch()
            real_getmtime = os.path.getmtime

            def fake_getmtime(path):
                if str(path).endswith("sid0.111.session.stdout"):
                    raise OSError("unreadable")
                return real_getmtime(path)

            with patch.object(
                project_scope.os.path, "getmtime", side_effect=fake_getmtime
            ):
                index = project_scope._build_stdout_index(str(task))

            self.assertEqual(index, {})

    def test_unknown_candidate_is_not_running(self):
        """An unverifiable candidate is reported as not running."""
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / "workspace" / "task"
            task.mkdir(parents=True)
            (task / "sid0.111.session.stdout").touch()
            index = project_scope._build_stdout_index(str(task))
            entries = [{"session_id": "sid0"}]

            with patch.object(
                project_scope, "pid_state", return_value=ProcessState.UNKNOWN
            ):
                project_scope._enrich_running_status(entries, index=index)

            self.assertEqual(entries[0]["status"], "Idle")

    def test_one_alive_candidate_is_running(self):
        """One live candidate proves the session is running."""
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / "workspace" / "task"
            task.mkdir(parents=True)
            (task / "sid0.111.session.stdout").touch()
            (task / "sid0.222.session.stdout").touch()
            index = project_scope._build_stdout_index(str(task))
            entries = [{"session_id": "sid0"}]
            states = iter([ProcessState.DEAD, ProcessState.ALIVE])

            with patch.object(
                project_scope, "pid_state", side_effect=lambda _pid: next(states)
            ):
                project_scope._enrich_running_status(entries, index=index)

            self.assertEqual(entries[0]["status"], "Running")


if __name__ == "__main__":
    unittest.main()
