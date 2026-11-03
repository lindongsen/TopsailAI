"""Tests for the shared foreground launch boundary."""

import os
import subprocess

import pytest
from unittest.mock import patch

import cli_topsailai.agent_launch_background
from cli_topsailai.agent_launch import launch_configured_agent


from cli_topsailai import agent_launch as agent_launch_module


@pytest.fixture(autouse=True)
def _fail_fast_on_uninjected_spawn(monkeypatch):
    """Never permit a launch test to fall through to a real process."""
    def fail_fast(*args, **kwargs):
        raise AssertionError("consumer-local fail-fast guard: real process spawn attempted")
    monkeypatch.setattr(agent_launch_module, "_spawn_process", fail_fast)


class FakeChild:
    """Finite child double that records ownership operations."""

    def __init__(self, returncode=0, wait_error=None):
        self.returncode = returncode
        self.wait_error = wait_error
        self.calls = []

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        if self.wait_error:
            raise self.wait_error
        return self.returncode

    def poll(self):
        self.calls.append(("poll", None))
        return self.returncode

    def terminate(self):
        self.calls.append(("terminate", None))

    def kill(self):
        self.calls.append(("kill", None))


def _model_environment(_folder):
    """Return a model result with no additional environment values."""
    return ({}, set())


def test_foreground_propagates_child_status_and_restores_cwd(tmp_path):
    child = FakeChild(returncode=42)
    calls = []

    def spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        return child

    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment), \
         patch("cli_topsailai.agent_launch._session_id", return_value="fixed-session"):
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=spawn) == 42

    assert calls == [(
        ["topsailai_launch_agent", "--subprocess", "--session-id", "fixed-session"],
        {"cwd": str(tmp_path), "env": calls[0][1]["env"]},
    )]
    assert calls[0][1]["env"]["PWD"] == str(tmp_path)
    assert calls[0][1]["env"]["TOPSAILAI_SESSION_ID"] == "fixed-session"
    assert child.calls == [("wait", None)]


def test_foreground_signal_maps_to_shell_signal_code(tmp_path):
    child = FakeChild(returncode=-2)
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment), \
         patch("cli_topsailai.agent_launch._session_id", return_value="fixed-session"):
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 130
    assert child.calls == [("wait", None)]


def test_default_mode_detection_resolves_concrete_mode(tmp_path):
    """Omitted mode uses the consuming module's concrete mode detector."""
    child = FakeChild(returncode=0)
    calls = []
    with patch("cli_topsailai.agent_launch._detect_agent_mode", return_value="raw") as detect, \
         patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment), \
         patch("cli_topsailai.agent_launch._session_id", return_value="fixed-session"):
        assert launch_configured_agent(str(tmp_path), mode=None, spawn=lambda argv, **kwargs: (calls.append((argv, kwargs)) or child)) == 0
    detect.assert_called_once_with()
    assert calls[0][0] == ["topsailai_launch_agent", "--subprocess", "--session-id", "fixed-session"]


def test_default_mode_detection_failure_is_preparation_error(tmp_path):
    """Mode detection failures are mapped to preparation exit code four."""
    spawned = []
    with patch("cli_topsailai.agent_launch._detect_agent_mode", side_effect=RuntimeError("probe failed")):
        assert launch_configured_agent(str(tmp_path), mode=None, spawn=spawned.append) == 4
    assert spawned == []


def test_default_spawn_uses_production_seam_only_when_explicitly_allowed(tmp_path):
    """The default seam is guarded and can be replaced with a finite fake."""
    child = FakeChild(returncode=0)
    with patch.object(agent_launch_module, "_spawn_process", return_value=child) as spawn:
        with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment):
            assert launch_configured_agent(str(tmp_path), mode="raw") == 0
    spawn.assert_called_once()


