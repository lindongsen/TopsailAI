#!/usr/bin/env python3
"""Unit tests for same-session runtime context broadcasting."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))) )

from cli_topsailai import runtime_broadcast
from cli_topsailai.runtime_target import ProcessState


class TestRuntimeBroadcast(unittest.TestCase):
    """Verify discovery, filtering, deduplication, and delivery semantics."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(
            dir="/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all"
        )
        self.task_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _stdout(self, name):
        path = self.task_dir / name
        path.touch()
        return path

    def test_broadcasts_to_session_and_task_pids_once(self):
        """Matching session and task evidence receives one identical message."""
        self._stdout("named.101.session.stdout")
        self._stdout("named.101.worker.task.stdout")
        self._stdout("named.102.worker.task.stdout")
        self._stdout("other.103.session.stdout")
        writes = []

        def writer(path, message):
            writes.append((Path(path).name, message))
            return True

        result = runtime_broadcast.broadcast_message(
            self.task_dir,
            "named",
            "shared context",
            process_probe=lambda pid: ProcessState.ALIVE,
            injection_writer=writer,
        )

        self.assertEqual([item.pid for item in result.outcomes], [101, 102])
        self.assertEqual(result.queued, 2)
        self.assertEqual(
            writes,
            [
                ("named.101.session.agent2llm_inject_messages.jsonl", "shared context"),
                ("named.102.session.agent2llm_inject_messages.jsonl", "shared context"),
            ],
        )

    def test_exact_session_and_malformed_names_are_filtered(self):
        """Prefix lookalikes and unsupported filenames never become targets."""
        for name in (
            "named.201.session.stdout",
            "named-extra.202.session.stdout",
            "named.203.bad.task.stdout",
            "named.x.session.stdout",
            "named.0.session.stdout",
            "named.-4.session.stdout",
            "named.204.stderr",
        ):
            self._stdout(name)
        writes = []
        result = runtime_broadcast.broadcast_message(
            self.task_dir,
            "named",
            "message",
            process_probe=lambda pid: ProcessState.ALIVE,
            injection_writer=lambda path, message: writes.append(path) or True,
        )
        self.assertEqual([item.pid for item in result.outcomes], [201, 203])
        self.assertEqual(len(writes), 2)

    def test_temporary_and_invalid_sessions_are_rejected_before_discovery(self):
        """Temporary and path-like identities cannot group unrelated processes."""
        self._stdout("topsailai.301.session.stdout")
        self._stdout("named.302.session.stdout")
        for session_id in ("topsailai", "(temp)", "", "../named", None):
            with self.subTest(session_id=session_id):
                writer = Mock(return_value=True)
                result = runtime_broadcast.broadcast_message(
                    self.task_dir,
                    session_id,
                    "message",
                    process_probe=lambda pid: ProcessState.ALIVE,
                    injection_writer=writer,
                )
                self.assertEqual(result.outcomes[0].status, "invalid_session")
                writer.assert_not_called()

    def test_liveness_filters_dead_unknown_and_permission_denied(self):
        """Only ALIVE targets are written and liveness failures are classified."""
        for pid in (401, 402, 403, 404):
            self._stdout(f"named.{pid}.session.stdout")
        states = {
            401: ProcessState.ALIVE,
            402: ProcessState.DEAD,
            403: ProcessState.UNKNOWN,
        }
        writes = []

        def probe(pid):
            if pid == 404:
                raise PermissionError("denied")
            return states[pid]

        result = runtime_broadcast.broadcast_message(
            self.task_dir,
            "named",
            "message",
            process_probe=probe,
            injection_writer=lambda path, message: writes.append(path) or True,
        )
        self.assertEqual([Path(path).name for path in writes], ["named.401.session.agent2llm_inject_messages.jsonl"])
        self.assertEqual(
            {item.pid: item.status for item in result.outcomes},
            {401: "queued", 402: "skipped_exited", 403: "skipped_unverifiable", 404: "permission_denied"},
        )

    def test_partial_failure_continues_without_retry(self):
        """A failed append does not suppress or retry later targets."""
        for pid in (501, 502, 503):
            self._stdout(f"named.{pid}.session.stdout")
        calls = []

        def writer(path, message):
            pid = int(Path(path).name.split(".")[1])
            calls.append(pid)
            if pid == 501:
                raise OSError("append failed")
            if pid == 502:
                return False
            return True

        result = runtime_broadcast.broadcast_message(
            self.task_dir,
            "named",
            "message",
            process_probe=lambda pid: ProcessState.ALIVE,
            injection_writer=writer,
        )
        self.assertEqual(calls, [501, 502, 503])
        self.assertEqual(
            {item.pid: item.status for item in result.outcomes},
            {501: "delivery_unknown", 502: "delivery_unknown", 503: "queued"},
        )

    def test_real_public_writer_appends_jsonl_record(self):
        """The public writer creates a receiver-compatible JSONL record."""
        self._stdout("named.602.session.stdout")
        result = runtime_broadcast.broadcast_message(
            self.task_dir, "named", "jsonl integration",
            process_probe=lambda pid: ProcessState.ALIVE,
        )
        self.assertEqual(result.outcomes[0].status, "queued")
        endpoint = self.task_dir / "named.602.session.agent2llm_inject_messages.jsonl"
        record = __import__("json").loads(endpoint.read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("jsonl integration", str(record["content"]))

    def test_dispatcher_uses_real_writer_for_identical_records_and_preserves_queue(self):
        """The shared dispatcher appends identical public-writer records to each target."""
        from cli_topsailai import streaming

        self._stdout("named.613.session.stdout")
        self._stdout("named.613.worker.task.stdout")
        self._stdout("named.614.session.stdout")
        self._stdout("other.615.session.stdout")
        existing = self.task_dir / "named.613.session.agent2llm_inject_messages.jsonl"
        existing.write_text(json.dumps({"content": "existing"}) + "\n", encoding="utf-8")
        original = runtime_broadcast.broadcast_message

        def broadcast_with_alive(task_dir, session, message, *, progress_callback=None):
            return original(
                task_dir, session, message,
                process_probe=lambda pid: ProcessState.ALIVE,
                progress_callback=progress_callback,
            )

        with unittest.mock.patch.object(runtime_broadcast, "broadcast_message", broadcast_with_alive):
            streaming._handle_stream_command(
                "/ctx.btw-all shared through dispatcher", str(self.task_dir), [], "named", None
            )

        records = []
        for pid in (613, 614):
            endpoint = self.task_dir / f"named.{pid}.session.agent2llm_inject_messages.jsonl"
            records.append([json.loads(line) for line in endpoint.read_text(encoding="utf-8").splitlines()])
        self.assertEqual(records[0][0]["content"], "existing")
        self.assertEqual(records[0][1]["content"], records[1][0]["content"])
        self.assertIn("shared through dispatcher", str(records[0][1]["content"]))
        self.assertFalse((self.task_dir / "other.615.session.agent2llm_inject_messages.jsonl").exists())

    def test_real_writer_deduplicates_multiple_targets_and_preserves_other_session(self):
        """The public writer appends identical records only to deduplicated targets."""
        self._stdout("named.603.session.stdout")
        self._stdout("named.603.worker.task.stdout")
        self._stdout("named.604.worker.task.stdout")
        self._stdout("other.605.session.stdout")
        result = runtime_broadcast.broadcast_message(
            self.task_dir, "named", "shared jsonl",
            process_probe=lambda pid: ProcessState.ALIVE,
        )
        self.assertEqual([item.pid for item in result.outcomes], [603, 604])
        for pid in (603, 604):
            endpoint = self.task_dir / f"named.{pid}.session.agent2llm_inject_messages.jsonl"
            self.assertEqual(len(endpoint.read_text(encoding="utf-8").splitlines()), 1)
        self.assertFalse((self.task_dir / "other.605.session.agent2llm_inject_messages.jsonl").exists())

    def test_global_error_is_reported_through_progress_callback(self):
        """Global discovery errors remain visible to the streaming handler."""
        events = []
        result = runtime_broadcast.broadcast_message(
            self.task_dir / "missing", "named", "message",
            progress_callback=lambda kind, value: events.append((kind, value.status)),
        )
        self.assertEqual(events, [("outcome", "task_dir_missing")])
        self.assertEqual(result.counts, {"queued": 0, "skipped": 0, "failed": 1, "uncertain": 0})

    def test_real_writer_preserves_prior_progress_when_later_target_interrupts(self):
        """A later host interrupt leaves earlier public-writer JSONL intact."""
        self._stdout("named.611.session.stdout")
        self._stdout("named.612.session.stdout")
        progress = []
        calls = []

        def writer(path, message):
            calls.append(Path(path).name)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return runtime_broadcast.write_injection(path, message)

        with self.assertRaises(KeyboardInterrupt):
            runtime_broadcast.broadcast_message(
                self.task_dir,
                "named",
                "interrupt after first",
                process_probe=lambda pid: ProcessState.ALIVE,
                injection_writer=writer,
                progress_callback=lambda kind, value: progress.append((kind, value)),
            )

        first = self.task_dir / "named.611.session.agent2llm_inject_messages.jsonl"
        second = self.task_dir / "named.612.session.agent2llm_inject_messages.jsonl"
        self.assertTrue(first.exists())
        self.assertEqual(len(first.read_text(encoding="utf-8").splitlines()), 1)
        self.assertFalse(second.exists())
        self.assertEqual(calls, [first.name, second.name])
        self.assertEqual(progress[0], ("snapshot", 2))
        self.assertEqual(progress[1][0], "outcome")
        self.assertEqual(progress[1][1].pid, 611)
        self.assertEqual(progress[1][1].status, "queued")

    def test_host_interrupts_propagate_from_writer(self):
        """Cancellation must not be converted into an ordinary delivery error."""
        self._stdout("named.601.session.stdout")

        def writer(path, message):
            raise SystemExit("stop")

        with self.assertRaises(SystemExit):
            runtime_broadcast.broadcast_message(
                self.task_dir,
                "named",
                "message",
                process_probe=lambda pid: ProcessState.ALIVE,
                injection_writer=writer,
            )

    def test_invalid_endpoint_is_reported_without_writing(self):
        """A pre-existing non-regular injection endpoint is never overwritten."""
        self._stdout("named.701.session.stdout")
        endpoint = self.task_dir / "named.701.session.agent2llm_inject_messages.jsonl"
        endpoint.mkdir()
        writer = Mock(return_value=True)
        result = runtime_broadcast.broadcast_message(
            self.task_dir,
            "named",
            "message",
            process_probe=lambda pid: ProcessState.ALIVE,
            injection_writer=writer,
        )
        self.assertEqual(result.outcomes[0].status, "failed_prewrite")
        writer.assert_not_called()

    def test_broadcast_result_incomplete_categories(self):
        """Empty and non-queued aggregates are incomplete while queued is complete."""
        self.assertTrue(runtime_broadcast.BroadcastResult("named", ()).incomplete)
        self.assertTrue(
            runtime_broadcast.BroadcastResult(
                "named", (runtime_broadcast.BroadcastOutcome(1, "delivery_unknown"),)
            ).incomplete
        )
        self.assertFalse(
            runtime_broadcast.BroadcastResult(
                "named", (runtime_broadcast.BroadcastOutcome(1, "queued"),)
            ).incomplete
        )

    def test_stdout_target_ignores_missing_nonregular_and_invalid_pid(self):
        """Discovery ignores races, nonregular files, and unparsable PID text."""
        missing = self.task_dir / "named.801.session.stdout"
        self.assertIsNone(runtime_broadcast._stdout_target(missing, self.task_dir, "named"))
        directory = self.task_dir / "named.802.session.stdout"
        directory.mkdir()
        self.assertIsNone(runtime_broadcast._stdout_target(directory, self.task_dir, "named"))
        invalid = self.task_dir / "named.803.session.stdout"
        invalid.touch()
        with unittest.mock.patch.object(
            runtime_broadcast, "parse_stdout_filename", return_value=("named", "bad")
        ):
            self.assertIsNone(
                runtime_broadcast._stdout_target(
                    self.task_dir / "named.803.session.stdout", self.task_dir, "named"
                )
            )

    def test_revalidate_rejects_changed_evidence(self):
        """Revalidation reports missing, nonregular, and renamed evidence."""
        target = runtime_broadcast.BroadcastTarget(
            "named", 804, self.task_dir / "named.804.session.stdout", self.task_dir / "inject"
        )
        self.assertEqual(
            runtime_broadcast._revalidate(target, lambda pid: ProcessState.ALIVE),
            "evidence_changed",
        )
        target.stdout_path.mkdir()
        self.assertEqual(
            runtime_broadcast._revalidate(target, lambda pid: ProcessState.ALIVE),
            "evidence_changed",
        )
        target.stdout_path.rmdir()
        target = runtime_broadcast.BroadcastTarget(
            "named", 804, self.task_dir / "other.804.session.stdout", self.task_dir / "inject"
        )
        target.stdout_path.touch()
        self.assertEqual(
            runtime_broadcast._revalidate(target, lambda pid: ProcessState.ALIVE),
            "evidence_changed",
        )

    def test_revalidation_target_errors_and_progress_callbacks(self):
        """Target exceptions are classified and each outcome is reported."""
        for pid in (807, 808, 809):
            self._stdout(f"named.{pid}.session.stdout")
        events = []
        def probe(pid):
            if pid == 807:
                from cli_topsailai.runtime_target import RuntimeTargetError
                raise RuntimeTargetError("permission_denied", "denied")
            if pid == 808:
                from cli_topsailai.runtime_target import RuntimeTargetError
                raise RuntimeTargetError("unsupported_transport", "unknown")
            return ProcessState.ALIVE
        result = runtime_broadcast.broadcast_message(
            self.task_dir, "named", "message", process_probe=probe,
            injection_writer=lambda path, message: True,
            progress_callback=lambda kind, value: events.append((kind, value)),
        )
        self.assertEqual([item.status for item in result.outcomes], ["permission_denied", "skipped_unverifiable", "queued"])
        self.assertEqual(events[0], ("snapshot", 3))
        self.assertEqual([item[0] for item in events[1:]], ["outcome"] * 3)

    def test_revalidation_permission_denied_evidence_is_classified(self):
        """Revalidation denial for one target does not suppress a later target."""
        self._stdout("named.810.session.stdout")
        self._stdout("named.811.session.stdout")
        original = Path.lstat
        discovery_seen = False

        def lstat(path):
            nonlocal discovery_seen
            if path.name == "named.810.session.stdout":
                if not discovery_seen:
                    discovery_seen = True
                    return original(path)
                raise PermissionError("denied during revalidation")
            return original(path)

        writes = []
        with unittest.mock.patch.object(Path, "lstat", lstat):
            result = runtime_broadcast.broadcast_message(
                self.task_dir, "named", "message", process_probe=lambda pid: ProcessState.ALIVE,
                injection_writer=lambda path, message: writes.append(Path(path).name) or True,
            )
        self.assertEqual(
            {item.pid: item.status for item in result.outcomes},
            {810: "permission_denied", 811: "queued"},
        )
        self.assertEqual(writes, ["named.811.session.agent2llm_inject_messages.jsonl"])

    def test_task_directory_errors_are_reported(self):
        """Missing, invalid, and inaccessible task directories fail visibly."""
        missing = self.task_dir / "missing"
        result = runtime_broadcast.broadcast_message(missing, "named", "message")
        self.assertEqual(result.outcomes[0].status, "task_dir_missing")
        file_path = self.task_dir / "not-a-directory"
        file_path.touch()
        result = runtime_broadcast.broadcast_message(file_path, "named", "message")
        self.assertEqual(result.outcomes[0].status, "task_dir_invalid")
        with unittest.mock.patch.object(Path, "lstat", side_effect=PermissionError("denied")):
            result = runtime_broadcast.broadcast_message(self.task_dir, "named", "message")
        self.assertEqual(result.outcomes[0].status, "permission_denied")

    def test_discovery_permission_error_is_reported(self):
        """A task directory enumeration error does not attempt any write."""
        with unittest.mock.patch.object(
            runtime_broadcast, "_discover", side_effect=PermissionError("denied")
        ):
            result = runtime_broadcast.broadcast_message(self.task_dir, "named", "message")
        self.assertEqual(result.outcomes[0].status, "permission_denied")

    def test_existing_regular_endpoint_and_endpoint_permission_error(self):
        """Regular endpoints are accepted and inaccessible endpoints fail prewrite."""
        self._stdout("named.805.session.stdout")
        endpoint = self.task_dir / "named.805.session.agent2llm_inject_messages.jsonl"
        endpoint.touch()
        writer = Mock(return_value=True)
        result = runtime_broadcast.broadcast_message(
            self.task_dir, "named", "message",
            process_probe=lambda pid: ProcessState.ALIVE, injection_writer=writer,
        )
        self.assertEqual(result.outcomes[0].status, "queued")
        self._stdout("named.806.session.stdout")
        original_lstat = Path.lstat

        def lstat(path):
            if path.name == "named.806.session.agent2llm_inject_messages.jsonl":
                raise PermissionError("denied")
            return original_lstat(path)

        with unittest.mock.patch.object(Path, "lstat", lstat):
            result = runtime_broadcast.broadcast_message(
                self.task_dir, "named", "message",
                process_probe=lambda pid: ProcessState.ALIVE, injection_writer=writer,
            )
        self.assertEqual(
            {item.pid: item.status for item in result.outcomes}[806], "failed_prewrite"
        )


if __name__ == "__main__":
    unittest.main()
