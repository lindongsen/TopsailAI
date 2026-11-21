"""Shared harness for the scheduler's BDD suite.

One Session is one daemon in one temporary workspace. Every scenario gets its
own, so scenarios cannot influence each other through a shared task tree, a
shared lock file or a shared provider state folder.

The harness drives the real binary: a real daemon in a tmux session, the real
CLI over the real control socket, and the real provider protocol through the
mock provider. Nothing inside the scheduler is mocked, so a passing scenario is
evidence about the shipped binary rather than about a test double.
"""

import glob
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time

# PROJECT_ROOT is the repository root, derived from this file's location.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# BINARY is the scheduler built by the Makefile.
BINARY = os.path.join(PROJECT_ROOT, ".tmp", "topsailai_scheduler")
# MOCK_PROVIDER is the mock provider executable the daemon runs by default.
MOCK_PROVIDER = os.path.join(PROJECT_ROOT, "providers", "mock", "bin", "mock")


def quote(value):
    """Quote one shell word."""
    return "'" + str(value).replace("'", "'\\''") + "'"


class Session:
    """One daemon in one temporary workspace."""

    def __init__(self, overrides=None):
        """Create the workspace and start the daemon.

        overrides replaces individual daemon settings for this scenario. A
        scenario that exercises a daemon-wide knob such as the concurrency limit
        or the shutdown grace cannot change it through a task file, so the knob
        is set here and the daemon is started with it.
        """
        self.workspace = tempfile.mkdtemp(prefix="sched-bdd-")
        self.tasks_root = os.path.join(self.workspace, "tasks")
        self.state_dir = os.path.join(self.workspace, "mock-state")
        self.log_path = os.path.join(self.workspace, "daemon.log")
        self.exit_path = os.path.join(self.workspace, "daemon.exit")
        self.session_name = "sched-bdd-%d" % os.getpid()
        self.overrides = dict(overrides or {})
        self.last_output = ""
        self.last_error = ""
        self.last_code = 0
        os.makedirs(self.tasks_root, exist_ok=True)
        os.makedirs(self.state_dir, exist_ok=True)
        self.start_daemon()

    # ---------------------------------------------------------------- daemon
    def _stop_previous_daemon(self):
        """Stop the daemon this session already started, and wait for it to go.

        tmux kill-session sends SIGHUP, which the daemon does not trap, so it
        dies without removing its control socket. A new daemon in the same
        workspace then finds a socket that still answers and refuses to start,
        because starting beside a live scheduler is exactly what it must not do.
        Waiting for the old process to disappear keeps the restart honest.
        """
        pid = self.daemon_pid()
        subprocess.run(["tmux", "kill-session", "-t", self.session_name],
                       capture_output=True, text=True)
        if pid is not None:
            wait_for_pid_gone(pid, timeout=20)

    def start_daemon(self):
        """Start the daemon inside tmux and wait until it answers."""
        self._stop_previous_daemon()
        environment = {
            "SCHEDULER_TASKS_ROOT": self.tasks_root,
            "SCHEDULER_CONTROL_SOCKET": os.path.join(self.workspace, "scheduler.sock"),
            "SCHEDULER_LOG_OUTPUT": self.log_path,
            "SCHEDULER_LOG_LEVEL": "debug",
            "SCHEDULER_RESCAN_INTERVAL": "1s",
            "SCHEDULER_SHUTDOWN_GRACE": "5s",
            "SCHEDULER_DEFAULT_TIMEOUT": "30s",
            "SCHEDULER_DEFAULT_PROVIDER_PATH": MOCK_PROVIDER,
            "SCHEDULER_POLL_INTERVAL": "100ms",
            "MOCK_PROVIDER_STATE_DIR": self.state_dir,
        }
        # A scenario-level override wins over the harness default, so a scenario
        # can exercise a daemon-wide knob without a second harness.
        environment.update(self.overrides)
        exports = " ".join("%s=%s" % (key, quote(value)) for key, value in environment.items())
        command = "cd %s && %s %s run; echo $? > %s" % (
            quote(self.workspace), exports, quote(BINARY), quote(self.exit_path))
        subprocess.run(["tmux", "new-session", "-d", "-s", self.session_name, command],
                       capture_output=True, text=True, check=True)

        deadline = time.time() + 20
        while time.time() < deadline:
            if self.cli("status").returncode == 0:
                return
            time.sleep(0.1)
        raise RuntimeError("the daemon did not become ready; log: %s" % self.read_log())

    def daemon_pid(self):
        """Return the daemon's pid, or None.

        The pattern is anchored to the exact command line on purpose. An
        unanchored pattern also matches the tmux wrapper whose command line
        merely contains that string, and the wrapper appears first.
        """
        result = subprocess.run(["pgrep", "-f", "^%s run$" % BINARY],
                                capture_output=True, text=True)
        for line in result.stdout.split():
            if line.strip().isdigit():
                return int(line.strip())
        return None

    def kill_daemon(self):
        """Kill the daemon without letting it clean up.

        SIGKILL, not SIGTERM: a graceful stop clears the lock record, and the
        record is exactly what a restart has to reconcile.
        """
        pid = self.daemon_pid()
        if pid is None:
            raise AssertionError("the daemon pid was not found")
        os.kill(pid, signal.SIGKILL)
        deadline = time.time() + 10
        while time.time() < deadline:
            if not _pid_alive(pid):
                return pid
            time.sleep(0.05)
        raise AssertionError("the daemon survived SIGKILL")

    def terminate_daemon(self, timeout=30):
        """Ask the daemon to stop gracefully and report how long it took.

        SIGTERM, unlike kill_daemon's SIGKILL, lets the daemon drain its runs.
        The elapsed time is returned because a drain that waits for a run is
        only observable as a duration: the run's own exit status is written by
        the provider, not by the daemon.
        """
        pid = self.daemon_pid()
        if pid is None:
            raise AssertionError("the daemon pid was not found")
        started = time.time()
        os.kill(pid, signal.SIGTERM)
        deadline = started + timeout
        while time.time() < deadline:
            if not _pid_alive(pid):
                return time.time() - started
            time.sleep(0.05)
        raise AssertionError("the daemon did not stop within %ss" % timeout)

    def wait_for_daemon_exit(self, timeout=30):
        """Wait until the daemon wrote its exit status."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(self.exit_path) and os.path.getsize(self.exit_path) > 0:
                with open(self.exit_path, "r", encoding="utf-8") as handle:
                    return int((handle.read() or "0").strip() or "0")
            time.sleep(0.05)
        raise AssertionError("the daemon wrote no exit status within %ss" % timeout)

    def reconfigure(self, overrides):
        """Restart the daemon with different settings.

        A daemon-wide knob such as the concurrency limit is read once at startup
        and cannot be changed through a task file, so a scenario that exercises
        one restarts the daemon with it. The tasks root and the provider state
        folder are kept, so a task written before the restart stays visible.
        """
        self.overrides = dict(overrides)
        self.start_daemon()

    def restart_daemon(self):
        """Start a fresh daemon in the same workspace."""
        self.start_daemon()

    def read_log(self):
        """Return the daemon log."""
        try:
            with open(self.log_path, "r", encoding="utf-8") as handle:
                return handle.read()
        except OSError:
            return ""

    def wait_for_log(self, pattern, timeout=20):
        """Wait until the daemon log contains a pattern."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pattern in self.read_log():
                return True
            time.sleep(0.1)
        return False

    def wait_for_log_count(self, pattern, count, timeout=30):
        """Wait until the daemon log contains a pattern at least count times."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.read_log().count(pattern) >= count:
                return True
            time.sleep(0.1)
        return False

    # ------------------------------------------------------------------- cli

    def cli(self, *arguments):
        """Run the CLI inside the workspace so it finds the same socket."""
        result = subprocess.run([BINARY] + list(arguments), cwd=self.workspace,
                                capture_output=True, text=True, timeout=180)
        self.last_code = result.returncode
        self.last_output = result.stdout
        self.last_error = result.stderr
        return result

    def status_json(self):
        """Return the status snapshot, or None when it cannot be read."""
        result = self.cli("status", "--json")
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except ValueError:
            return None

    # ----------------------------------------------------------------- tasks

    def write_task(self, task_id, yaml_content, markdown_content):
        """Write the YAML and Markdown files of one task."""
        folder = os.path.dirname(os.path.join(self.tasks_root, task_id))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(self.tasks_root, task_id + ".yaml"), "w", encoding="utf-8") as handle:
            handle.write(yaml_content)
        with open(os.path.join(self.tasks_root, task_id + ".md"), "w", encoding="utf-8") as handle:
            handle.write(markdown_content)

    def write_yaml_only(self, task_id, yaml_content):
        """Write only the YAML file of one task."""
        folder = os.path.dirname(os.path.join(self.tasks_root, task_id))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(self.tasks_root, task_id + ".yaml"), "w", encoding="utf-8") as handle:
            handle.write(yaml_content)

    def remove_task(self, task_id):
        """Delete the files of one task."""
        for suffix in (".yaml", ".md"):
            path = os.path.join(self.tasks_root, task_id + suffix)
            if os.path.exists(path):
                os.remove(path)

    def wait_for_discovery(self, task_id, timeout=20):
        """Wait until the daemon has discovered a task.

        A task written after the daemon started is only visible after the next
        rescan, so a launch issued immediately would fail with "task not found".
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            snapshot = self.status_json()
            if snapshot:
                for task in snapshot.get("tasks") or []:
                    if task.get("id") == task_id:
                        return task
            time.sleep(0.1)
        raise AssertionError("task %r was not discovered within %ss" % (task_id, timeout))

    def wait_for_absent(self, task_id, timeout=20):
        """Wait until the daemon no longer reports a task."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            snapshot = self.status_json()
            if snapshot is not None:
                ids = [task.get("id") for task in snapshot.get("tasks") or []]
                if task_id not in ids:
                    return
            time.sleep(0.1)
        raise AssertionError("task %r was still reported after %ss" % (task_id, timeout))

    def wait_for_state(self, task_id, state, timeout=20):
        """Wait until a task reports a state."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            snapshot = self.status_json()
            if snapshot:
                for task in snapshot.get("tasks") or []:
                    if task.get("id") == task_id and task.get("state") == state:
                        return task
            time.sleep(0.1)
        raise AssertionError("task %r never reported state %r" % (task_id, state))

    def task_status(self, task_id):
        """Return one task's status entry, or None."""
        snapshot = self.status_json()
        if not snapshot:
            return None
        for task in snapshot.get("tasks") or []:
            if task.get("id") == task_id:
                return task
        return None

    # -------------------------------------------------------------- provider

    def run_ids_for(self, task_id):
        """Return every provider run id recorded for a task, oldest first."""
        found = []
        for path in glob.glob(os.path.join(self.state_dir, "*.request.json")):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    document = json.load(handle)
            except (OSError, ValueError):
                continue
            if document.get("task_id") != task_id:
                continue
            run_id = os.path.basename(path)[: -len(".request.json")]
            found.append((os.path.getmtime(path), run_id))
        found.sort(key=lambda pair: pair[0])
        return [run_id for _, run_id in found]

    def requests_for(self, task_id):
        """Return every request document recorded for a task, oldest first."""
        documents = []
        for run_id in self.run_ids_for(task_id):
            path = os.path.join(self.state_dir, run_id + ".request.json")
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    documents.append(json.load(handle))
            except (OSError, ValueError):
                continue
        return documents

    def request_for(self, task_id):
        """Return the newest request document recorded for a task."""
        documents = self.requests_for(task_id)
        assert documents, "no request was recorded for task %r" % task_id
        return documents[-1]

    def wait_for_request(self, task_id, timeout=20):
        """Wait until a request document exists for a task."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.requests_for(task_id):
                return self.request_for(task_id)
            time.sleep(0.1)
        raise AssertionError("no request was recorded for task %r within %ss" % (task_id, timeout))

    def output_for_run(self, run_id):
        """Return the output a run produced."""
        path = os.path.join(self.state_dir, run_id + ".out")
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError:
            return ""

    def wait_for_run_exit(self, run_id, timeout=30):
        """Wait until a run wrote its exit status."""
        path = os.path.join(self.state_dir, run_id + ".exit")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return
            time.sleep(0.1)
        raise AssertionError("run %s wrote no exit status within %ss" % (run_id, timeout))

    # ------------------------------------------------------------------ lock

    def lock_path(self, task_id):
        """Return the lock file path of a task."""
        return os.path.join(self.tasks_root, task_id + ".lock")

    def read_lock_record(self, task_id):
        """Return the lock record of a task, or an empty dict."""
        try:
            with open(self.lock_path(task_id), "r", encoding="utf-8") as handle:
                content = handle.read().strip()
        except OSError:
            return {}
        if not content:
            return {}
        try:
            return json.loads(content)
        except ValueError:
            return {}

    def wait_for_lock_record(self, task_id, timeout=20):
        """Wait until the lock file carries a record naming a run."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            record = self.read_lock_record(task_id)
            if record.get("run_id"):
                return record
            time.sleep(0.1)
        raise AssertionError("task %r wrote no lock record within %ss" % (task_id, timeout))

    def wait_for_request_count(self, task_id, count, timeout=30):
        """Wait until a task has at least count recorded requests."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if len(self.run_ids_for(task_id)) >= count:
                return len(self.run_ids_for(task_id))
            time.sleep(0.1)
        raise AssertionError("task %r recorded %d requests, wanted %d within %ss"
                             % (task_id, len(self.run_ids_for(task_id)), count, timeout))

    def wait_for_request_growth(self, task_id, baseline, timeout=30):
        """Wait until a task records more requests than a baseline count."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            current = len(self.run_ids_for(task_id))
            if current > baseline:
                return current
            time.sleep(0.1)
        raise AssertionError("task %r recorded no new request beyond %d within %ss"
                             % (task_id, baseline, timeout))

    # --------------------------------------------------------------- cleanup

    def stop(self):
        """Stop the daemon and remove the workspace."""
        subprocess.run(["tmux", "kill-session", "-t", self.session_name],
                       capture_output=True, text=True)
        shutil.rmtree(self.workspace, ignore_errors=True)


def _pid_alive(pid):
    """Report whether a process exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_pid_gone(pid, timeout=20):
    """Wait until a process no longer exists."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    raise AssertionError("pid %d was still alive after %ss" % (pid, timeout))
