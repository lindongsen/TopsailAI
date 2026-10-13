"""Exercise stop custody without signaling any real process.

Author: DawsonLin
"""

from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from cli_topsailai.session_driver import DriverMetadata, DriverObservation, ProcessEvidence
from cli_topsailai.session_driver_stopper import stop_driver


class Process:
    """Model identity, signal effects and query failures explicitly."""

    pid = 90
    birth = 1.0
    running = True
    command = ["python3", "/fixture/driver.py", "--session", "sample"]
    state = psutil.STATUS_RUNNING
    error = None
    query_error = None
    exit_on_signal = True

    def __init__(self):
        """Keep signal history isolated per test."""
        self.signals = []

    def create_time(self):
        """Expose a mutable birth seam for replacement races."""
        if self.query_error:
            raise self.query_error
        return self.birth

    def cmdline(self):
        """Return a concrete exact driver invocation."""
        return self.command

    def cwd(self):
        """Supply the path context used by command verification."""
        return "/fixture"

    def status(self):
        """Expose running or terminal OS state."""
        return self.state

    def is_running(self):
        """Report whether original identity is still present."""
        return self.running

    def send_signal(self, value):
        """Record a single exact-handle signal and its simulated effect."""
        if self.error:
            raise self.error
        self.signals.append(value)
        if self.exit_on_signal:
            self.running = False


@pytest.fixture
def setup():
    """Provide detached rows, metadata and explicit process/time dependencies."""
    process = Process()
    row = dict(session_id="sample", pid=10, filename="sample.10.session.stdout")
    metadata = DriverMetadata(1, "sample", 90, "a" * 32, "running")
    state = SimpleNamespace(record=metadata, calls=0, hook=None, now=0.0)

    def observer(home, session, *, process_probe):
        """Apply one optional race then derive real observation semantics."""
        state.calls += 1
        if state.hook:
            state.hook(state.calls)
        if isinstance(state.record, DriverObservation):
            return state.record
        evidence = process_probe(state.record)
        if evidence is ProcessEvidence.UNKNOWN:
            return DriverObservation("?", "process_unverified", state.record, evidence)
        if state.record.status != "running":
            label = "?" if evidence is ProcessEvidence.VERIFIED else "EXIT"
        else:
            label = "ON" if evidence is ProcessEvidence.VERIFIED else "STALE"
        return DriverObservation(label, "process_" + evidence.value, state.record, evidence)

    def sleep(amount):
        """Advance a deterministic monotonic clock."""
        state.now += amount

    args = dict(topsailai_home=Path("/fixture"),
                authority=SimpleNamespace(entry=Path("/fixture/driver.py"), validate=lambda: None),
                discover=lambda: [row], target_probe=lambda pid: False,
                observer=observer, process_factory=lambda pid: process,
                clock=lambda: state.now, sleep=sleep)
    return process, row, state, args


def run(setup, **overrides):
    """Invoke the shared operation using fixture-owned dependencies."""
    process, row, state, args = setup
    return stop_driver([row], 1, **(args | overrides))


def test_verified_stop(setup):
    """Signal only driver, never the exited target; confirm original exit."""
    result = run(setup)
    assert result.outcome == "stopped"
    assert setup[0].signals == [15]


@pytest.mark.parametrize("record", [None, "terminal", "absent"])
def test_idempotent(setup, record):
    """Missing ownership and confirmed absence require no signaling."""
    process, row, state, args = setup
    if record is None:
        state.record = DriverObservation("-", "metadata_missing")
    else:
        process.running = False
        if record == "terminal":
            state.record = DriverMetadata(1, "sample", 90, "a" * 32, "stopped")
    assert run(setup).outcome == "already_stopped"
    assert not process.signals


@pytest.mark.parametrize("override", [dict(timeout=0), dict(interval=False),
    dict(timeout=float("nan")), dict(interval=float("inf")), dict(timeout="x"),
    dict(authority=None), dict(platform="nt"), dict(discover=lambda: [])])
def test_invalid_preflight(setup, override):
    """Invalid timing, authority, platform and target all fail closed."""
    assert run(setup, **override).outcome == "rejected"
    assert not setup[0].signals


@pytest.mark.parametrize("mode", ["command", "terminal", "denied", "target", "malformed"])
def test_invalid_identity(setup, mode):
    """Do not signal uncertain or live terminal owners or the session itself."""
    process, row, state, args = setup
    if mode == "command":
        process.command = ["python3", "/wrong.py", "-s", "sample"]
    elif mode == "terminal":
        state.record = DriverMetadata(1, "sample", 90, "a" * 32, "stopped")
    elif mode == "denied":
        process.query_error = psutil.AccessDenied(90)
    elif mode == "target":
        row.update(pid=90, filename="sample.90.session.stdout")
    else:
        state.record = DriverObservation("?", "invalid_metadata_shape")
    assert run(setup).outcome == "rejected"
    assert not process.signals


@pytest.mark.parametrize("mode", ["run", "pid", "birth", "missing", "command"])
def test_owner_changed_before_signal(setup, mode):
    """Re-read metadata and birth/command before authorizing a signal."""
    process, row, state, args = setup

    def change(count):
        """Inject replacement at the second observation boundary."""
        if count != 2:
            return
        if mode in ("run", "pid"):
            state.record = DriverMetadata(1, "sample", 91 if mode == "pid" else 90,
                                          "b" * 32 if mode == "run" else "a" * 32, "running")
        elif mode == "birth":
            process.birth = 2.0
        elif mode == "missing":
            state.record = DriverObservation("-", "metadata_missing")
        else:
            process.command = ["bad"]

    state.hook = change
    assert run(setup).outcome == "rejected"
    assert not process.signals


