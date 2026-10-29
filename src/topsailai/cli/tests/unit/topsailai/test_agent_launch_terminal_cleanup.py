"""Tests for the selectable background terminal mechanisms."""

import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import time
import uuid
from pathlib import Path
from unittest.mock import patch
import pytest
from cli_topsailai import agent_launch_terminal as terminal

from test_agent_launch_terminal_helpers import *

@pytest.mark.parametrize("mechanism", ["tmux", "dtach"])
def test_pre_submission_interrupt_cancels_launcher_before_container_stop(
        monkeypatch, mechanism):
    """An interrupted launch must cancel the launcher before stopping the container.

    The launcher lives in its own process session, so stopping the supervisor
    first would orphan a live launcher. Cancellation must therefore be requested
    first, and launcher death must be proven before the fallback cleanup.
    """
    order = []
    transport = _FakeTransport(order)
    _install_submit_doubles(monkeypatch, transport,
                            protocol_error=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        terminal.submit_terminal("/work/proj", "session-1", mechanism=mechanism)

    assert "cancel" in order
    assert order.index("cancel") < order.index("reap")
    assert order.index("reap") < order.index("launcher_gone")
    assert order.index("launcher_gone") < order.index("cleanup")
    assert transport.closed is True


@pytest.mark.parametrize("mechanism", ["tmux", "dtach"])
def test_pre_submission_interrupt_reports_unproven_launcher_custody(
        monkeypatch, mechanism, capsys):
    """A launcher that is still alive after cancellation is never reported clean."""
    order = []
    transport = _FakeTransport(order)
    _install_submit_doubles(monkeypatch, transport,
                            protocol_error=KeyboardInterrupt())
    monkeypatch.setattr(terminal, "_launcher_gone",
                        lambda t, **k: order.append("launcher_gone") or False)

    with pytest.raises(KeyboardInterrupt):
        terminal.submit_terminal("/work/proj", "session-1", mechanism=mechanism)

    assert "terminal custody unproven" in capsys.readouterr().out


def test_pre_submission_failure_without_in_flight_error_raises_custody_error(
        monkeypatch):
    """A custody failure on a clean return path is raised, not swallowed."""
    order = []
    transport = _FakeTransport(order)
    _install_submit_doubles(monkeypatch, transport, protocol_error=RuntimeError("boom"))
    monkeypatch.setattr(terminal, "_launcher_gone",
                        lambda t, **k: order.append("launcher_gone") or False)

    with pytest.raises(RuntimeError, match="boom"):
        terminal.submit_terminal("/work/proj", "session-1", mechanism="tmux")


def test_real_started_parser_failure_continues_all_cleanup(monkeypatch, capsys):
    """A real invalid started frame cannot abort later release steps."""
    order = []
    transport = _FakeTransport(order)
    _install_submit_doubles(monkeypatch, transport,
                            protocol_error=KeyboardInterrupt("PRIMARY"))

    def invalid_reconcile(current, **kwargs):
        from cli_topsailai import agent_launch_background as bg
        order.append("real_reconcile_invalid_started")
        terminal._record(current, {"kind": "started", "session": "wrong"},
                         "session-1")
        return None

    monkeypatch.setattr(terminal, "_reconcile", invalid_reconcile)

    with pytest.raises(KeyboardInterrupt, match="PRIMARY"):
        terminal.submit_terminal("/work/proj", "session-1", mechanism="tmux")

    assert order[:4] == ["cancel", "real_reconcile_invalid_started",
                         "reap", "launcher_gone"]
    assert transport.closed is True
    assert "Preserving terminal attempt material" in capsys.readouterr().out


@pytest.mark.parametrize("exception", [ValueError("bad"), KeyError("bad"),
                                        AttributeError("bad")])
def test_ordinary_cleanup_errors_continue_release(monkeypatch, exception):
    """Ordinary cleanup errors never skip later release boundaries."""
    order = []
    transport = _FakeTransport(order)
    _install_submit_doubles(monkeypatch, transport,
                            protocol_error=KeyboardInterrupt("PRIMARY"))
    monkeypatch.setattr(terminal, "_reconcile", lambda *args, **kwargs:
                        (_ for _ in ()).throw(exception))

    with pytest.raises(KeyboardInterrupt, match="PRIMARY"):
        terminal.submit_terminal("/work/proj", "session-1", mechanism="tmux")

    assert "reap" in order
    assert "launcher_gone" in order
    assert transport.closed is True


@pytest.mark.parametrize("failing_step", ["reconcile", "reap"])
def test_cleanup_failure_never_masks_the_primary_exception(
        monkeypatch, capsys, failing_step):
    """A cleanup-phase failure must not replace the exception already propagating.

    The interruption is the primary fact. If reconciliation or reaping raises,
    the original KeyboardInterrupt must still surface, and the remaining release
    steps (transport close and the attempt-material decision) must still run.
    """
    order = []
    transport = _FakeTransport(order)
    _install_submit_doubles(monkeypatch, transport,
                            protocol_error=KeyboardInterrupt("PRIMARY"))

    def boom(*args, **kwargs):
        order.append(f"{failing_step}_raised")
        raise terminal.TerminalUnconfirmed(f"{failing_step} cleanup read failed")

    if failing_step == "reconcile":
        monkeypatch.setattr(terminal, "_reconcile", boom)
    else:
        monkeypatch.setattr(transport, "reap", boom)

    with pytest.raises(KeyboardInterrupt) as error:
        terminal.submit_terminal("/work/proj", "session-1", mechanism="tmux")

    assert str(error.value) == "PRIMARY"
    assert transport.closed is True
    assert "launcher_gone" in order
    output = capsys.readouterr().out
    assert f"{failing_step} cleanup read failed" in output
    assert "terminal custody unproven" in output
    # Custody is unproven, so the attempt material is preserved, not deleted.
    assert "Preserving terminal attempt material" in output


def test_cleanup_failure_preserves_attempt_when_ownership_is_unknown(
        monkeypatch, capsys):
    """A supervisor exit cannot prove launcher custody without ownership."""
    order = []
    transport = _FakeTransport(order, ownership=False)
    _install_submit_doubles(monkeypatch, transport,
                            protocol_error=KeyboardInterrupt("PRIMARY"))

    def boom(*args, **kwargs):
        raise terminal.TerminalUnconfirmed("reconcile cleanup read failed")

    monkeypatch.setattr(terminal, "_reconcile", boom)

    with pytest.raises(KeyboardInterrupt) as error:
        terminal.submit_terminal("/work/proj", "session-1", mechanism="tmux")

    assert str(error.value) == "PRIMARY"
    assert transport.closed is True
    assert "cleanup" not in order
    output = capsys.readouterr().out
    assert "reconcile cleanup read failed" in output
    assert "Preserving terminal attempt material" in output


def test_generator_exit_propagates_after_safe_cleanup(monkeypatch):
    """GeneratorExit is deferred until all safe cleanup steps have run."""
    order = []
    transport = _FakeTransport(order)
    attempt = _install_submit_doubles(monkeypatch, transport,
                                      protocol_error=RuntimeError("unused"))
    monkeypatch.setattr(terminal, "_reconcile",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            GeneratorExit("HOST")))
    monkeypatch.setattr(terminal, "_launcher_gone",
                        lambda *args, **kwargs: order.append("launcher_gone") or True)
    with pytest.raises(GeneratorExit, match="HOST"):
        terminal._release_after_failure(
            attempt, transport, None, None, clock=time.monotonic,
            sleeper=lambda _: None)
    assert "reap" in order
    assert "launcher_gone" in order
    assert transport.closed is True


