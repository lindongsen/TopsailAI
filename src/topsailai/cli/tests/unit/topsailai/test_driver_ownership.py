"""Unit tests for owned driver process-tree termination.

These tests cover the ownership contract that makes a resume cancellation
truthful: a driver that is not the direct child (dtach daemonizes, tmux runs it
inside a server) must still be proven gone before cancellation is reported.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from cli_topsailai import driver_ownership
from cli_topsailai.driver_ownership import (
    DriverOwnership,
    read_pidfile,
    remove_pidfile,
    stop_owned_driver,
)


def _wait_for_file(path, timeout=5.0):
    """Wait until *path* exists and return its stripped content."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    text = handle.read().strip()
            except OSError:
                text = ""
            if text:
                return text
        time.sleep(0.02)
    raise AssertionError(f"pidfile was not written: {path}")


def _pid_alive(pid):
    """Return whether *pid* still exists."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class TestPidfile(unittest.TestCase):
    """The pidfile is the only exact driver identity for wrapped modes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="driver-ownership-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_read_pidfile_returns_recorded_pid(self):
        path = os.path.join(self.tmpdir, "driver.pid")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("4321\n")
        self.assertEqual(read_pidfile(path), 4321)

    def test_read_pidfile_absent_or_invalid_returns_none(self):
        self.assertIsNone(read_pidfile(None))
        self.assertIsNone(read_pidfile(os.path.join(self.tmpdir, "missing.pid")))
        path = os.path.join(self.tmpdir, "garbage.pid")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not-a-pid")
        self.assertIsNone(read_pidfile(path))

    def test_remove_pidfile_deletes_and_logs(self):
        path = os.path.join(self.tmpdir, "driver.pid")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("1")
        with patch("builtins.print") as mock_print:
            remove_pidfile(path)
        self.assertFalse(os.path.exists(path))
        mock_print.assert_called_once()
        self.assertIn("[OK] Deleted:", mock_print.call_args.args[0])

    def test_remove_pidfile_absent_is_silent(self):
        with patch("builtins.print") as mock_print:
            remove_pidfile(os.path.join(self.tmpdir, "missing.pid"))
        mock_print.assert_not_called()


class TestRawOwnership(unittest.TestCase):
    """In raw mode the driver is the direct child."""

    def test_raw_delegates_to_direct_child_stop(self):
        child = object()
        with patch.object(
            driver_ownership, "_stop_direct_child", return_value=True
        ) as mock_stop:
            self.assertTrue(stop_owned_driver(DriverOwnership(kind="raw"), child))
        mock_stop.assert_called_once_with(child)

    def test_raw_reports_unproven_custody(self):
        with patch.object(
            driver_ownership, "_stop_direct_child", return_value=False
        ):
            self.assertFalse(
                stop_owned_driver(DriverOwnership(kind="raw"), object())
            )

    def test_direct_child_stop_skips_group_signal_when_not_group_leader(self):
        """A tmux client shares the caller's group and must not be group-killed."""
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(child.kill)
        with patch.object(driver_ownership, "_signal_child_group") as mock_group:
            self.assertTrue(
                driver_ownership._stop_direct_child(child, signal_group=False)
            )
        mock_group.assert_not_called()
        self.assertIsNotNone(child.poll())