def test_spawn_oserror_maps_to_spawn_failure_and_restores_state(tmp_path, capsys, monkeypatch):
    """A spawn error restores all parent state and reports only failure."""
    original_cwd = os.getcwd()
    absent_key = "UNIT1A_SPAWN_FAILURE_ABSENT"
    mutation_key = "UNIT1A_SPAWN_FAILURE_MUTATION"
    monkeypatch.delenv(absent_key, raising=False)
    monkeypatch.setenv(mutation_key, "before")
    original_environment = dict(os.environ)

    def prepare_model(_folder):
        """Introduce and mutate preparation state before the failing spawn."""
        os.environ[absent_key] = "introduced"
        os.environ[mutation_key] = "during"
        return ({}, set())

    def fail_spawn(*args, **kwargs):
        assert os.environ[absent_key] == "introduced"
        assert os.environ[mutation_key] == "during"
        assert os.getcwd() == str(tmp_path)
        raise OSError("no executable")

    with patch("cli_topsailai.agent_launch._session_id", return_value="fixed-session"), \
         patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=prepare_model):
        result = launch_configured_agent(str(tmp_path), mode="raw", spawn=fail_spawn)

    captured = capsys.readouterr()
    assert result == 5
    assert os.getcwd() == original_cwd
    assert dict(os.environ) == original_environment
    assert absent_key not in os.environ
    assert captured.out == (
        f"[INFO] Launching agent: workspace={tmp_path} mode=raw "
        "background=no session=fixed-session\n"
    )
    assert captured.err == "[ERROR] Agent launch failed: no executable\n"
    assert "Agent launcher exited" not in captured.out + captured.err


def test_outer_oserror_after_spawn_attempts_custody_cleanup(tmp_path):
    """An unexpected post-spawn OSError is classified after cleanup."""
    child = FakeChild(returncode=0)
    real_print = print
    def fail_exit_print(*args, **kwargs):
        if args and str(args[0]).startswith("[INFO] Agent launcher exited"):
            raise OSError("output failed")
        return real_print(*args, **kwargs)
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment), \
         patch("builtins.print", side_effect=fail_exit_print), \
         patch("cli_topsailai.agent_launch._stop_owned_child", return_value=False) as stop:
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 6
    stop.assert_called_once_with(child)


def test_outer_post_spawn_oserror_returns_custody_status(tmp_path):
    """Unexpected post-spawn errors retain ownership and classify cleanup."""
    child = FakeChild(returncode=0)
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment), \
         patch.object(child, "wait", side_effect=KeyboardInterrupt()), \
         patch("cli_topsailai.agent_launch._stop_owned_child", return_value=True) as stop:
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 130
    stop.assert_called_once_with(child)


def _prepared_model_environment(_folder):
    """Return model environment bookkeeping for launch assertions."""
    return ({"MODEL_TEST_OLD": "old"}, {"MODEL_TEST_FORWARDED"})


def test_preparation_failure_does_not_spawn_and_restores_state(tmp_path):
    original_cwd = os.getcwd()
    original_value = os.environ.get("UNIT1A_PREP_FAILURE")
    os.environ["UNIT1A_PREP_FAILURE"] = "before"
    spawned = []

    def fail_after_mutation(folder, _session_id):
        os.chdir(folder)
        os.environ["UNIT1A_PREP_FAILURE"] = "mutated"
        raise RuntimeError("model preparation failed")

    try:
        with patch("cli_topsailai.agent_launch._prepare_environment", side_effect=fail_after_mutation):
            result = launch_configured_agent(str(tmp_path), mode="raw", spawn=spawned.append)
        assert result == 4
        assert spawned == []
        assert os.getcwd() == original_cwd
        assert os.environ["UNIT1A_PREP_FAILURE"] == "before"
    finally:
        if original_value is None:
            os.environ.pop("UNIT1A_PREP_FAILURE", None)
        else:
            os.environ["UNIT1A_PREP_FAILURE"] = original_value


