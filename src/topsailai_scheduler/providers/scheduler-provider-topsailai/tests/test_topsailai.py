#!/usr/bin/env python3
"""Tests for the TopsailAI provider.

This project is independent of the scheduler, so its tests exercise only the
protocol and the upstream command lines it builds. Nothing here imports
scheduler code.

No real agent is launched. A stub executable stands in for `topsailai` and
records the arguments it receives, so the tests can assert the exact command
line and environment the provider produces without starting anything.

Run with:

    python3 tests/test_topsailai.py
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

# PROVIDER is the executable under test.
PROVIDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "scheduler-provider-topsailai")

# STUB is a stand-in for the topsailai executable. It records its arguments and
# environment, then prints the JSON document named by STUB_REPLY.
STUB = """#!/usr/bin/env python3
import json
import os
import sys

record = os.environ.get("STUB_RECORD")
if record:
    with open(record, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "argv": sys.argv[1:],
            "interactive": os.environ.get("TOPSAILAI_INTERACTIVE_MODE"),
            "task": os.environ.get("TOPSAILAI_TASK"),
            "extra": os.environ.get("TASK_EXTRA"),
        }) + "\\n")

reply = os.environ.get("STUB_REPLY")
if reply:
    sys.stdout.write(reply)
    sys.stdout.write("\\n")
