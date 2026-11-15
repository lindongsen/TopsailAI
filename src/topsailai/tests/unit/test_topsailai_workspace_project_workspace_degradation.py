'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-14
  Purpose: Prove the project-workspace fallback degrades safely when session
           storage is unreachable or empty, and pin the observable contract that
           an empty store is indistinguishable from "this session has no
           workspace". The empty-store case is a real false-negative risk, so it
           is asserted explicitly instead of being left implicit.
'''

import os
import subprocess
import sys
import textwrap

import pytest

# The package root, used so the child process imports this checkout rather than
# an installed copy. The file lives at ``<root>/topsailai/tests/unit``, so the
# root is four levels above it.
SOURCE_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
)


def _run_child(body, home):
    """Run *body* in a fresh interpreter whose home is *home*.

    A child process is required because the package changes the working
    directory once at import time, so the storage location cannot be redirected
    inside an already-imported process.
    """
    script = textwrap.dedent(body)
    env = dict(os.environ)
    env["PYTHONPATH"] = SOURCE_ROOT
    env["TOPSAILAI_HOME"] = str(home)
    env.pop("CONTEXT_HISTORY_MANAGERS", None)
    env.pop("TOPSAILAI_PROJECT_WORKSPACE", None)
    env.pop("TOPSAILAI_PROJECT_FOLDER", None)
    env.pop("SESSION_ID", None)
    env.pop("TOPSAILAI_SESSION_ID", None)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )


def test_empty_store_degrades_to_none_without_raising(tmp_path):
    """An empty session store yields ``None`` instead of an exception.

    This is the documented degradation contract: a caller keeps its own default
    rather than failing startup. It is also the false-negative case, because an
    empty store and a session without a workspace are indistinguishable here.
    """
    result = _run_child(
        """
        from topsailai.workspace import project_workspace

        value = project_workspace.resolve_project_workspace(session_id="s-absent")
        print("RESULT:", repr(value))
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "RESULT: None" in result.stdout


def test_empty_store_is_indistinguishable_from_a_missing_workspace(tmp_path):
    """Both an empty store and a workspace-less record resolve to ``None``.

    Pinning this equality makes the false-negative explicit: a caller cannot
    tell "storage was empty" from "this session has no workspace", so the
    fallback must never be treated as proof that a session has no workspace.
    """
    result = _run_child(
        """
        from types import SimpleNamespace

        from topsailai.context import ctx_manager
        from topsailai.workspace import project_workspace

        class EmptyManager:
            def get_session(self, session_id):
                return None

        class BlankManager:
            def get_session(self, session_id):
                return SimpleNamespace(project_workspace="")

        ctx_manager.get_session_manager = lambda: EmptyManager()
        empty = project_workspace.resolve_project_workspace(session_id="s-empty")

        project_workspace._LOOKUP_CACHE.clear()
        ctx_manager.get_session_manager = lambda: BlankManager()
        blank = project_workspace.resolve_project_workspace(session_id="s-blank")

        print("EMPTY:", repr(empty))
        print("BLANK:", repr(blank))
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "EMPTY: None" in result.stdout
    assert "BLANK: None" in result.stdout


def test_unreadable_store_degrades_to_none_and_logs(tmp_path):
    """A storage failure yields ``None`` and is logged for diagnosis.

    A silent ``None`` would be undiagnosable, so the warning is part of the
    contract rather than an implementation detail.
    """
    result = _run_child(
        """
        import logging

        from topsailai.context import ctx_manager
        from topsailai.workspace import project_workspace

        # The package installs its own root handlers, so ``basicConfig`` is a
        # no-op here. A handler on the module logger observes the record
        # regardless of how the root logger is configured.
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        project_workspace.logger.addHandler(Capture())
        project_workspace.logger.setLevel(logging.WARNING)

        def explode():
            raise RuntimeError("storage unavailable")

        ctx_manager.get_session_manager = explode
        value = project_workspace.resolve_project_workspace(session_id="s-broken")
        print("RESULT:", repr(value))
        print("LEVELS:", [record.levelname for record in records])
        print("MESSAGES:", [record.getMessage() for record in records])
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "RESULT: None" in result.stdout
    assert "LEVELS: ['WARNING']" in result.stdout
    assert "storage unavailable" in result.stdout


def test_environment_value_never_touches_storage(tmp_path):
    """An exported workspace resolves without any storage access.

    This is the reason the fallback is cheap on the normal path: a correctly
    exported environment must not pay for a database lookup.
    """
    result = _run_child(
        """
        import os

        from topsailai.context import ctx_manager
        from topsailai.workspace import project_workspace

        def explode():
            raise AssertionError("storage must not be reached")

        ctx_manager.get_session_manager = explode
        os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = "/env/wins"
        print("RESULT:", repr(project_workspace.resolve_project_workspace()))
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "RESULT: '/env/wins'" in result.stdout