def test_cleanup_failure_on_clean_return_raises_custody_error(monkeypatch):
    """Without an in-flight exception, unproven custody is raised, not swallowed."""
    order = []
    transport = _FakeTransport(order)
    _install_submit_doubles(monkeypatch, transport, protocol_error=RuntimeError("boom"))

    def boom(*args, **kwargs):
        raise terminal.TerminalUnconfirmed("reconcile failed")

    monkeypatch.setattr(terminal, "_reconcile", boom)

    with pytest.raises(RuntimeError, match="boom"):
        terminal.submit_terminal("/work/proj", "session-1", mechanism="tmux")
    assert transport.closed is True


def test_unproven_custody_preserves_attempt_material(monkeypatch, capsys):
    """Unproven custody must not delete the only evidence of what was created."""
    order = []
    transport = _FakeTransport(order)
    _install_submit_doubles(monkeypatch, transport,
                            protocol_error=KeyboardInterrupt())
    monkeypatch.setattr(terminal, "_launcher_gone",
                        lambda t, **k: order.append("launcher_gone") or False)

    with pytest.raises(KeyboardInterrupt):
        terminal.submit_terminal("/work/proj", "session-1", mechanism="tmux")

    assert "cleanup" not in order
    assert "Preserving terminal attempt material" in capsys.readouterr().out
