"""Owned raw-resume process fixtures and independent identity observations."""

from __future__ import annotations

import ast
import inspect
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import cli_topsailai.agent_launch_background as background
from cli_topsailai import project_scope


class Custody:
    """Track supervisor and driver custody without masking production results."""

    def __init__(self, root: Path) -> None:
        """Create an exclusively owned fixture tree."""
        self.root = root
        self.home = root / "home"
        self.workspace = root / "workspace"
        self.home.mkdir(parents=True)
        self.workspace.mkdir()
        (self.home / "workspace" / "task").mkdir(parents=True)
        self.supervisors: list[subprocess.Popen[Any]] = []
        self.supervisor_tokens: dict[int, int] = {}
        self.drivers: list[tuple[int, int]] = []
        self.events: list[str] = []
        self.frames: list[dict[str, Any]] = []
        self.observed_frames: list[dict[str, Any]] = []
        self.held_submitted_archive: list[dict[str, Any]] = []
        self.ownership: Any | None = None
        self.telemetry = self.workspace / "telemetry.json"
        self.heartbeat = self.workspace / "heartbeat"
        self.release = self.workspace / "release"
        self.entrypoint = self._write_role("supervisor.py", _SUPERVISOR)
        self.driver = self._write_role("topsailai_agent_chats", _DRIVER)
        self.u2_marker = self.root / "u2-hook-marker.log"
        self.u3_marker = self.root / "u3-hook-marker.log"
        self.u4_marker = self.root / "u4-hook-marker.log"
        self.u3_original_cleanup: dict[str, Any] | None = None
        self.u3_received_cleanup: dict[str, Any] | None = None
        self.u3_receiver_frame: Mapping[str, Any] | None = None
        self.u3_transformations = 0
        self.u3_omissions = 0
        self.u4_original_cleanup: dict[str, Any] | None = None
        self.u4_received_cleanup: dict[str, Any] | None = None
        self.u4_receiver_frame: Mapping[str, Any] | None = None
        self.u4_transformations = 0
        self.u4_omissions = 0
        self.u5_marker = self.root / "u5-hook-marker.log"
        self.u5_original_cleanup: dict[str, Any] | None = None
        self.u5_received_cleanup: dict[str, Any] | None = None
        self.u5_receiver_frame: Mapping[str, Any] | None = None
        self.u5_transformations = 0
        self.u5_omissions = 0
        self.u5_validator_calls: list[dict[str, Any]] = []
        self.finished = False
        self.return_state: dict[str, Any] | None = None
        self._original_cwd = os.getcwd()
        self._original_environment = os.environ.copy()
        self.production_entry_cwd: str | None = None
        self.production_entry_environment: dict[str, str] | None = None

    def _write_role(self, name: str, content: str) -> Path:
        """Write one executable role below the fixture root."""
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        return path

    def spawn(self, *args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
        """Register the real supervisor immediately after Popen returns."""
        child = subprocess.Popen(*args, **kwargs)
        self.supervisors.append(child)
        token = self.identity_token(child.pid)
        if token is not None:
            self.supervisor_tokens[child.pid] = token
        self.events.append(f"registered supervisor pid={child.pid}")
        return child

    def environment(self, session: str) -> dict[str, str]:
        """Build the isolated environment inherited by the real driver."""
        env = os.environ.copy()
        env.update({
            "TOPSAILAI_HOME": str(self.home),
            "PYTHONPATH": str(Path(__file__).resolve().parents[3]),
            "SESSION_ID": session,
            "TOPSAILAI_SESSION_ID": session,
            "FIXTURE_TELEMETRY": str(self.telemetry),
            "FIXTURE_HEARTBEAT": str(self.heartbeat),
            "FIXTURE_RELEASE": str(self.release),
            "FIXTURE_MODEL": "c2-model",
            "PATH": f"{self.root}{os.pathsep}{env.get('PATH', '')}",
        })
        return env

    @staticmethod
    def identity_token(pid: int) -> int | None:
        """Read Linux proc starttime field 22 without treating errors as absence."""
        try:
            raw = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
            rest = raw[raw.rindex(")") + 2:].split()
            return int(rest[19])
        except (OSError, IndexError, ValueError):
            return None

    def register_driver(self, pid: int, token: int) -> None:
        """Register driver custody independently from supervisor custody."""
        record = (int(pid), int(token))
        if record not in self.drivers:
            self.drivers.append(record)
            self.events.append(f"registered driver pid={record[0]} token={record[1]}")

    def register_driver_from_telemetry(self) -> None:
        """Recover custody from already-observable telemetry on an error path."""
        if not self.telemetry.exists():
            self.events.append("driver custody unknown: telemetry unavailable")
            return
        try:
            data = json.loads(self.telemetry.read_text(encoding="utf-8"))
            self.register_driver(int(data["pid"]), int(data["token"]))
            self.events.append("registered driver from telemetry fallback")
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self.events.append(f"driver custody unknown: telemetry parse failed: {error}")

    def wait_for(self, path: Path, timeout: float = 5.0) -> dict[str, Any]:
        """Wait for child telemetry without deleting child-controlled files."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            time.sleep(0.01)
        raise AssertionError(f"timed out waiting for {path}")

    @staticmethod
    def process_state(
        pid: int,
        token: int,
        read_stat: Any | None = None,
    ) -> str:
        """Return alive, replaced, absent, or unknown from an injectable kernel read."""
        reader = read_stat or Path(f"/proc/{pid}/stat").read_text
        try:
            raw = reader(encoding="utf-8") if read_stat is None else reader(pid)
            rest = raw[raw.rindex(")") + 2:].split()
            if rest[0] == "Z":
                return "unknown"
            current = int(rest[19])
            return "alive" if current == token else "replaced"
        except FileNotFoundError:
            return "absent"
        except (OSError, IndexError, ValueError):
            return "unknown"

    @staticmethod
    def signal_if_alive(
        pid: int,
        token: int,
        read_stat: Any,
        signal: Any,
    ) -> None:
        """Signal only after the exact identity has been re-confirmed."""
        if Custody.process_state(pid, token, read_stat) == "alive":
            signal(pid)
    def live(self, pid: int, token: int) -> bool:
        """Require an independently observed live, non-zombie exact identity."""
        return self.process_state(pid, token) == "alive"

    def absent(self, pid: int, token: int) -> bool:
        """Require definitive kernel disappearance, never replacement or unknown."""
        return self.process_state(pid, token) == "absent"

    def capture_return_state(self) -> None:
        """Capture state at production return before any restoration fallback."""
        environment = dict(os.environ)
        environment.pop("PYTEST_CURRENT_TEST", None)
        expected = dict(self.production_entry_environment or {})
        expected.pop("PYTEST_CURRENT_TEST", None)
        self.return_state = {
            "cwd": os.getcwd(),
            "environment": environment,
            "expected_cwd": self.production_entry_cwd,
            "expected_environment": expected,
        }
        self.events.append("captured production return state before restore")

    def release_child(self) -> None:
        """Release the child only after all acceptance evidence is captured."""
        if not self.release.exists():
            self.release.write_text("release\n", encoding="utf-8")
            self.events.append("released child after evidence")

    def finish(self, *, read_stat: Any | None = None, signal: Any | None = None) -> None:
        """Attempt every wait/check and preserve evidence before any failure."""
        if self.finished:
            return
        self.release_child()
        failures: list[str] = []
        timed_out_supervisors: list[subprocess.Popen[Any]] = []
        for child in self.supervisors:
            try:
                child.wait(timeout=5)
                self.events.append(f"reaped supervisor pid={child.pid}")
            except subprocess.TimeoutExpired:
                failures.append(f"supervisor wait timeout pid={child.pid}")
                timed_out_supervisors.append(child)
                self.events.append(f"supervisor wait timeout pid={child.pid}")
        self.register_driver_from_telemetry()
        if not self.drivers:
            failures.append("driver custody unknown: empty registry")
            self.events.append("driver custody unknown: empty registry")
        probe = read_stat or (lambda pid: Path(f"/proc/{pid}/stat").read_text(encoding="utf-8"))
        send = signal or (lambda pid: os.kill(pid, 15))
        driver_states = [
            (pid, token, self.process_state(pid, token, probe))
            for pid, token in self.drivers
        ]
        driver_recovery_needed = any(state != "absent" for _pid, _token, state in driver_states)
        if driver_recovery_needed:
            self.events.append("driver cleanup recovery required")
        recovery_needed = bool(failures or driver_recovery_needed)
        if recovery_needed:
            identities = list(self.supervisor_tokens.items()) + list(self.drivers)
            for pid, token in identities:
                try:
                    self.signal_if_alive(pid, token, probe, send)
                    self.events.append(f"attempted bounded recovery pid={pid}")
                except (OSError, ValueError) as error:
                    self.events.append(f"bounded recovery unknown pid={pid}: {error}")
            for child in timed_out_supervisors:
                try:
                    child.wait(timeout=5)
                    self.events.append(f"reaped supervisor after recovery pid={child.pid}")
                except subprocess.TimeoutExpired:
                    failures.append(f"supervisor recovery wait timeout pid={child.pid}")
                    self.events.append(f"supervisor recovery wait timeout pid={child.pid}")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.drivers:
            states = [self.process_state(pid, token) for pid, token in self.drivers]
            if all(state == "absent" for state in states):
                break
            time.sleep(0.02)
        for pid, token in self.drivers:
            state = self.process_state(pid, token)
            if state != "absent":
                failures.append(f"driver {pid} cleanup state={state}")
        report = self.root / ("custody-failure.json" if failures else "custody-report.json")
        if failures:
            self.events.extend(f"FAIL: {failure}" for failure in failures)
        else:
            self.events.append("verified driver kernel absence")
        report.write_text(json.dumps({
            "events": self.events,
            "drivers": self.drivers,
            "supervisors": [child.pid for child in self.supervisors],
            "failures": failures,
        }, indent=2, sort_keys=True), encoding="utf-8")
        if failures:
            raise AssertionError("; ".join(failures))
        self.finished = True

def identity_from_frame(frame: Mapping[str, Any]) -> tuple[int, int, str]:
    """Parse a production identity without executing serialized content."""
    value = ast.literal_eval(str(frame["launcher_identity"]))
    assert isinstance(value, tuple) and len(value) == 3
    return int(value[0]), int(value[1]), str(value[2])


def launch(
    custody: Custody, session: str, *, cancel_requested: Any | None = None,
    submitted_gate: Any | None = None,
) -> int:
    """Invoke the public workspace resume route with a real raw supervisor."""
    original_read = background._read_frames
    original_ownership = background._ownership_from_started
    original_background_launch = background.launch_background
    original_validator = background._validate_launcher_cleanup_ack
    original_model = project_scope._apply_selected_model_environment
    original_confirm = project_scope._confirm_resumed_startup
    import cli_topsailai.agent_launch as agent_launch
    original_agent_model = agent_launch._apply_selected_model_environment
    original_environment = os.environ.copy()
    original_cwd = os.getcwd()
    mutation = os.environ.get("C2_CAMPAIGN_MUTATION")
    u2_mutation = os.environ.get("C2_U2_MUTATION")
    u3_mutation = os.environ.get("C2_U3_MUTATION")
    u4_mutation = os.environ.get("C2_U4_MUTATION")
    u5_mutation = os.environ.get("C2_U5_MUTATION")
    held_submitted: list[dict[str, Any]] = []

    def observed_ownership(frame: Mapping[str, Any], session_id: str) -> Any:
        """Capture the one production ownership call without invoking it twice."""
        result = original_ownership(frame, session_id)
        custody.ownership = result
        custody.register_driver(result.launcher_pid, int(ast.literal_eval(result.identity)[1]))
        custody.events.append("captured production ownership return and registered owner")
        return result

    def observed_read(fd: Any, buffer: bytearray) -> list[dict[str, Any]]:
        """Retain frames and hold submitted delivery behind the test gate."""
        frames = original_read(fd, buffer)
        observed = [dict(frame) for frame in frames]
        if submitted_gate is not None and not submitted_gate.get("triggered", False):
            released: list[dict[str, Any]] = []
            for frame in frames:
                if frame.get("kind") == "submitted":
                    held_submitted.append(frame)
                else:
                    released.append(frame)
            frames = released
        elif held_submitted:
            frames = held_submitted + frames
            held_submitted.clear()
        for frame in observed:
            if frame.get("kind") == "started":
                try:
                    pid, token, _ = identity_from_frame(frame)
                    custody.register_driver(pid, token)
                except (AssertionError, KeyError, TypeError, ValueError):
                    custody.register_driver_from_telemetry()
        for frame in observed:
            if frame.get("kind") == "started" and mutation == "identity":
                pid, token, _ = identity_from_frame(frame)
                frame["launcher_identity"] = repr((pid, token + 1, "authoritative"))
                custody.events.append("engaged identity observation mutation")
        if u3_mutation in {"pid", "omit-cleanup-pid-check"}:
            for index, frame in enumerate(frames):
                if frame.get("kind") != "cleanup":
                    continue
                custody.u3_original_cleanup = dict(frame)
                receiver = dict(frame)
                receiver["launcher_pid"] = int(frame["launcher_pid"]) + 1
                frames[index] = receiver
                custody.u3_received_cleanup = dict(receiver)
                custody.u3_receiver_frame = receiver
                custody.u3_transformations += 1
                custody.events.append("engaged U3 receiver launcher_pid mutation")
                break
        if u4_mutation in {"token", "omit-cleanup-token-check"}:
            for index, frame in enumerate(frames):
                if frame.get("kind") != "cleanup":
                    continue
                custody.u4_original_cleanup = dict(frame)
                receiver = dict(frame)
                pid, token, source = identity_from_frame(frame)
                receiver["launcher_identity"] = repr((pid, token + 1, source))
                frames[index] = receiver
                custody.u4_received_cleanup = dict(receiver)
                custody.u4_receiver_frame = receiver
                custody.u4_transformations += 1
                custody.events.append("engaged U4 receiver launcher_identity token mutation")
                break
        if u5_mutation in {"session", "omit-cleanup-session-check"}:
            for index, frame in enumerate(frames):
                if frame.get("kind") != "cleanup":
                    continue
                custody.u5_original_cleanup = dict(frame)
                receiver = dict(frame)
                receiver["session"] = f"{frame['session']}-mismatch"
                frames[index] = receiver
                custody.u5_received_cleanup = dict(receiver)
                custody.u5_receiver_frame = receiver
                custody.u5_transformations += 1
                custody.events.append("engaged U5 receiver session mutation")
                break
        custody.frames.extend(frames)
        custody.observed_frames.extend(observed)
        return frames

    os.environ.clear()
    os.environ.update(custody.environment(session))
    os.environ["TOPSAILAI_CLI_ENTRY"] = str(custody.entrypoint)
    marker = (custody.u5_marker if u5_mutation else
              custody.u4_marker if u4_mutation else
              custody.u3_marker if u3_mutation else custody.u2_marker)

    def spawn_owned_supervisor(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
        """Add mutation variables only to the test-owned supervisor environment."""
        if u2_mutation == "disable-owned-cleanup":
            supervisor_environment = dict(kwargs.get("env") or os.environ)
            supervisor_environment["C2_U2_MUTATION"] = "disable-owned-cleanup"
            supervisor_environment["C2_U2_MARKER"] = str(marker)
            kwargs["env"] = supervisor_environment
        return custody.spawn(*args, **kwargs)

    def launch_with_optional_cancellation(folder: str, session_id: str, **kwargs: Any) -> dict[str, Any]:
        """Inject test-owned cancellation at the real launch seam."""
        if cancel_requested is not None:
            kwargs["cancel_requested"] = cancel_requested
        return original_background_launch(folder, session_id, **kwargs)

    def validate_u4(frame: Mapping[str, Any], ownership: Any) -> bool:
        """Neutralize only the registered U4 receiver identity token comparison."""
        original_cleanup = custody.u4_original_cleanup
        received_cleanup = custody.u4_received_cleanup
        if ownership is None or original_cleanup is None or received_cleanup is None:
            return original_validator(frame, ownership)
        frame_payload = dict(frame)
        original_payload = dict(original_cleanup)
        frame_identity = frame_payload.get("launcher_identity")
        original_identity = original_payload.get("launcher_identity")
        try:
            received_identity = identity_from_frame(received_cleanup)
            candidate_identity = identity_from_frame(frame)
            owner_identity = identity_from_frame({"launcher_identity": ownership.identity})
        except (AssertionError, KeyError, TypeError, ValueError):
            return original_validator(frame, ownership)
        original_payload.pop("launcher_identity", None)
        frame_payload.pop("launcher_identity", None)
        targeted = (
            u4_mutation == "omit-cleanup-token-check"
            and frame is custody.u4_receiver_frame
            and ownership is custody.ownership
            and frame.get("kind") == "cleanup"
            and frame_identity == received_cleanup.get("launcher_identity")
            and original_identity == ownership.identity
            and received_identity[0] == owner_identity[0]
            and received_identity[2] == owner_identity[2]
            and candidate_identity[0] == received_identity[0]
            and candidate_identity[2] == received_identity[2]
            and candidate_identity[1] == received_identity[1]
            and candidate_identity[1] != owner_identity[1]
            and candidate_identity[1] == owner_identity[1] + 1
            and frame_payload == original_payload
        )
        if not targeted:
            return original_validator(frame, ownership)
        private_frame = dict(frame)
        private_frame["launcher_identity"] = original_identity
        result = original_validator(private_frame, ownership)
        custody.u4_omissions += 1
        boundary = inspect.currentframe().f_back.f_code.co_name
        record = {
            "event": "u4_validator_omission",
            "boundary": boundary,
            "decision": "normalize_start_token",
            "original_validator_result": result,
            "received": {"launcher_identity": frame_identity},
            "private_input": {"launcher_identity": private_frame["launcher_identity"]},
            "owner": {"launcher_pid": ownership.launcher_pid, "identity": ownership.identity},
        }
        with custody.u4_marker.open("a", encoding="utf-8") as marker_file:
            marker_file.write(json.dumps(record, sort_keys=True) + "\n")
        return result

    def validate_u5(frame: Mapping[str, Any], ownership: Any) -> bool:
        """Neutralize only the registered U5 receiver session comparison."""
        original_cleanup = custody.u5_original_cleanup
        received_cleanup = custody.u5_received_cleanup
        custody.u5_validator_calls.append({
            "frame": frame,
            "ownership": ownership,
            "boundary": inspect.currentframe().f_back.f_code.co_name,
        })
        if ownership is None or original_cleanup is None or received_cleanup is None:
            return original_validator(frame, ownership)
        required = {"session", "launcher_pid", "launcher_identity", "kind", "cleanup_confirmed"}
        original_payload = dict(original_cleanup)
        frame_payload = dict(frame)
        owner_identity = getattr(ownership, "identity", None)
        original_identity = original_payload.get("launcher_identity")
        original_valid = (
            required <= original_payload.keys()
            and original_payload.get("kind") == "cleanup"
            and bool(original_payload.get("cleanup_confirmed"))
            and original_payload.get("session") == getattr(ownership, "session", None)
            and original_payload.get("launcher_pid") == getattr(ownership, "launcher_pid", None)
            and original_identity == owner_identity
        )
        received_session = received_cleanup.get("session")
        original_session = original_payload.get("session")
        targeted = (
            original_valid
            and u5_mutation == "omit-cleanup-session-check"
            and frame is custody.u5_receiver_frame
            and ownership is custody.ownership
            and frame.get("kind") == "cleanup"
            and frame.get("session") == received_session
            and isinstance(received_session, str)
            and bool(received_session)
            and received_session != original_session
            and frame_payload == dict(received_cleanup)
            and set(frame_payload) == set(original_payload)
            and all(
                key == "session" or frame_payload[key] == original_payload[key]
                for key in original_payload
            )
            and isinstance(original_session, str)
            and bool(original_session)
        )
        if not targeted:
            return original_validator(frame, ownership)
        private_frame = dict(frame)
        private_frame["session"] = original_session
        if private_frame["session"] != original_session:
            return original_validator(frame, ownership)
        result = original_validator(private_frame, ownership)
        custody.u5_omissions += 1
        record = {
            "event": "u5_validator_omission",
            "original_validator_result": result,
            "boundary": custody.u5_validator_calls[-1]["boundary"],
            "decision": "normalize_session",
            "original": {"session": original_payload.get("session"), "launcher_pid": original_payload.get("launcher_pid"), "launcher_identity": original_identity},
            "received": {"session": frame.get("session"), "launcher_pid": frame.get("launcher_pid"), "launcher_identity": frame.get("launcher_identity")},
            "private_input": {"session": private_frame.get("session"), "launcher_pid": private_frame.get("launcher_pid"), "launcher_identity": private_frame.get("launcher_identity")},
            "owner": {"launcher_pid": ownership.launcher_pid, "identity": ownership.identity, "session": ownership.session},
        }
        with custody.u5_marker.open("a", encoding="utf-8") as marker_file:
            marker_file.write(json.dumps(record, sort_keys=True) + "\n")
        return result
    def validate_u3(frame: Mapping[str, Any], ownership: Any) -> bool:
        """Neutralize only the registered U3 receiver PID comparison."""
        original_cleanup = custody.u3_original_cleanup
        received_cleanup = custody.u3_received_cleanup
        frame_payload = dict(frame)
        original_payload = dict(original_cleanup or {})
        frame_payload.pop("launcher_pid", None)
        original_payload.pop("launcher_pid", None)
        targeted = (
            u3_mutation == "omit-cleanup-pid-check"
            and frame is custody.u3_receiver_frame
            and ownership is custody.ownership
            and frame.get("kind") == "cleanup"
            and "launcher_pid" in frame
            and original_cleanup is not None
            and received_cleanup is not None
            and frame_payload == original_payload
            and frame.get("launcher_pid") == received_cleanup.get("launcher_pid")
            and frame.get("launcher_pid") != original_cleanup.get("launcher_pid")
        )
        if not targeted:
            return original_validator(frame, ownership)
        private_frame = dict(frame)
        private_frame["launcher_pid"] = ownership.launcher_pid
        result = original_validator(private_frame, ownership)
        custody.u3_omissions += 1
        boundary = inspect.currentframe().f_back.f_code.co_name
        record = {
            "event": "u3_validator_omission",
            "boundary": boundary,
            "decision": "normalize_launcher_pid",
            "original_validator_result": result,
            "received": {
                "launcher_pid": frame.get("launcher_pid"),
                "launcher_identity": frame.get("launcher_identity"),
                "session": frame.get("session"),
            },
            "private_input": {
                "launcher_pid": private_frame.get("launcher_pid"),
                "launcher_identity": private_frame.get("launcher_identity"),
                "session": private_frame.get("session"),
            },
            "owner": {
                "launcher_pid": ownership.launcher_pid,
                "identity": ownership.identity,
            },
        }
        with custody.u3_marker.open("a", encoding="utf-8") as marker_file:
            marker_file.write(json.dumps(record, sort_keys=True) + "\n")
        return result

    background._read_frames = observed_read
    background._ownership_from_started = observed_ownership
    background.launch_background = launch_with_optional_cancellation
    if u3_mutation == "omit-cleanup-pid-check":
        background._validate_launcher_cleanup_ack = validate_u3
    elif u4_mutation == "omit-cleanup-token-check":
        background._validate_launcher_cleanup_ack = validate_u4
    elif u5_mutation in {"session", "omit-cleanup-session-check"}:
        background._validate_launcher_cleanup_ack = validate_u5
    project_scope._apply_selected_model_environment = lambda _folder: ({}, set())
    agent_launch._apply_selected_model_environment = lambda _folder: ({}, set())
    # This fixture proves submission identity and detach, not startup
    # confirmation: its driver never publishes a control channel, so the real
    # heartbeat window would always expire and mask the behaviour under test.
    project_scope._confirm_resumed_startup = lambda *args, **kwargs: {
        "startup_confirmed": True,
        "startup_pid": None,
        "startup_reason": "heartbeat_answered",
    }
    custody.production_entry_cwd = os.getcwd()
    custody.production_entry_environment = os.environ.copy()
    try:
        result = project_scope.resume_session_result(
            session, background=True, agent_mode="raw", driver="topsailai_agent_chats",
            spawn=spawn_owned_supervisor, query=lambda _session: [{
                "session_id": session, "project_workspace": str(custody.workspace),
            }], home=str(custody.home),
            entrypoint_base=str(Path(__file__).resolve().parents[3]),
        )
        if mutation == "production-leak":
            os.chdir(custody.workspace)
            os.environ["C2_U1_PRODUCTION_LEAK"] = "1"
        custody.capture_return_state()
        return result
    finally:
        if mutation != "disable-wrapper-fallback":
            custody.register_driver_from_telemetry()
        if held_submitted:
            custody.held_submitted_archive.extend(dict(frame) for frame in held_submitted)
            custody.events.append(f"archived held submitted frames count={len(held_submitted)}")
            held_submitted.clear()
        background._read_frames = original_read
        background._ownership_from_started = original_ownership
        background.launch_background = original_background_launch
        background._validate_launcher_cleanup_ack = original_validator
        project_scope._apply_selected_model_environment = original_model
        project_scope._confirm_resumed_startup = original_confirm
        agent_launch._apply_selected_model_environment = original_agent_model
        os.environ.clear()
        os.environ.update(original_environment)
        os.chdir(original_cwd)

_SUPERVISOR = f'''#!{sys.executable}
import inspect
import ast
import json
import os
import sys
import time
sys.path.insert(0, {str(Path(__file__).resolve().parents[3])!r})
_u2_mutation = os.environ.pop("C2_U2_MUTATION", None)
_u2_marker = os.environ.pop("C2_U2_MARKER", None)
if _u2_marker:
    with open(_u2_marker, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({{"event": "supervisor_environment", "mutation": _u2_mutation, "marker": _u2_marker}}) + "\\n")
if _u2_mutation == "disable-owned-cleanup":
    import cli_topsailai.agent_launch_background as _background
    _original_cleanup_owned = _background._cleanup_owned
    _original_child_identity = _background._child_identity
    _registered_owner = [None]
    _owner_bound = [False]

    def _u2_child_identity(child, identity_probe=None):
        """Capture ownership only for the supervisor registration observation."""
        identity = _original_child_identity(child, identity_probe)
        caller = inspect.currentframe().f_back
        registration_origin = (
            caller is not None
            and caller.f_code.co_name == "_supervise"
            and caller.f_locals.get("child") is child
        )
        if registration_origin and not _owner_bound[0]:
            _registered_owner[0] = tuple(identity)
            _owner_bound[0] = True
        return identity

    _background._child_identity = _u2_child_identity

    def _u2_cleanup_owned(child, *, wait_timeout=0.25, identity=None, identity_probe=None):
        """Bypass cleanup only for the registration-bound owner identity."""
        target_pid = getattr(child, "pid", None)
        target_token = identity[1] if isinstance(identity, tuple) and len(identity) > 1 else None
        boundary = inspect.currentframe().f_back.f_code.co_name
        owner_match = (
            _registered_owner[0] is not None
            and target_pid == _registered_owner[0][0]
            and isinstance(identity, tuple)
            and tuple(identity) == _registered_owner[0]
        )
        record = {{
            "event": "invocation", "pid": target_pid, "token": target_token,
            "boundary": boundary, "bypassed": owner_match,
        }}
        if _u2_marker:
            with open(_u2_marker, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\\n")
        if owner_match:
            return True
        return _original_cleanup_owned(
            child, wait_timeout=wait_timeout, identity=identity, identity_probe=identity_probe
        )

    _background._cleanup_owned = _u2_cleanup_owned
from cli_topsailai.agent_launch_background import _supervisor_entry
_supervisor_entry(sys.argv[2], sys.argv[3])
'''

_DRIVER = f'''#!{sys.executable}
import json, os, time, tempfile
from pathlib import Path
from cli_topsailai.agent_launch_background import _authoritative_child_identity
pid = os.getpid()
identity = _authoritative_child_identity(pid)
Path(os.environ["FIXTURE_TELEMETRY"]).write_text(json.dumps({{
    "pid": pid, "token": identity[1], "parent": os.getppid(),
    "session": os.environ["SESSION_ID"], "top_session": os.environ["TOPSAILAI_SESSION_ID"],
    "cwd": os.getcwd(), "model": os.environ["FIXTURE_MODEL"],
    "mutation": os.environ.get("C2_U2_MUTATION"), "marker": os.environ.get("C2_U2_MARKER")
}}), encoding="utf-8")
count = 0
while not Path(os.environ["FIXTURE_RELEASE"]).exists():
    count += 1
    target = Path(os.environ["FIXTURE_HEARTBEAT"])
    temp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False)
    temp.write(str(count)); temp.close(); os.replace(temp.name, target)
    time.sleep(0.02)
target = Path(os.environ["FIXTURE_HEARTBEAT"])
temp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False)
temp.write("released"); temp.close(); os.replace(temp.name, target)
'''