def test_wrapper_failure_maps_to_preparation_error_without_spawn(tmp_path):
    child_calls = []
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment), \
         patch("cli_topsailai.agent_launch._wrap_command_for_agent_mode", side_effect=ValueError("bad mode")):
        result = launch_configured_agent(str(tmp_path), mode="unsupported", spawn=child_calls.append)
    assert result == 4
    assert child_calls == []


def test_tmux_preparation_failure_maps_to_four_without_spawn(tmp_path):
    child_calls = []
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment), \
         patch("cli_topsailai.agent_launch._wrap_command_for_agent_mode", side_effect=RuntimeError("tmux missing")):
        result = launch_configured_agent(str(tmp_path), mode="tmux", spawn=child_calls.append)
    assert result == 4
    assert child_calls == []


def test_wait_oserror_cleans_owned_child(tmp_path):
    """A wait failure retains custody and performs ordered cleanup."""
    child = FakeChild(returncode=None, wait_error=OSError("wait failed"))
    child.wait_errors = [subprocess.TimeoutExpired("wait", 1), None]
    def scripted_wait(timeout=None):
        child.calls.append(("wait", timeout))
        if timeout is None:
            raise OSError("wait failed")
        if child.wait_errors:
            error = child.wait_errors.pop(0)
            if error:
                raise error
        return 0
    child.wait = scripted_wait
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment):
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 5
    assert child.calls == [("wait", None), ("poll", None), ("wait", 1.0), ("terminate", None), ("wait", 1.0)]


def test_wait_oserror_with_unresolved_custody_returns_six(tmp_path):
    """An unreaped child never reports an ordinary wait failure."""
    child = FakeChild(returncode=None, wait_error=OSError("wait failed"))
    def never_reaps(timeout=None):
        child.calls.append(("wait", timeout))
        if timeout is None:
            raise OSError("wait failed")
        raise subprocess.TimeoutExpired("wait", timeout)
    child.wait = never_reaps
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment):
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 6
    assert child.calls == [("wait", None), ("poll", None), ("wait", 1.0), ("terminate", None), ("wait", 1.0), ("kill", None), ("wait", 1.0)]


def test_keyboard_interrupt_terminates_then_kills_and_reaps_child(tmp_path):
    child = FakeChild(returncode=None, wait_error=KeyboardInterrupt())
    child.wait_errors = [subprocess.TimeoutExpired("wait", 1), subprocess.TimeoutExpired("wait", 1), None]
    original_wait = child.wait

    def wait_with_cleanup_timeout(timeout=None):
        child.calls.append(("wait", timeout))
        if timeout is None:
            raise KeyboardInterrupt()
        if timeout is not None and child.wait_errors:
            error = child.wait_errors.pop(0)
            if error:
                raise error
        return child.returncode

    child.wait = wait_with_cleanup_timeout
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment):
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 130
    assert child.calls == [
        ("wait", None), ("poll", None),
        ("wait", 1.0), ("terminate", None), ("wait", 1.0),
        ("kill", None), ("wait", 1.0),
    ]


def test_keyboard_interrupt_with_unresolved_custody_returns_six(tmp_path):
    child = FakeChild(returncode=None, wait_error=KeyboardInterrupt())

    def never_reaps(timeout=None):
        child.calls.append(("wait", timeout))
        if timeout is not None:
            raise subprocess.TimeoutExpired("wait", timeout)
        raise KeyboardInterrupt()

    child.wait = never_reaps
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment):
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 6
    assert child.calls == [
        ("wait", None), ("poll", None),
        ("wait", 1.0), ("terminate", None), ("wait", 1.0),
        ("kill", None), ("wait", 1.0),
    ]


def test_keyboard_interrupt_termination_oserror_returns_six(tmp_path):
    child = FakeChild(returncode=None, wait_error=KeyboardInterrupt())

    def terminate_failure():
        child.calls.append(("terminate", None))
        raise OSError("already gone")

    child.terminate = terminate_failure
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment):
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 6
    assert child.calls == [("wait", None), ("poll", None), ("wait", 1.0)]