class TestWrappedOwnership(unittest.TestCase):
    """dtach and tmux drivers are not the direct child."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="driver-ownership-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.pidfile = os.path.join(self.tmpdir, "driver.pid")

    def test_dtach_stops_recorded_driver_group(self):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(child.kill)
        with open(self.pidfile, "w", encoding="utf-8") as handle:
            handle.write(str(child.pid))
        ownership = DriverOwnership(kind="dtach", pidfile=self.pidfile)
        self.assertTrue(stop_owned_driver(ownership, child))
        self.assertFalse(_pid_alive(child.pid))
        self.assertFalse(os.path.exists(self.pidfile))

    def test_dtach_without_pidfile_reports_unproven_custody(self):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(child.kill)
        ownership = DriverOwnership(kind="dtach", pidfile=self.pidfile)
        self.assertFalse(stop_owned_driver(ownership, child))

    def test_dtach_surviving_driver_reports_unproven_custody(self):
        """A driver tree that cannot be proven empty must not be reported stopped."""
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(child.kill)
        with open(self.pidfile, "w", encoding="utf-8") as handle:
            handle.write(str(child.pid))
        ownership = DriverOwnership(kind="dtach", pidfile=self.pidfile)
        with patch.object(driver_ownership, "_wait_group_gone", return_value=False):
            self.assertFalse(stop_owned_driver(ownership, child))

    def test_tmux_kills_session_and_does_not_group_signal_client(self):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(child.kill)
        with open(self.pidfile, "w", encoding="utf-8") as handle:
            handle.write(str(child.pid))
        ownership = DriverOwnership(
            kind="tmux", pidfile=self.pidfile, session_name="topsailai-test"
        )
        with patch.object(
            driver_ownership, "_kill_tmux_session", return_value=True
        ) as mock_kill, patch.object(
            driver_ownership, "_stop_direct_child", return_value=True
        ) as mock_child, patch.object(
            driver_ownership, "_stop_owned_group", return_value=True
        ):
            self.assertTrue(stop_owned_driver(ownership, child))
        mock_kill.assert_called_once_with("topsailai-test")
        self.assertFalse(mock_child.call_args.kwargs["signal_group"])

    def test_tmux_session_kill_failure_without_pidfile_is_unproven(self):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(child.kill)
        ownership = DriverOwnership(
            kind="tmux", pidfile=self.pidfile, session_name="topsailai-test"
        )
        with patch.object(
            driver_ownership, "_kill_tmux_session", return_value=False
        ), patch.object(driver_ownership, "_stop_direct_child", return_value=True):
            self.assertFalse(stop_owned_driver(ownership, child))

    def test_tmux_without_pidfile_is_unproven_even_when_session_dies(self):
        """A killed session is not proof that the owned driver tree is empty."""
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(child.kill)
        ownership = DriverOwnership(
            kind="tmux", pidfile=self.pidfile, session_name="topsailai-test"
        )
        with patch.object(
            driver_ownership, "_kill_tmux_session", return_value=True
        ), patch.object(driver_ownership, "_stop_direct_child", return_value=True):
            self.assertFalse(stop_owned_driver(ownership, child))


class TestRealWrappedDriver(unittest.TestCase):
    """End-to-end ownership against a real daemonized-style wrapper."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="driver-ownership-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.pidfile = os.path.join(self.tmpdir, "driver.pid")

    def test_wrapper_records_driver_pid_and_stop_proves_it_dead(self):
        """The wrapper records its own PID, then execs the real driver."""
        inner = (
            f"echo $$ > {self.pidfile}; "
            f"exec {sys.executable} -c 'import time; time.sleep(30)'"
        )
        child = subprocess.Popen(
            ["sh", "-c", inner], start_new_session=True
        )
        self.addCleanup(child.kill)
        driver_pid = int(_wait_for_file(self.pidfile))
        self.assertTrue(_pid_alive(driver_pid))
        ownership = DriverOwnership(kind="dtach", pidfile=self.pidfile)
        self.assertTrue(stop_owned_driver(ownership, child))
        self.assertFalse(_pid_alive(driver_pid))
        self.assertFalse(os.path.exists(self.pidfile))