@pytest.mark.parametrize("error,outcome", [(psutil.AccessDenied(90), "failed"),
    (OSError("denied"), "failed"), (NotImplementedError(), "failed"),
    (psutil.NoSuchProcess(90), "already_stopped")])
def test_signal_failure(setup, error, outcome):
    """Classify definite submission errors and concurrent departure."""
    setup[0].error = error
    assert run(setup).outcome == outcome
    assert not setup[0].signals


def test_timeout(setup):
    """Never resend or escalate after uncertain delivery."""
    setup[0].exit_on_signal = False
    result = run(setup, timeout=0.3)
    assert result.outcome == "unconfirmed"
    assert result.reason == "stop_timeout"
    assert setup[0].signals == [15]
    assert setup[2].now == pytest.approx(0.3)


@pytest.mark.parametrize("mode", ["run", "unknown", "denied", "missing", "zombie"])
def test_post_signal_evidence(setup, mode):
    """Do not imply replacement stopped or hide unavailable inspection."""
    process, row, state, args = setup

    def change(count):
        """Inject uncertainty or safe absence during confirmation."""
        if count != 3:
            return
        if mode == "run":
            state.record = DriverMetadata(1, "sample", 90, "b" * 32, "running")
        elif mode == "unknown":
            state.record = DriverObservation("?", "metadata_not_regular")
        elif mode == "denied":
            process.running = True
            process.query_error = psutil.AccessDenied(90)
        elif mode == "missing":
            state.record = DriverObservation("-", "metadata_missing")
        else:
            process.state = psutil.STATUS_ZOMBIE

    state.hook = change
    result = run(setup)
    assert result.outcome == ("stopped" if mode in ("missing", "zombie") else "unconfirmed")
    assert process.signals == [15]


def test_ambiguous_session(setup):
    """Multiple live authoritative session PIDs never authorize control."""
    row = setup[1]
    other = row | dict(pid=11, filename="sample.11.session.stdout")
    assert run(setup, discover=lambda: [row, other], target_probe=lambda pid: True).outcome == "rejected"
    assert not setup[0].signals


def test_invalid_row_and_duplicates(setup):
    """Reject malformed rows and duplicate discovery entries."""
    assert run(setup, discover=lambda: [setup[1], setup[1]]).outcome == "rejected"
    setup[1]["is_task"] = True
    assert run(setup).outcome == "rejected"
    assert not setup[0].signals


def test_ignored_ineligible_discovery(setup):
    """Ignore non-authoritative discovery without losing a unique row."""
    row = setup[1]
    assert run(setup, discover=lambda: [None, {}, row | dict(is_task=True), row]).outcome == "stopped"


def test_invalid_index(setup):
    """Reject out-of-range indices before discovery or process inspection."""
    assert stop_driver([setup[1]], 0, **setup[3]).outcome == "rejected"


def test_process_disappears_during_bind(setup):
    """A vanished metadata owner is idempotently absent."""
    def missing(pid):
        """Simulate process construction racing with exit."""
        raise psutil.NoSuchProcess(pid)
    assert run(setup, process_factory=missing).outcome == "already_stopped"


def test_absence_exception(setup):
    """NoSuchProcess at a birth query confirms original process absence."""
    setup[0].query_error = psutil.NoSuchProcess(90)
    assert run(setup).outcome == "already_stopped"


def test_command_probe_birth_changes(setup):
    """Identity changing during command inspection fails closed."""
    def command():
        """Replace birth after initial capture but before command validation."""
        setup[0].birth = 2.0
        return setup[0].command
    setup[0].cmdline = command
    assert run(setup).outcome == "rejected"
    assert not setup[0].signals


def test_departure_at_last_check(setup):
    """Exit after metadata revalidation needs no signal."""
    original = setup[0].is_running
    calls = 0

    def running():
        """Disarm liveness only at the final pre-signal check."""
        nonlocal calls
        calls += 1
        return False if calls == 5 else original()

    setup[0].is_running = running
    assert run(setup).outcome == "already_stopped"
    assert not setup[0].signals


def test_confirmation_query_failure(setup):
    """A post-submission inspection exception cannot become success."""
    def sleep(amount):
        """Lose query authority after first poll."""
        setup[0].query_error = psutil.AccessDenied(90)
    setup[0].exit_on_signal = False
    result = run(setup, sleep=sleep)
    assert result.outcome == "unconfirmed"
    assert result.reason == "inspection_unavailable"
    assert setup[0].signals == [15]


@pytest.mark.parametrize("boundary", [1, 2])
@pytest.mark.parametrize("mode", ["mutation", "replacement", "reordering"])
def test_selected_identity_changed_before_signal(setup, boundary, mode):
    """Reject changed selection at either observation boundary without signaling."""
    process, row, state, args = setup
    other = row | dict(pid=90, filename="sample.90.session.stdout")
    rows = [row, other] if mode == "reordering" else [row]

    def change(count):
        """Alter the selected identity while both rows remain discoverable."""
        if count != boundary:
            return
        if mode == "mutation":
            row.update(other)
        elif mode == "replacement":
            rows[0] = other
        else:
            rows.reverse()

    state.hook = change
    result = stop_driver(rows, 1, **(args | {"discover": lambda: list(rows)}))
    assert result.outcome == "rejected"
    assert result.reason == "target_changed"
    assert process.signals == []