def test_model_preparation_values_reach_child_and_parent_is_restored(tmp_path):
    child = FakeChild(returncode=0)
    captured = []
    original = os.environ.get("MODEL_TEST_FORWARDED")

    def prepare(folder):
        os.environ["MODEL_TEST_FORWARDED"] = "expected"
        return ({"MODEL_TEST_FORWARDED": original}, {"MODEL_TEST_FORWARDED"})

    try:
        with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=prepare) as helper:
            result = launch_configured_agent(
                str(tmp_path), mode="raw",
                spawn=lambda argv, **kwargs: (captured.append((argv, kwargs)) or child),
            )
        assert result == 0
        helper.assert_called_once_with(str(tmp_path))
        assert captured[0][1]["env"]["MODEL_TEST_FORWARDED"] == "expected"
        assert os.environ.get("MODEL_TEST_FORWARDED") == original
        assert child.calls == [("wait", None)]
    finally:
        if original is None:
            os.environ.pop("MODEL_TEST_FORWARDED", None)
        else:
            os.environ["MODEL_TEST_FORWARDED"] = original


def test_background_mode_delegates_without_foreground_spawn(tmp_path, capsys):
    """Background mode delegates to the detached supervisor boundary."""
    with patch("cli_topsailai.agent_launch._session_id", return_value="fixed"), \
         patch("cli_topsailai.agent_launch._apply_selected_model_environment", return_value=({}, set())), \
         patch("cli_topsailai.agent_launch_background.launch_background", return_value={
             "launcher_pid": 1234, "log_path": str(tmp_path / "fixed.agent-launch.log"),
         }) as launch:
        assert launch_configured_agent(str(tmp_path), mode=None, background=True) == 0
    launch.assert_called_once()
    assert "launcher_pid=1234" in capsys.readouterr().out


def test_background_log_identity_is_per_attempt_only_for_resume(tmp_path):
    """A fresh launch keeps its historical log name; a resume is per-attempt."""
    with patch("cli_topsailai.agent_launch._session_id", return_value="fresh"), \
         patch("cli_topsailai.agent_launch._apply_selected_model_environment", return_value=({}, set())), \
         patch("cli_topsailai.agent_launch_background.launch_background", return_value={
             "launcher_pid": 1, "log_path": str(tmp_path / "x.agent-launch.log"),
         }) as launch:
        assert launch_configured_agent(str(tmp_path), mode="raw", background=True) == 0
    assert launch.call_args.kwargs["log_identity"] is None

    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", return_value=({}, set())), \
         patch("cli_topsailai.agent_launch_background.launch_background", return_value={
             "launcher_pid": 1, "log_path": str(tmp_path / "x.agent-launch.log"),
         }) as launch:
        assert launch_configured_agent(
            str(tmp_path), mode="raw", background=True, session_id="persisted",
        ) == 0
    identity = launch.call_args.kwargs["log_identity"]
    assert identity.startswith("persisted.")
    assert identity != "persisted"

def test_model_preparation_none_maps_to_four_without_spawn(tmp_path):
    spawned = []
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", return_value=None):
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=spawned.append) == 4
    assert spawned == []


def test_interrupt_when_child_already_exited_skips_termination(tmp_path):
    child = FakeChild(returncode=0, wait_error=KeyboardInterrupt())
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment):
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 130
    assert child.calls == [("wait", None), ("poll", None)]


def test_interrupt_cleanup_waits_without_kill_when_terminate_reaps(tmp_path):
    child = FakeChild(returncode=None, wait_error=KeyboardInterrupt())

    def wait_interrupt_then_reap(timeout=None):
        child.calls.append(("wait", timeout))
        if timeout is None:
            raise KeyboardInterrupt()
        child.returncode = 0
        return 0

    child.wait = wait_interrupt_then_reap
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment):
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 130
    assert child.calls == [("wait", None), ("poll", None), ("wait", 1.0)]