class TestOwnedTreeCustody(unittest.TestCase):
    """Custody covers the whole owned group, not only the leader PID.

    A driver may exit while a descendant that ignores ``SIGTERM`` keeps running
    in the same owned process group. Reporting cancellation at that point would
    be a false success, so these tests assert the descendant is really gone.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="driver-ownership-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.record = os.path.join(self.tmpdir, "tree.json")

    def _spawn_leader_with_stubborn_descendant(self):
        """Start a leader that exits at once, leaving a SIGTERM-ignoring child."""
        leader = (
            "import json, os, subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', "
            "'import signal, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)'])\n"
            f"open({self.record!r}, 'w').write(json.dumps("
            "dict(leader=os.getpid(), desc=child.pid, pgid=os.getpgid(0))))\n"
            "time.sleep(0.2)\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", leader], start_new_session=True
        )
        self.addCleanup(child.kill)
        data = json.loads(_wait_for_file(self.record))
        child.wait(timeout=10)
        self.addCleanup(self._kill_exact, data["desc"])
        return child, data

    def _kill_exact(self, pid):
        """Kill one exact PID and log the deletion event."""
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            return
        print(f"[KILLED] exact pid {pid}")

    def test_leader_exit_with_stubborn_descendant_is_proven_dead(self):
        """The owned group must be emptied even after the leader exits."""
        child, data = self._spawn_leader_with_stubborn_descendant()
        self.assertFalse(_pid_alive(data["leader"]))
        self.assertTrue(_pid_alive(data["desc"]))
        self.assertTrue(stop_owned_driver(DriverOwnership(kind="raw"), child))
        self.assertFalse(_pid_alive(data["desc"]))

    def test_unstoppable_descendant_reports_unproven_custody(self):
        """When the group cannot be emptied, custody must be reported unproven."""
        child, data = self._spawn_leader_with_stubborn_descendant()
        with patch.object(driver_ownership, "_signal_group_pgid"):
            self.assertFalse(stop_owned_driver(DriverOwnership(kind="raw"), child))
        self.assertTrue(_pid_alive(data["desc"]))

    def test_observation_failure_with_undeliverable_signal_is_unproven(self):
        """An incomplete /proc scan must never be read as a proven-empty group.

        This is the reviewer's exact combination: ``stat`` reads fail with
        ``PermissionError`` while group signal delivery is disabled. The
        descendant is still alive, so custody must be reported unproven rather
        than claimed as a clean cancellation.
        """
        child, data = self._spawn_leader_with_stubborn_descendant()
        real_open = open

        def unreadable_stat(path, *args, **kwargs):
            if str(path).startswith("/proc/") and str(path).endswith("/stat"):
                raise PermissionError("injected proc observation unavailable")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=unreadable_stat), patch.object(
            driver_ownership, "_signal_group_pgid"
        ):
            self.assertFalse(stop_owned_driver(DriverOwnership(kind="raw"), child))
        self.assertTrue(_pid_alive(data["desc"]))

    def test_vanished_process_is_treated_as_gone_not_unknown(self):
        """A process that disappears mid-scan is a benign race, not unknown."""
        real_open = open

        def vanished_stat(path, *args, **kwargs):
            if str(path).startswith("/proc/") and str(path).endswith("/stat"):
                raise FileNotFoundError("process vanished")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=vanished_stat):
            self.assertEqual(driver_ownership._proc_group_members(os.getpid()), [])

    def test_unparseable_stat_record_is_unknown_not_empty(self):
        """A malformed stat record leaves the group state unknown."""
        real_open = open

        def malformed_stat(path, *args, **kwargs):
            if str(path).startswith("/proc/") and str(path).endswith("/stat"):
                return io.StringIO("garbage-without-expected-fields")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=malformed_stat):
            self.assertIsNone(driver_ownership._proc_group_members(os.getpid()))

    def test_unknown_observation_keeps_group_alive(self):
        """``_group_alive`` must not conclude empty from an incomplete scan."""
        pgid = os.getpgid(0)
        with patch.object(driver_ownership, "_proc_group_members", return_value=None):
            self.assertTrue(driver_ownership._group_alive(pgid))

    def test_structurally_invalid_stat_with_undeliverable_signal_is_unproven(self):
        """A record without PID and parenthesized comm must not exclude a member.

        This is the reviewer's exact malformed shape: ``S 0 999999999`` has no
        leading PID and no parenthesized command field, so it is not a valid
        ``/proc/PID/stat`` record. Reading it as "not a member of the target
        group" would prove an empty group while the descendant is still alive.
        """
        child, data = self._spawn_leader_with_stubborn_descendant()
        real_open = open

        def malformed_stat(path, *args, **kwargs):
            if str(path).startswith("/proc/") and str(path).endswith("/stat"):
                return io.StringIO("S 0 999999999")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=malformed_stat), patch.object(
            driver_ownership, "_signal_group_pgid"
        ):
            self.assertFalse(stop_owned_driver(DriverOwnership(kind="raw"), child))
        self.assertTrue(_pid_alive(data["desc"]))

    def test_comm_with_spaces_and_parentheses_is_parsed(self):
        """A real command name may contain spaces and parentheses."""
        parsed = driver_ownership._parse_proc_stat(
            "4242 (my (weird) proc) S 1 4242 4242 0 -1"
        )
        self.assertEqual(parsed, (4242, "S", 4242))

    def test_non_numeric_leading_pid_is_unknown(self):
        """The leading field must be the numeric PID."""
        self.assertIsNone(
            driver_ownership._parse_proc_stat("abc (comm) S 1 4242 4242")
        )

    def test_missing_closing_paren_is_unknown(self):
        """A record without a closing parenthesis is structurally invalid."""
        self.assertIsNone(
            driver_ownership._parse_proc_stat("4242 (comm S 1 4242 4242")
        )

    def test_record_pid_mismatch_is_unknown(self):
        """A record that does not describe the process it was read from is unknown."""
        real_open = open

        def mismatched_stat(path, *args, **kwargs):
            if str(path).startswith("/proc/") and str(path).endswith("/stat"):
                return io.StringIO("999999 (comm) S 1 999999 999999")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mismatched_stat):
            self.assertIsNone(driver_ownership._proc_group_members(os.getpid()))



class TestKernelOnlyProof(unittest.TestCase):
    """Absence of the owned group may come only from the kernel.

    ``/proc`` enumeration is a diagnostic aid, so no malformed or incomplete
    record can ever be converted into a proof that the group is gone. These
    tests pin that rule directly: the proof outcome must be identical for every
    enumeration defect while the kernel still reports the group as existing.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="driver-ownership-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _spawn_leader_with_stubborn_descendant(self):
        """Start a leader that exits at once, leaving a SIGTERM-ignoring child.

        Every call uses its own record and readiness paths, so a subTest can
        never observe a previous round's identities. The descendant writes its
        readiness marker only after installing ``SIG_IGN``, and the leader
        records the tree immediately after spawning it, so cleanup ownership is
        established before any fallible assertion runs.
        """
        token = uuid.uuid4().hex
        record = os.path.join(self.tmpdir, f"tree-{token}.json")
        ready = os.path.join(self.tmpdir, f"ready-{token}")
        descendant = (
            "import signal, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"open({ready!r}, 'w').write('ready')\n"
            "time.sleep(120)\n"
        )
        leader = (
            "import json, os, subprocess, sys, time\n"
            f"child = subprocess.Popen([sys.executable, '-c', {descendant!r}])\n"
            f"open({record!r}, 'w').write(json.dumps("
            "dict(leader=os.getpid(), desc=child.pid, pgid=os.getpgid(0))))\n"
            "deadline = time.monotonic() + 10\n"
            f"while not os.path.exists({ready!r}) and time.monotonic() < deadline:\n"
            "    time.sleep(0.01)\n"
            "time.sleep(0.2)\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", leader], start_new_session=True
        )
        # The leader leads its own session, so its PID is also the owned PGID.
        # Registering the group kill first guarantees the descendant cannot
        # outlive this test even when reading the record fails.
        self.addCleanup(self._kill_group_exact, child.pid)
        self.addCleanup(child.kill)
        data = json.loads(_wait_for_file(record))
        self.addCleanup(self._kill_exact, data["desc"])
        self.assertEqual(data["leader"], child.pid)
        _wait_for_file(ready)
        child.wait(timeout=10)
        return child, data

    def _kill_exact(self, pid):
        """Kill one exact PID and log the deletion event."""
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            return
        print(f"[KILLED] exact pid {pid}")

    def _kill_group_exact(self, pgid):
        """Kill one exact owned process group and log the deletion event."""
        try:
            os.killpg(pgid, 9)
        except ProcessLookupError:
            return
        except OSError:
            return
        print(f"[KILLED] exact pgid {pgid}")

    def test_malformed_shapes_cannot_prove_absence(self):
        """Every reviewer malformed shape must leave custody unproven.

        The kernel still reports the owned group as existing, so no enumeration
        defect may be read as proof of absence. Each shape gets a fresh record
        path and its own readiness marker, so the assertions and cleanup always
        target the tree created for that shape.
        """
        shapes = (
            "S 0 999999999",
            "4242 (comm)Z 0 999999999",
            "4242(comm) S 0 999999999",
            "4242 (comm) S garbage 999999999",
        )
        for shape in shapes:
            with self.subTest(shape=shape):
                child, data = self._spawn_leader_with_stubborn_descendant()
                real_open = open

                def malformed_stat(path, *args, **kwargs):
                    if str(path).startswith("/proc/") and str(path).endswith("/stat"):
                        return io.StringIO(shape)
                    return real_open(path, *args, **kwargs)

                with patch("builtins.open", side_effect=malformed_stat), patch.object(
                    driver_ownership, "_signal_group_pgid"
                ):
                    self.assertFalse(
                        stop_owned_driver(DriverOwnership(kind="raw"), child)
                    )
                self.assertTrue(_pid_alive(data["desc"]))

    def test_existing_group_with_empty_enumeration_is_alive(self):
        """A successful kernel probe wins over an empty enumeration."""
        pgid = os.getpgid(0)
        with patch.object(driver_ownership, "_proc_group_members", return_value=[]):
            self.assertTrue(driver_ownership._group_alive(pgid))

    def test_existing_group_with_unknown_enumeration_is_alive(self):
        """An unreadable enumeration must never be read as proven-empty."""
        pgid = os.getpgid(0)
        with patch.object(driver_ownership, "_proc_group_members", return_value=None):
            self.assertTrue(driver_ownership._group_alive(pgid))

    def test_enumeration_is_not_consulted_for_the_proof(self):
        """The proof must not depend on enumeration at all."""
        pgid = os.getpgid(0)
        with patch.object(
            driver_ownership, "_proc_group_members", side_effect=AssertionError(
                "enumeration must not gate the custody proof"
            )
        ):
            self.assertTrue(driver_ownership._group_alive(pgid))

    def test_kernel_esrch_is_the_only_proof_of_absence(self):
        """``ESRCH`` from the kernel is the only accepted proof of absence."""
        absent_pgid = 2_000_000_000
        self.assertFalse(driver_ownership._group_alive(absent_pgid))
        self.assertIs(driver_ownership._group_state(absent_pgid), False)

    def test_kernel_permission_error_is_unknown_not_gone(self):
        """An unanswerable kernel probe must be unknown, never gone."""
        pgid = os.getpgid(0)
        with patch.object(
            driver_ownership.os, "killpg", side_effect=PermissionError("denied")
        ):
            self.assertIsNone(driver_ownership._group_state(pgid))
            self.assertTrue(driver_ownership._group_alive(pgid))

    def test_kernel_unexpected_oserror_is_unknown_not_gone(self):
        """Any unexpected probe failure must be unknown, never gone."""
        pgid = os.getpgid(0)
        with patch.object(
            driver_ownership.os, "killpg", side_effect=OSError("unavailable")
        ):
            self.assertIsNone(driver_ownership._group_state(pgid))
            self.assertTrue(driver_ownership._group_alive(pgid))

    def test_diagnostic_description_reports_remaining_members(self):
        """The diagnostic names the surviving PIDs without gating the proof."""
        child, data = self._spawn_leader_with_stubborn_descendant()
        description = driver_ownership.describe_ownership(
            DriverOwnership(kind="raw"), child
        )
        self.assertIn(f"driver={data['leader']}", description)
        self.assertIn(str(data["desc"]), description)

@unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
class TestRealTmuxDriver(unittest.TestCase):
    """A driver running inside a real tmux server must be proven gone."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="driver-ownership-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.pidfile = os.path.join(self.tmpdir, "driver.pid")
        self.session = f"topsailai-ownership-test-{os.getpid()}"

    def tearDown(self):
        subprocess.run(
            ["tmux", "kill-session", "-t", f"={self.session}"],
            capture_output=True,
        )

    def test_tmux_driver_is_proven_dead(self):
        inner = (
            f"echo $$ > {self.pidfile}; "
            f"exec {sys.executable} -c 'import time; time.sleep(30)'"
        )
        child = subprocess.Popen(
            ["tmux", "new-session", "-d", "-s", self.session, "sh", "-c", inner]
        )
        self.addCleanup(child.kill)
        driver_pid = int(_wait_for_file(self.pidfile))
        self.assertTrue(_pid_alive(driver_pid))
        ownership = DriverOwnership(
            kind="tmux", pidfile=self.pidfile, session_name=self.session
        )
        self.assertTrue(stop_owned_driver(ownership, child))
        self.assertFalse(_pid_alive(driver_pid))


if __name__ == "__main__":
    unittest.main()
