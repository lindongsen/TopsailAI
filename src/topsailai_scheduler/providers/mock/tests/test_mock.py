#!/usr/bin/env python3
"""Tests for the mock provider.

This project is independent of the scheduler, so its tests exercise only the
protocol: one JSON document in, one JSON document out, and the lifecycle facts
the scheduler relies on. Nothing here imports scheduler code.

Run with:

    python3 tests/test_mock.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

# PROVIDER is the executable under test.
PROVIDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "mock")


class MockProviderTest(unittest.TestCase):
    """Exercises the three protocol operations."""

    def setUp(self):
        """Create an isolated state folder so runs cannot collide."""
        self.state = tempfile.mkdtemp(prefix="mock-provider-test-")
        self.environment = dict(os.environ)
        self.environment["MOCK_PROVIDER_STATE_DIR"] = self.state

    def tearDown(self):
        """Remove the state folder and any process it recorded."""
        for name in os.listdir(self.state):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.state, name), "r", encoding="utf-8") as handle:
                    record = json.load(handle)
            except (OSError, ValueError):
                continue
            pid = int(record.get("pid") or 0)
            if pid > 0:
                try:
                    os.killpg(pid, 9)
                except OSError:
                    pass
        shutil.rmtree(self.state, ignore_errors=True)

    def call(self, operation, document):
        """Run one protocol operation and return its decoded reply."""
        completed = subprocess.run(
            [PROVIDER, operation],
            input=json.dumps(document),
            capture_output=True,
            text=True,
            env=self.environment,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, "provider failed: %s" % completed.stderr)
        if not completed.stdout.strip():
            return None
        return json.loads(completed.stdout)

    def start(self, command="/bin/sh", args=None, workspace="/tmp"):
        """Start one run and return its receipt."""
        return self.call("start", {
            "protocol_version": 1,
            "task_id": "test/task",
            "task_path": "/tmp/test.md",
            "task_dir": "/tmp",
            "workspace": workspace,
            "command": command,
            "args": args or [],
            "env": {},
            "timeout_ms": 0,
        })

    def test_start_returns_a_run_id(self):
        """A start receipt must carry a run id, because poll needs one."""
        receipt = self.start(args=["-c", "sleep 5"])
        self.assertEqual(receipt["protocol_version"], 1)
        self.assertTrue(receipt["run_id"])
        self.assertGreater(receipt["pid"], 0)

    def test_poll_reports_running_while_alive(self):
        """A live run must be reported as running, not finished."""
        receipt = self.start(args=["-c", "sleep 30"])
        observation = self.call("poll", {"protocol_version": 1, "run_id": receipt["run_id"]})
        self.assertEqual(observation["state"], "running")

    def test_poll_reports_finished_with_the_exit_code(self):
        """A completed run must report the exit status it produced."""
        receipt = self.start(args=["-c", "exit 7"])
        deadline = time.time() + 10
        observation = None
        while time.time() < deadline:
            observation = self.call("poll", {"protocol_version": 1, "run_id": receipt["run_id"]})
            if observation["state"] == "finished":
                break
            time.sleep(0.1)
        self.assertEqual(observation["state"], "finished")
        self.assertEqual(observation["exit_code"], 7)

    def test_poll_reports_unknown_for_an_unknown_run(self):
        """An unknown run must be reported as unknown, never guessed."""
        observation = self.call("poll", {"protocol_version": 1, "run_id": "does-not-exist"})
        self.assertEqual(observation["state"], "unknown")

    def test_stop_ends_the_run(self):
        """A stop must end the run and the following poll must say finished."""
        receipt = self.start(args=["-c", "sleep 30"])
        self.call("stop", {"protocol_version": 1, "run_id": receipt["run_id"]})
        deadline = time.time() + 10
        observation = None
        while time.time() < deadline:
            observation = self.call("poll", {"protocol_version": 1, "run_id": receipt["run_id"]})
            if observation["state"] == "finished":
                break
            time.sleep(0.1)
        self.assertEqual(observation["state"], "finished")

    def test_stop_of_an_unknown_run_succeeds(self):
        """Stopping a run the provider lost must not fail, or a stop is impossible."""
        self.call("stop", {"protocol_version": 1, "run_id": "does-not-exist"})

    def test_start_without_a_command_simulates_a_run(self):
        """The agent launcher leaves the command to the provider."""
        receipt = self.start(command="")
        self.assertTrue(receipt["run_id"])

    def test_workspace_is_honoured(self):
        """The run must execute in the workspace the scheduler names."""
        folder = tempfile.mkdtemp(prefix="mock-provider-workspace-")
        try:
            receipt = self.start(args=["-c", "pwd > %s/pwd.txt" % folder], workspace=folder)
            deadline = time.time() + 10
            while time.time() < deadline:
                observation = self.call("poll", {"protocol_version": 1, "run_id": receipt["run_id"]})
                if observation["state"] == "finished":
                    break
                time.sleep(0.1)
            with open(os.path.join(folder, "pwd.txt"), "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read().strip(), folder)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_environment_is_passed_to_the_run(self):
        """A task's own environment must reach the run."""
        receipt = self.call("start", {
            "protocol_version": 1,
            "task_id": "test/task",
            "task_path": "/tmp/test.md",
            "task_dir": "/tmp",
            "workspace": "/tmp",
            "command": "/bin/sh",
            "args": ["-c", "printf '%s' \"$MOCK_EXTRA\" > " + os.path.join(self.state, "env.txt")],
            "env": {"MOCK_EXTRA": "carried"},
            "timeout_ms": 0,
        })
        deadline = time.time() + 10
        while time.time() < deadline:
            observation = self.call("poll", {"protocol_version": 1, "run_id": receipt["run_id"]})
            if observation["state"] == "finished":
                break
            time.sleep(0.1)
        with open(os.path.join(self.state, "env.txt"), "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "carried")

    def test_unknown_operation_fails(self):
        """An unknown operation must fail rather than exit zero."""
        completed = subprocess.run(
            [PROVIDER, "explode"],
            input="{}",
            capture_output=True,
            text=True,
            env=self.environment,
            timeout=30,
        )
        self.assertNotEqual(completed.returncode, 0)

    def test_missing_request_fails(self):
        """An empty request must fail rather than invent a run."""
        completed = subprocess.run(
            [PROVIDER, "start"],
            input="",
            capture_output=True,
            text=True,
            env=self.environment,
            timeout=30,
        )
        self.assertNotEqual(completed.returncode, 0)


    def wait_finished(self, run_id, timeout=10):
        """Poll until the run reports finished, returning the observation."""
        deadline = time.time() + timeout
        observation = None
        while time.time() < deadline:
            observation = self.call("poll", {"protocol_version": 1, "run_id": run_id})
            if observation["state"] == "finished":
                return observation
            time.sleep(0.05)
        self.fail("run %s did not finish within %ss: %r" % (run_id, timeout, observation))

    def read_record(self, run_id):
        """Return the run record the provider persisted."""
        with open(os.path.join(self.state, "%s.json" % run_id), "r", encoding="utf-8") as handle:
            return json.load(handle)

    def read_request(self, run_id):
        """Return the wire document the provider received."""
        with open(os.path.join(self.state, "%s.request.json" % run_id), "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_the_wire_request_is_recorded_verbatim(self):
        """Every field the scheduler sends must be recoverable afterwards.

        The record is the provider's summary; the request file is the evidence.
        Without it a field the provider ignores could not be verified at all.
        """
        receipt = self.call("start", {
            "protocol_version": 1,
            "task_id": "data/work",
            "task_path": "/tasks/data/work.md",
            "task_dir": "/tasks/data",
            "workspace": "/tmp",
            "command": "/bin/sh",
            "args": ["-c", "true"],
            "env": {"EXTRA": "value"},
            "timeout_ms": 1800000,
        })
        request = self.read_request(receipt["run_id"])
        self.assertEqual(request["protocol_version"], 1)
        self.assertEqual(request["task_id"], "data/work")
        self.assertEqual(request["task_path"], "/tasks/data/work.md")
        self.assertEqual(request["task_dir"], "/tasks/data")
        self.assertEqual(request["workspace"], "/tmp")
        self.assertEqual(request["command"], "/bin/sh")
        self.assertEqual(request["args"], ["-c", "true"])
        self.assertEqual(request["env"], {"EXTRA": "value"})
        self.assertEqual(request["timeout_ms"], 1800000)

    def test_the_record_captures_the_invocation(self):
        """The record must expose the argv the run actually received."""
        receipt = self.start(command="/bin/sh", args=["-c", "true"])
        record = self.read_record(receipt["run_id"])
        self.assertEqual(record["command"], "/bin/sh")
        self.assertEqual(record["args"], ["-c", "true"])
        self.assertEqual(record["argv"], ["/bin/sh", "-c", "true"])

    def test_the_record_captures_task_identity_and_timeout(self):
        """Task identity and the timeout must be visible without the wire file."""
        receipt = self.call("start", {
            "protocol_version": 1,
            "task_id": "nested/deep/task",
            "task_path": "/tasks/nested/deep/task.md",
            "task_dir": "/tasks/nested/deep",
            "workspace": "/tmp",
            "command": "/bin/sh",
            "args": ["-c", "true"],
            "env": {},
            "timeout_ms": 2500,
        })
        record = self.read_record(receipt["run_id"])
        self.assertEqual(record["task_id"], "nested/deep/task")
        self.assertEqual(record["task_path"], "/tasks/nested/deep/task.md")
        self.assertEqual(record["task_dir"], "/tasks/nested/deep")
        self.assertEqual(record["timeout_ms"], 2500)

    def test_the_record_captures_the_environment(self):
        """The task's own environment must be recorded, not only applied."""
        receipt = self.call("start", {
            "protocol_version": 1,
            "task_id": "test/task",
            "task_path": "/tmp/test.md",
            "task_dir": "/tmp",
            "workspace": "/tmp",
            "command": "/bin/sh",
            "args": ["-c", "true"],
            "env": {"ALPHA": "1", "BETA": "two"},
            "timeout_ms": 0,
        })
        record = self.read_record(receipt["run_id"])
        self.assertEqual(record["env"], {"ALPHA": "1", "BETA": "two"})

    def test_an_unsupported_protocol_version_is_refused(self):
        """A future revision must be refused, never silently misread."""
        completed = subprocess.run(
            [PROVIDER, "start"],
            input=json.dumps({
                "protocol_version": 99,
                "task_id": "test/task",
                "command": "/bin/sh",
                "args": ["-c", "true"],
            }),
            capture_output=True,
            text=True,
            env=self.environment,
            timeout=30,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("protocol_version", completed.stderr)

    def test_a_missing_protocol_version_is_refused(self):
        """The version is required, so an absent one is not assumed to be current."""
        completed = subprocess.run(
            [PROVIDER, "start"],
            input=json.dumps({"task_id": "test/task", "command": "/bin/sh"}),
            capture_output=True,
            text=True,
            env=self.environment,
            timeout=30,
        )
        self.assertNotEqual(completed.returncode, 0)

    def test_a_non_object_environment_is_refused(self):
        """A malformed env must fail rather than be silently dropped."""
        completed = subprocess.run(
            [PROVIDER, "start"],
            input=json.dumps({
                "protocol_version": 1,
                "task_id": "test/task",
                "command": "/bin/sh",
                "args": ["-c", "true"],
                "env": ["NOT", "AN", "OBJECT"],
            }),
            capture_output=True,
            text=True,
            env=self.environment,
            timeout=30,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("env", completed.stderr)

    def test_a_non_list_args_is_refused(self):
        """A malformed args must fail rather than be silently dropped."""
        completed = subprocess.run(
            [PROVIDER, "start"],
            input=json.dumps({
                "protocol_version": 1,
                "task_id": "test/task",
                "command": "/bin/sh",
                "args": "-c true",
            }),
            capture_output=True,
            text=True,
            env=self.environment,
            timeout=30,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("args", completed.stderr)

    def test_an_empty_command_is_recorded_as_the_simulated_one(self):
        """The agent launcher sends no command, so the record must show what ran."""
        receipt = self.start(command="")
        record = self.read_record(receipt["run_id"])
        self.assertEqual(record["command"], "/bin/true")
        self.assertEqual(self.read_request(receipt["run_id"])["command"], "")

if __name__ == "__main__":
    unittest.main(verbosity=2)