def test_outer_keyboard_interrupt_after_child_creation_is_cleaned(tmp_path):
    child = FakeChild(returncode=None)
    with patch("cli_topsailai.agent_launch._prepare_environment", side_effect=KeyboardInterrupt), \
         patch("cli_topsailai.agent_launch._stop_owned_child", return_value=True) as stop:
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 130
    stop.assert_not_called()


def test_outer_interrupt_after_spawn_reaps_owned_child(tmp_path):
    child = FakeChild(returncode=0)
    real_print = print

    def interrupt_after_exit_message(*args, **kwargs):
        if args and str(args[0]).startswith("[INFO] Agent launcher exited"):
            raise KeyboardInterrupt()
        return real_print(*args, **kwargs)

    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment), \
         patch("builtins.print", side_effect=interrupt_after_exit_message), \
         patch("cli_topsailai.agent_launch._stop_owned_child", return_value=True) as stop:
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 130
    stop.assert_called_once_with(child)


def test_outer_interrupt_with_unresolved_owned_child_returns_six(tmp_path):
    child = FakeChild(returncode=0)
    real_print = print

    def interrupt_after_exit_message(*args, **kwargs):
        if args and str(args[0]).startswith("[INFO] Agent launcher exited"):
            raise KeyboardInterrupt()
        return real_print(*args, **kwargs)

    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment), \
         patch("builtins.print", side_effect=interrupt_after_exit_message), \
         patch("cli_topsailai.agent_launch._stop_owned_child", return_value=False) as stop:
        assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child) == 6
    stop.assert_called_once_with(child)


def test_restoration_oserror_is_reported(tmp_path):
    original_cwd = os.getcwd()
    calls = []

    def chdir(path):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("restore failed")
        return None

    try:
        with patch("cli_topsailai.agent_launch.os.chdir", side_effect=chdir), \
             patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment):
            assert launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: FakeChild()) == 6
    finally:
        os.chdir(original_cwd)
    assert calls == [str(tmp_path), original_cwd]


def test_cwd_restore_failure_still_restores_environment_with_module_local_os(tmp_path, monkeypatch):
    """Cwd and environment restoration remain independent after a cwd fault."""
    original_environment = {"PWD": "/caller", "KEEP": "before"}
    fake_environment = dict(original_environment)
    chdir_calls = []

    class FakeOS:
        environ = fake_environment

        @staticmethod
        def getcwd():
            return "/caller"

        @staticmethod
        def chdir(path):
            chdir_calls.append(path)
            raise OSError("cwd restore failed")

    def mutate_environment(*args, **kwargs):
        fake_environment["NEW_KEY"] = "mutated"
        fake_environment["KEEP"] = "mutated"
        return 0

    monkeypatch.setattr(agent_launch_module, "os", FakeOS)
    monkeypatch.setattr(agent_launch_module, "_launch_configured_agent_impl", mutate_environment)

    result = launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: None)

    assert result == 6
    assert fake_environment == original_environment
    assert "NEW_KEY" not in fake_environment
    assert chdir_calls == ["/caller"]


@pytest.mark.parametrize(
    ("background_result", "expected", "message"),
    [
        ({"outcome": "cancelled", "exit_code": 6, "cleanup_confirmed": False}, 6, None),
        ({"outcome": "cancelled", "exit_code": 130, "cleanup_confirmed": False}, 6, None),
        ({"outcome": "cancelled", "exit_code": 130, "cleanup_confirmed": True}, 130, "Agent launch cancelled"),
    ],
)
def test_background_cancellation_result_contracts(
    tmp_path, capsys, background_result, expected, message
):
    """Map cancellation result envelopes only when custody is confirmed."""
    with patch("cli_topsailai.agent_launch._session_id", return_value="fixed"), \
         patch("cli_topsailai.agent_launch._apply_selected_model_environment", return_value=({}, set())), \
         patch("cli_topsailai.agent_launch_background.launch_background", return_value=background_result):
        assert launch_configured_agent(str(tmp_path), mode="raw", background=True) == expected
    if message is not None:
        assert message in capsys.readouterr().out