sys.exit(int(os.environ.get("STUB_EXIT") or "0"))
"""


class TopsailAIProviderTest(unittest.TestCase):
    """Exercises the three protocol operations against a stub."""

    def setUp(self):
        """Create an isolated state folder and a stub executable."""
        self.state = tempfile.mkdtemp(prefix="topsailai-provider-test-")
        self.stub = os.path.join(self.state, "topsailai-stub")
        with open(self.stub, "w", encoding="utf-8") as handle:
            handle.write(STUB)
        os.chmod(self.stub, os.stat(self.stub).st_mode | stat.S_IEXEC)

        self.record = os.path.join(self.state, "calls.jsonl")
        self.environment = dict(os.environ)
        self.environment["TOPSAILAI_PROVIDER_STATE_DIR"] = self.state
        self.environment["TOPSAILAI_PROVIDER_BINARY"] = self.stub
        self.environment["STUB_RECORD"] = self.record

    def tearDown(self):
        """Remove the state folder."""
        shutil.rmtree(self.state, ignore_errors=True)

    def call(self, operation, document, reply=None, exit_code=0):
        """Run one protocol operation and return its decoded reply."""
        environment = dict(self.environment)
        if reply is not None:
            environment["STUB_REPLY"] = json.dumps(reply)
        environment["STUB_EXIT"] = str(exit_code)
        completed = subprocess.run(
            [PROVIDER, operation],
            input=json.dumps(document),
            capture_output=True,
            text=True,
            env=environment,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, "provider failed: %s" % completed.stderr)
        if not completed.stdout.strip():
            return None
        return json.loads(completed.stdout)

    def calls(self):
        """Return the recorded stub calls."""
        if not os.path.exists(self.record):
            return []
        with open(self.record, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def start(self, reply=None, document=None):
        """Start one run and return its receipt."""
        if document is None:
            document = {
                "protocol_version": 1,
                "task_id": "data/work",
                "task_path": "/tasks/data/work.md",
                "task_dir": "/tasks/data",
                "workspace": "/srv/project",
                "command": "",
                "args": [],
                "env": {},
                "timeout_ms": 0,
            }
        if reply is None:
            reply = {"ok": True, "session_id": "20261120120000", "pid": 4242}
        return self.call("start", document, reply=reply)

    def test_start_returns_a_run_id_and_session(self):
        """A start receipt must carry a run id, because poll needs one."""
        receipt = self.start()
        self.assertEqual(receipt["protocol_version"], 1)
        self.assertTrue(receipt["run_id"])
        self.assertEqual(receipt["pid"], 4242)

    def test_start_uses_raw_mode(self):
        """The launch must use raw mode, or the exit status is a wrapper's."""
        self.start()
        arguments = self.calls()[0]["argv"]
        self.assertIn("-m", arguments)
        self.assertEqual(arguments[arguments.index("-m") + 1], "raw")
        self.assertNotIn("dtach", arguments)
        self.assertNotIn("tmux", arguments)

    def test_start_requests_json_and_no_prompts(self):
        """The receipt must be JSON on stdout, and the launcher must not prompt."""
        self.start()
        arguments = self.calls()[0]["argv"]
        self.assertIn("--json", arguments)
        self.assertIn("--non-interactive", arguments)

    def test_start_does_not_use_the_task_flag(self):
        """The task must travel through the environment, not --task.

        Upstream --task writes the content to a temporary file and sets
        TOPSAILAI_TASK to that path, which would collide with the task path this
        provider supplies.
        """
        self.start()
        self.assertNotIn("--task", self.calls()[0]["argv"])

    def test_start_forces_non_interactive_agent_mode(self):
        """The agent's own mode must be forced, because --non-interactive does not.

        Upstream --non-interactive only stops the launcher prompting; the agent
        defaults to interactive, which would leave a run waiting for input that
        never comes.
        """
        self.start()
        self.assertEqual(self.calls()[0]["interactive"], "0")

    def test_start_passes_the_task_path(self):
        """The task content path must reach the agent."""
        self.start()
        self.assertEqual(self.calls()[0]["task"], "/tasks/data/work.md")

    def test_start_passes_the_workspace(self):
        """The workspace must be the folder the agent runs in."""
        self.start()
        self.assertEqual(self.calls()[0]["argv"][-1], "/srv/project")

    def test_task_environment_reaches_the_agent(self):
        """A task's own variables must reach the agent."""
        self.start(document={
            "protocol_version": 1,
            "task_id": "data/work",
            "task_path": "/tasks/data/work.md",
            "task_dir": "/tasks/data",
            "workspace": "/srv/project",
            "command": "",
            "args": [],
            "env": {"TASK_EXTRA": "carried"},
            "timeout_ms": 0,
        })
        self.assertEqual(self.calls()[0]["extra"], "carried")

    def test_task_cannot_switch_the_agent_back_to_interactive(self):
        """A task must not be able to break supervision through its own env."""
        self.start(document={
            "protocol_version": 1,
            "task_id": "data/work",
            "task_path": "/tasks/data/work.md",
            "task_dir": "/tasks/data",
            "workspace": "/srv/project",
            "command": "",
            "args": [],
            "env": {"TOPSAILAI_INTERACTIVE_MODE": "1"},
            "timeout_ms": 0,
        })
        self.assertEqual(self.calls()[0]["interactive"], "0")

    def test_start_without_a_session_id_fails(self):
        """A launch that reports no session cannot be supervised, so it must fail."""
        completed = subprocess.run(
            [PROVIDER, "start"],
            input=json.dumps({
                "protocol_version": 1,
                "task_id": "data/work",
                "task_path": "/tasks/data/work.md",
                "task_dir": "/tasks/data",
                "workspace": "/srv/project",
                "command": "",
                "args": [],
                "env": {},
                "timeout_ms": 0,
            }),
            capture_output=True,
            text=True,
            env=dict(self.environment, STUB_REPLY=json.dumps({"ok": True})),
            timeout=60,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("session_id", completed.stderr)

    def test_poll_reports_running_while_processing(self):
        """A processing session must be reported as running."""
        receipt = self.start()
        observation = self.call(
            "poll",
            {"protocol_version": 1, "run_id": receipt["run_id"]},
            reply={"ok": True, "state": "processing"},
        )
        self.assertEqual(observation["state"], "running")

    def test_poll_reports_finished_when_idle(self):
        """An idle session must be reported as finished."""
        receipt = self.start()
        observation = self.call(
            "poll",
            {"protocol_version": 1, "run_id": receipt["run_id"]},
            reply={"ok": True, "state": "idle"},
        )
        self.assertEqual(observation["state"], "finished")

    def test_poll_queries_the_session_status(self):
        """Poll must ask the session's lock-based state, not guess."""
        receipt = self.start()
        self.call(
            "poll",
            {"protocol_version": 1, "run_id": receipt["run_id"]},
            reply={"ok": True, "state": "processing"},
        )
        arguments = self.calls()[-1]["argv"]
        self.assertEqual(arguments[:2], ["session", "status"])
        self.assertIn("20261120120000", arguments)
        self.assertIn("--json", arguments)

    def test_poll_reports_unknown_for_an_unrecognised_state(self):
        """An unrecognised state must not be guessed as finished."""
        receipt = self.start()
        observation = self.call(
            "poll",
            {"protocol_version": 1, "run_id": receipt["run_id"]},
            reply={"ok": True, "state": "confused"},
        )
        self.assertEqual(observation["state"], "unknown")

    def test_poll_reports_unknown_for_an_unknown_run(self):
        """An unknown run must be reported as unknown."""
        observation = self.call("poll", {"protocol_version": 1, "run_id": "does-not-exist"})
        self.assertEqual(observation["state"], "unknown")

    def test_stop_interrupts_the_session(self):
        """Stop must interrupt the session it started."""
        receipt = self.start()
        self.call("stop", {"protocol_version": 1, "run_id": receipt["run_id"]}, reply={"ok": True})
        arguments = self.calls()[-1]["argv"]
        self.assertEqual(arguments[:3], ["runtime", "control", "hard_interrupt"])
        self.assertIn("20261120120000", arguments)
        self.assertIn("4242", arguments)

    def test_stop_of_an_unknown_run_succeeds(self):
        """Stopping a run the provider lost must not fail."""
        self.call("stop", {"protocol_version": 1, "run_id": "does-not-exist"})

    def test_unknown_operation_fails(self):
        """An unknown operation must fail rather than exit zero."""
        completed = subprocess.run(
            [PROVIDER, "explode"],
            input="{}",
            capture_output=True,
            text=True,
            env=self.environment,
            timeout=60,
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
            timeout=60,
        )
        self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
