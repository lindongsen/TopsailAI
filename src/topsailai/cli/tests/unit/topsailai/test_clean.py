#!/usr/bin/env python3
"""
Unit tests for cleanup helpers in cli_topsailai.

Covers:
- clean_expired_files()
- clean_by_numbers()
"""

import sys
import os
import unittest
import tempfile
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from cli_topsailai import cleaning
from cli_topsailai.cleaning import clean_by_numbers, clean_expired_files


def _make_file_record(path: str) -> dict:
    """Build a log-file record matching discover_log_files output."""
    stat_info = os.stat(path)
    return {
        "filename": os.path.basename(path),
        "path": path,
        "session_id": None,
        "pid": None,
        "size": stat_info.st_size,
        "mtime": stat_info.st_mtime,
        "ctime": stat_info.st_ctime,
    }


class TestCleanExpiredFiles(unittest.TestCase):
    """Tests for clean_expired_files()."""

    @mock.patch("cli_topsailai.cleaning.input")
    def test_deletes_only_old_idle_files(self, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            old_path = os.path.join(tmp, "old.session.stdout")
            new_path = os.path.join(tmp, "new.session.stdout")
            with open(old_path, "w") as f:
                f.write("old")
            with open(new_path, "w") as f:
                f.write("new")
            # Make old file 4 days old
            old_mtime = time.time() - 4 * 24 * 3600
            os.utime(old_path, (old_mtime, old_mtime))

            files = [
                _make_file_record(old_path),
                _make_file_record(new_path),
            ]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 1)
            self.assertFalse(os.path.exists(old_path))
            self.assertTrue(os.path.exists(new_path))

    @mock.patch("cli_topsailai.cleaning.input")
    def test_no_expired_files(self, mock_input):
        with tempfile.TemporaryDirectory() as tmp:
            new_path = os.path.join(tmp, "new.session.stdout")
            with open(new_path, "w") as f:
                f.write("new")
            files = [_make_file_record(new_path)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 0)
            self.assertTrue(os.path.exists(new_path))

    @mock.patch("cli_topsailai.cleaning.input")
    def test_cancelled_confirmation(self, mock_input):
        mock_input.return_value = "n"
        with tempfile.TemporaryDirectory() as tmp:
            old_path = os.path.join(tmp, "old.session.stdout")
            with open(old_path, "w") as f:
                f.write("old")
            old_mtime = time.time() - 4 * 24 * 3600
            os.utime(old_path, (old_mtime, old_mtime))

            files = [_make_file_record(old_path)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 0)
            self.assertTrue(os.path.exists(old_path))

    @mock.patch("cli_topsailai.cleaning.input")
    def test_eof_cancels(self, mock_input):
        mock_input.side_effect = EOFError()
        with tempfile.TemporaryDirectory() as tmp:
            old_path = os.path.join(tmp, "old.session.stdout")
            with open(old_path, "w") as f:
                f.write("old")
            old_mtime = time.time() - 4 * 24 * 3600
            os.utime(old_path, (old_mtime, old_mtime))

            files = [_make_file_record(old_path)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 0)

    @mock.patch("cli_topsailai.cleaning.input")
    @mock.patch("cli_topsailai.cleaning.is_file_in_use", return_value=False)
    def test_deletes_related_session_files(self, mock_in_use, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            stdout = os.path.join(tmp, "old.1234.session.stdout")
            stderr = os.path.join(tmp, "old.1234.session.stderr")
            pipe = os.path.join(tmp, "old.1234.session.pipe")
            inject = os.path.join(tmp, "old.1234.session.agent2llm_inject_messages.jsonl")
            task_stdout = os.path.join(tmp, "old.1234.step-1.task.stdout")
            for p in [stdout, stderr, pipe, inject, task_stdout]:
                with open(p, "w") as f:
                    f.write("x")

            old_mtime = time.time() - 4 * 24 * 3600
            for p in [stdout, stderr, pipe, inject, task_stdout]:
                os.utime(p, (old_mtime, old_mtime))

            files = [_make_file_record(stdout)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 5)
            self.assertFalse(os.path.exists(stdout))
            self.assertFalse(os.path.exists(stderr))
            self.assertFalse(os.path.exists(pipe))
            self.assertFalse(os.path.exists(inject))
            self.assertFalse(os.path.exists(task_stdout))

    @mock.patch("cli_topsailai.cleaning.input")
    @mock.patch("cli_topsailai.cleaning.is_file_in_use", return_value=False)
    def test_does_not_delete_unrelated_files(self, mock_in_use, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            old_stdout = os.path.join(tmp, "old.1234.session.stdout")
            other_stdout = os.path.join(tmp, "other.5678.session.stdout")
            for p in [old_stdout, other_stdout]:
                with open(p, "w") as f:
                    f.write("x")

            old_mtime = time.time() - 4 * 24 * 3600
            os.utime(old_stdout, (old_mtime, old_mtime))
            os.utime(other_stdout, (old_mtime, old_mtime))

            files = [_make_file_record(old_stdout)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 1)
            self.assertFalse(os.path.exists(old_stdout))
            self.assertTrue(os.path.exists(other_stdout))

    @mock.patch("cli_topsailai.cleaning.input")
    @mock.patch("cli_topsailai.cleaning.is_file_in_use")
    def test_skips_in_use_related_files(self, mock_in_use, mock_input):
        mock_input.return_value = "y"

        def _in_use_side_effect(path):
            return path.endswith(".session.stderr")

        mock_in_use.side_effect = _in_use_side_effect
        with tempfile.TemporaryDirectory() as tmp:
            stdout = os.path.join(tmp, "old.1234.session.stdout")
            stderr = os.path.join(tmp, "old.1234.session.stderr")
            pipe = os.path.join(tmp, "old.1234.session.pipe")
            for p in [stdout, stderr, pipe]:
                with open(p, "w") as f:
                    f.write("x")

            old_mtime = time.time() - 4 * 24 * 3600
            for p in [stdout, stderr, pipe]:
                os.utime(p, (old_mtime, old_mtime))

            files = [_make_file_record(stdout)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 2)
            self.assertFalse(os.path.exists(stdout))
            self.assertTrue(os.path.exists(stderr))
            self.assertFalse(os.path.exists(pipe))

    @mock.patch("cli_topsailai.cleaning.input")
    @mock.patch("cli_topsailai.cleaning.is_file_in_use", return_value=True)
    def test_skips_in_use_expired_file(self, mock_in_use, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            old_path = os.path.join(tmp, "old.session.stdout")
            with open(old_path, "w") as f:
                f.write("old")
            old_mtime = time.time() - 4 * 24 * 3600
            os.utime(old_path, (old_mtime, old_mtime))

            files = [_make_file_record(old_path)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 0)
            self.assertTrue(os.path.exists(old_path))



class TestAgentLaunchLogCleanup(unittest.TestCase):
    """Tests for diagnostic launch-log retention and active protection."""

    @mock.patch("cli_topsailai.cleaning.input", return_value="y")
    def test_deletes_expired_launch_log_and_backup(self, _mock_input):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("workspace-agent-x.agent-launch.log", "workspace-agent-x.agent-launch.log.1"):
                path = os.path.join(tmp, name)
                with open(path, "w") as handle:
                    handle.write("log")
                old = time.time() - 4 * 24 * 3600
                os.utime(path, (old, old))
            self.assertEqual(clean_expired_files(tmp, []), 2)

    @mock.patch("cli_topsailai.cleaning.input", return_value="y")
    def test_protects_active_launch_log_with_lease(self, _mock_input):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "workspace-agent-x.agent-launch.log")
            with open(path, "w") as handle:
                handle.write("active")
            old = time.time() - 4 * 24 * 3600
            os.utime(path, (old, old))
            with open(path + ".lease", "w") as handle:
                handle.write("lease")
            self.assertEqual(clean_expired_files(tmp, []), 0)
            self.assertTrue(os.path.exists(path))

class TestCleanByNumbers(unittest.TestCase):
    """Tests for clean_by_numbers()."""

    @mock.patch("cli_topsailai.cleaning.input")
    def test_deletes_selected_indices(self, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            path1 = os.path.join(tmp, "a.session.stdout")
            path2 = os.path.join(tmp, "b.session.stdout")
            path3 = os.path.join(tmp, "c.session.stdout")
            for p in [path1, path2, path3]:
                with open(p, "w") as f:
                    f.write("x")

            files = [
                _make_file_record(path1),
                _make_file_record(path2),
                _make_file_record(path3),
            ]
            deleted_count = clean_by_numbers(tmp, files, [0, 2])
            self.assertEqual(deleted_count, 2)
            self.assertFalse(os.path.exists(path1))
            self.assertTrue(os.path.exists(path2))
            self.assertFalse(os.path.exists(path3))

    @mock.patch("cli_topsailai.cleaning.input")
    def test_invalid_index_ignored(self, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            path1 = os.path.join(tmp, "a.session.stdout")
            with open(path1, "w") as f:
                f.write("x")
            files = [_make_file_record(path1)]
            deleted_count = clean_by_numbers(tmp, files, [5])
            self.assertEqual(deleted_count, 0)

    @mock.patch("cli_topsailai.cleaning.input")
    def test_cancelled_confirmation(self, mock_input):
        mock_input.return_value = "n"
        with tempfile.TemporaryDirectory() as tmp:
            path1 = os.path.join(tmp, "a.session.stdout")
            with open(path1, "w") as f:
                f.write("x")
            files = [_make_file_record(path1)]
            deleted_count = clean_by_numbers(tmp, files, [0])
            self.assertEqual(deleted_count, 0)
            self.assertTrue(os.path.exists(path1))


class TestCleanByNumbersRelatedFiles(unittest.TestCase):
    """Tests for clean_by_numbers() related-file expansion."""

    @mock.patch("cli_topsailai.cleaning.input")
    @mock.patch("cli_topsailai.cleaning.is_file_in_use", return_value=False)
    def test_deletes_related_files_by_number(self, mock_in_use, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            stdout = os.path.join(tmp, "s.1.session.stdout")
            stderr = os.path.join(tmp, "s.1.session.stderr")
            pipe = os.path.join(tmp, "s.1.session.pipe")
            for p in [stdout, stderr, pipe]:
                with open(p, "w") as f:
                    f.write("x")

            files = [_make_file_record(stdout)]
            deleted_count = clean_by_numbers(tmp, files, [0])
            self.assertEqual(deleted_count, 3)
            self.assertFalse(os.path.exists(stdout))
            self.assertFalse(os.path.exists(stderr))
            self.assertFalse(os.path.exists(pipe))


if __name__ == "__main__":
    unittest.main()


class TestLaunchLogLifecycle(unittest.TestCase):
    """UNIT 1B-2 proofs for launch-log expiry and lease authority."""

    def _make_log(self, tmp, name, age_days=4):
        """Create one launch log with an explicit age."""
        path = os.path.join(tmp, name)
        with open(path, "w") as handle:
            handle.write("log")
        old = time.time() - age_days * 24 * 3600
        os.utime(path, (old, old))
        return path

    @mock.patch("cli_topsailai.cleaning.input", return_value="y")
    def test_b22_expired_idle_log_cleanup_is_exact_and_confirmed(self, _mock_input):
        """Only the exact expired group is deleted; unrelated files survive."""
        with tempfile.TemporaryDirectory() as tmp:
            active = self._make_log(tmp, "workspace-agent-a.agent-launch.log")
            backup1 = self._make_log(tmp, "workspace-agent-a.agent-launch.log.1")
            backup2 = self._make_log(tmp, "workspace-agent-a.agent-launch.log.2")
            fresh = self._make_log(tmp, "workspace-agent-b.agent-launch.log", age_days=0)
            unrelated = os.path.join(tmp, "other.session.stdout")
            with open(unrelated, "w") as handle:
                handle.write("keep")
            deleted = clean_expired_files(tmp, [])
            self.assertEqual(deleted, 3)
            for path in (active, backup1, backup2):
                self.assertFalse(os.path.exists(path))
            self.assertTrue(os.path.exists(fresh))
            self.assertTrue(os.path.exists(unrelated))

    @mock.patch("cli_topsailai.cleaning.input", return_value="n")
    def test_b22_cancel_deletes_nothing(self, _mock_input):
        """A declined confirmation deletes no launch log."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_log(tmp, "workspace-agent-c.agent-launch.log")
            self.assertEqual(clean_expired_files(tmp, []), 0)
            self.assertTrue(os.path.exists(path))

    @mock.patch("cli_topsailai.cleaning.input", return_value="y")
    def test_b23_active_lease_and_mutation_time_revalidation(self, _mock_input):
        """A live lease protects the log; a stale lease does not."""
        from cli_topsailai import agent_launch_background as bg
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_log(tmp, "workspace-agent-d.agent-launch.log")
            lease = bg.active_launch_lease(Path(path))
            # A lease owned by this live process protects the log.
            bg._write_lease(lease, pid=os.getpid(), identity=bg._authoritative_child_identity(os.getpid()))
            self.assertEqual(clean_expired_files(tmp, []), 0)
            self.assertTrue(os.path.exists(path))
            # A lease whose recorded owner is gone is stale and must not protect.
            lease.unlink()
            bg._write_lease(lease, pid=999999, identity=(999999, 1))
            self.assertEqual(clean_expired_files(tmp, []), 1)
            self.assertFalse(os.path.exists(path))

    @mock.patch("cli_topsailai.cleaning.input", return_value="y")
    def test_b23_unreadable_lease_fails_closed(self, _mock_input):
        """An unreadable lease is not proof of inactivity, so the log survives."""
        from cli_topsailai import agent_launch_background as bg
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_log(tmp, "workspace-agent-e.agent-launch.log")
            bg.active_launch_lease(Path(path)).write_text("not json")
            self.assertEqual(clean_expired_files(tmp, []), 0)
            self.assertTrue(os.path.exists(path))


class TestLaunchLogRevalidation(unittest.TestCase):
    """UNIT 1B-2 proofs for mutation-time revalidation before deletion."""

    def _make_log(self, tmp, name, age_days=4):
        """Create one launch log with an explicit age."""
        path = os.path.join(tmp, name)
        with open(path, "w") as handle:
            handle.write("log")
        old = time.time() - age_days * 24 * 3600
        os.utime(path, (old, old))
        return path

    @mock.patch("cli_topsailai.cleaning.input", return_value="y")
    def test_b23_log_becoming_active_before_deletion_is_skipped(self, _mock_input):
        """A log that gains a live lease after inventory is not deleted."""
        from cli_topsailai import agent_launch_background as bg
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_log(tmp, "workspace-agent-f.agent-launch.log")
            real_records = cleaning._launch_log_records

            def records(task_dir):
                found = real_records(task_dir)
                # The lease appears after the inventory was built.
                bg._write_lease(bg.active_launch_lease(Path(path)), pid=os.getpid(),
                                identity=bg._authoritative_child_identity(os.getpid()))
                return found

            with mock.patch.object(cleaning, "_launch_log_records", records):
                deleted = clean_expired_files(tmp, [])
            self.assertEqual(deleted, 0)
            self.assertTrue(os.path.exists(path))

    @mock.patch("cli_topsailai.cleaning.input", return_value="y")
    def test_b23_changed_file_before_deletion_is_skipped(self, _mock_input):
        """A file whose mtime changed after inventory is not deleted."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_log(tmp, "workspace-agent-g.agent-launch.log")
            real_records = cleaning._launch_log_records

            def records(task_dir):
                found = real_records(task_dir)
                # The file is rewritten after the inventory was built.
                os.utime(path, (time.time(), time.time()))
                return found

            with mock.patch.object(cleaning, "_launch_log_records", records):
                deleted = clean_expired_files(tmp, [])
            self.assertEqual(deleted, 0)
            self.assertTrue(os.path.exists(path))

    @mock.patch("cli_topsailai.cleaning.input", return_value="y")
    def test_b23_vanished_file_is_reported_not_deleted(self, _mock_input):
        """A file removed after inventory is reported as a failure, not counted."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_log(tmp, "workspace-agent-h.agent-launch.log")
            real_records = cleaning._launch_log_records

            def records(task_dir):
                found = real_records(task_dir)
                os.remove(path)
                return found

            with mock.patch.object(cleaning, "_launch_log_records", records):
                deleted = clean_expired_files(tmp, [])
            self.assertEqual(deleted, 0)

    @mock.patch("cli_topsailai.cleaning.input", return_value="y")
    def test_b23_remove_failure_is_reported(self, _mock_input):
        """A failing removal is reported and not counted as deleted."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_log(tmp, "workspace-agent-i.agent-launch.log")
            with mock.patch("cli_topsailai.cleaning.os.remove",
                            side_effect=OSError("permission denied")):
                deleted = clean_expired_files(tmp, [])
            self.assertEqual(deleted, 0)
            self.assertTrue(os.path.exists(path))

    def test_b24_launch_log_records_ignores_unrelated_and_missing_dir(self):
        """Discovery selects only launch logs and tolerates a missing directory."""
        with tempfile.TemporaryDirectory() as tmp:
            self._make_log(tmp, "a.agent-launch.log")
            self._make_log(tmp, "a.agent-launch.log.1")
            with open(os.path.join(tmp, "other.session.stdout"), "w") as handle:
                handle.write("x")
            os.mkdir(os.path.join(tmp, "dir.agent-launch.log"))
            names = sorted(r["filename"] for r in cleaning._launch_log_records(tmp))
            self.assertEqual(names, ["a.agent-launch.log", "a.agent-launch.log.1"])
            self.assertEqual(cleaning._launch_log_records(os.path.join(tmp, "missing")), [])


class TestLaunchLogDeletionRevalidation(unittest.TestCase):
    """UNIT 1B-2 proofs for the deletion-loop revalidation itself."""

    def _make_log(self, tmp, name, age_days=4):
        """Create one launch log with an explicit age."""
        path = os.path.join(tmp, name)
        with open(path, "w") as handle:
            handle.write("log")
        old = time.time() - age_days * 24 * 3600
        os.utime(path, (old, old))
        return path

    @mock.patch("cli_topsailai.cleaning.input", return_value="y")
    def test_b23_lease_appearing_after_inventory_skips_deletion(self, _mock_input):
        """A lease created after inventory still protects the log at deletion time."""
        from cli_topsailai import agent_launch_background as bg
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_log(tmp, "workspace-agent-j.agent-launch.log")
            real_expand = cleaning._expand_to_related_files

            def expand(task_dir, selected):
                # The lease appears after the inventory filter already ran.
                bg._write_lease(bg.active_launch_lease(Path(path)), pid=os.getpid(),
                                identity=bg._authoritative_child_identity(os.getpid()))
                return real_expand(task_dir, selected)

            with mock.patch.object(cleaning, "_expand_to_related_files", expand):
                deleted = clean_expired_files(tmp, [])
            self.assertEqual(deleted, 0)
            self.assertTrue(os.path.exists(path))

    @mock.patch("cli_topsailai.cleaning.input", return_value="y")
    def test_b23_stat_failure_at_deletion_is_reported(self, _mock_input):
        """A file that cannot be stat-ed at deletion time is reported, not deleted."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_log(tmp, "workspace-agent-k.agent-launch.log")
            real_expand = cleaning._expand_to_related_files

            def expand(task_dir, selected):
                expanded = real_expand(task_dir, selected)
                os.remove(path)
                return expanded

            with mock.patch.object(cleaning, "_expand_to_related_files", expand):
                deleted = clean_expired_files(tmp, [])
            self.assertEqual(deleted, 0)

    def test_b24_launch_log_records_tolerates_stat_failure(self):
        """A launch log that cannot be stat-ed is skipped, not fatal."""
        with tempfile.TemporaryDirectory() as tmp:
            self._make_log(tmp, "a.agent-launch.log")
            real_stat = os.stat
            calls = {"n": 0}

            def stat(path, *args, **kwargs):
                # The first call is the isfile() probe; the second is the record stat.
                calls["n"] += 1
                if calls["n"] > 1:
                    raise OSError("denied")
                return real_stat(path, *args, **kwargs)

            with mock.patch("cli_topsailai.cleaning.os.stat", stat):
                self.assertEqual(cleaning._launch_log_records(tmp), [])

    def test_b24_expand_skips_duplicates_and_stat_failures(self):
        """Related-file expansion deduplicates and tolerates stat failures."""
        with tempfile.TemporaryDirectory() as tmp:
            first = self._make_log(tmp, "s.1.session.stdout")
            second = self._make_log(tmp, "s.1.session.stderr")
            selected = [{"filename": "s.1.session.stdout", "path": first,
                         "size": 3, "mtime": os.stat(first).st_mtime}]
            with mock.patch("cli_topsailai.cleaning.find_related_files_for_path",
                            return_value=[first, first, second]):
                with mock.patch("cli_topsailai.cleaning.os.stat",
                                side_effect=OSError("denied")):
                    expanded = cleaning._expand_to_related_files(tmp, selected)
            self.assertEqual(expanded, [])


class TestLaunchLogLeaseIsNotARecord(unittest.TestCase):
    """UNIT 1B-2 proof that a lease sidecar is never a deletable record."""

    def test_b23_lease_sidecar_is_excluded_from_records(self):
        """Deleting a live lease would make a live log look inactive."""
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "a.agent-launch.log")
            with open(log, "w") as handle:
                handle.write("log")
            with open(log + ".lease", "w") as handle:
                handle.write('{"pid": 1, "start": 2}')
            names = [r["filename"] for r in cleaning._launch_log_records(tmp)]
            self.assertEqual(names, ["a.agent-launch.log"])

    @mock.patch("cli_topsailai.cleaning.input", return_value="y")
    def test_b23_live_lease_survives_clean_and_protects_log(self, _mock_input):
        """A live lease is neither deleted nor bypassed by the cleaner."""
        from cli_topsailai import agent_launch_background as bg
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "b.agent-launch.log")
            with open(log, "w") as handle:
                handle.write("log")
            old = time.time() - 4 * 24 * 3600
            os.utime(log, (old, old))
            lease = bg.active_launch_lease(Path(log))
            bg._write_lease(lease, pid=os.getpid(),
                            identity=bg._authoritative_child_identity(os.getpid()))
            deleted = clean_expired_files(tmp, [])
            self.assertEqual(deleted, 0)
            self.assertTrue(os.path.exists(log))
            self.assertTrue(os.path.exists(lease))