def test_background_unexpected_failure_without_owned_child_maps_to_five(tmp_path):
    """An unexpected preparation exception without a child is an ordinary failure."""
    with patch("cli_topsailai.agent_launch._session_id", return_value="fixed"), \
         patch("cli_topsailai.agent_launch._prepare_environment", side_effect=Exception("unexpected")):
        assert launch_configured_agent(str(tmp_path), mode="raw") == 5


def test_fresh_session_id_is_short_and_parseable():
    """A fresh identity stays short, dot-free and recoverable from a filename."""
    import re

    from cli_topsailai.log_files import parse_stdout_filename

    session_id = agent_launch_module._session_id()

    assert len(session_id) == 15
    assert session_id.startswith("wa-")
    assert re.fullmatch(r"wa-[0-9a-f]{12}", session_id)
    assert "." not in session_id
    assert session_id not in ("topsailai", "(temp)", ".", "..")
    assert parse_stdout_filename(f"{session_id}.1234.session.stdout") == (session_id, "1234")


def test_fresh_session_ids_are_distinct():
    """Two fresh launches never share one identity."""
    assert agent_launch_module._session_id() != agent_launch_module._session_id()


def test_resume_keeps_persisted_identity_without_minting(tmp_path):
    """A resume reuses the persisted identity and never calls the minting helper."""
    child = FakeChild(returncode=0)
    calls = []

    def spawn(argv, **kwargs):
        calls.append(argv)
        return child

    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=_model_environment), \
         patch("cli_topsailai.agent_launch._session_id", side_effect=AssertionError("minted on resume")):
        assert launch_configured_agent(
            str(tmp_path), mode="raw", spawn=spawn, session_id="persisted-id",
        ) == 0

    assert calls == [["topsailai_launch_agent", "--subprocess", "--session-id", "persisted-id"]]


def test_non_interactive_flag_reaches_background_submission(tmp_path):
    """The launch boundary forwards the flag to the detached supervisor."""
    with patch("cli_topsailai.agent_launch._session_id", return_value="fixed"), \
         patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               return_value=({}, set())), \
         patch("cli_topsailai.agent_launch_background.launch_background", return_value={
             "launcher_pid": 1, "log_path": str(tmp_path / "x.agent-launch.log"),
         }) as launch:
        assert launch_configured_agent(
            str(tmp_path), mode="raw", background=True, non_interactive=True) == 0
    assert launch.call_args.kwargs["non_interactive"] is True


def test_non_interactive_flag_reaches_terminal_submission(tmp_path):
    """The launch boundary forwards the flag to the terminal supervisor."""
    from cli_topsailai import agent_launch_terminal as terminal

    with patch("cli_topsailai.agent_launch._session_id", return_value="fixed"), \
         patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               return_value=({}, set())), \
         patch.object(terminal.shutil, "which", return_value="/usr/bin/tool"), \
         patch("cli_topsailai.project_scope._tmux_supports_environment_option",
               return_value=True), \
         patch("cli_topsailai.agent_launch_terminal.submit_terminal", return_value={
             "launcher_pid": 1, "log_path": str(tmp_path / "x.agent-launch.log"),
         }) as submit:
        assert launch_configured_agent(
            str(tmp_path), mode="tmux", background=True, non_interactive=True) == 0
    assert submit.call_args.kwargs["non_interactive"] is True


def test_background_submission_omits_non_interactive_when_not_requested(tmp_path):
    """An ordinary background launch keeps the historical submission shape."""
    with patch("cli_topsailai.agent_launch._session_id", return_value="fixed"), \
         patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               return_value=({}, set())), \
         patch("cli_topsailai.agent_launch_background.launch_background", return_value={
             "launcher_pid": 1, "log_path": str(tmp_path / "x.agent-launch.log"),
         }) as launch:
        assert launch_configured_agent(str(tmp_path), mode="raw", background=True) == 0
    assert launch.call_args.kwargs["non_interactive"] is False
