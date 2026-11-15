"""Unit tests for the ``bin/agent_chats`` session-id hand-off.

The wrapper must preserve the difference between "not passed" and "passed
empty", because ``agent_chats._resolve_session_id`` treats an absent alias as
"generate one" and a present blank alias as "run without a session". Exporting
an empty ``SESSION_ID`` when neither alias is set collapses those two cases and
silently disables generation.

Each test runs the real wrapper file. Only the final launch line is replaced
with a probe, so the assertions cover the shipped shell logic instead of a
duplicated copy of it, and no agent process is started.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# The wrapper lives next to the cli directory: <project>/bin/agent_chats.
CLI_DIR = Path(__file__).resolve().parents[3]
WRAPPER = CLI_DIR.parent / "bin" / "agent_chats"

# The wrapper's last line launches the agent; replace it with a probe.
LAUNCH_LINE_PREFIX = "DEBUG=1 run_cli agent_chats"

PROBE = (
    'python3 -c "import os;'
    "print('present=%s value=%r' % ("
    "'SESSION_ID' in os.environ, os.environ.get('SESSION_ID')))"
    '"'
)


def _probe_wrapper(tmp_path: Path) -> Path:
    """Copy the real wrapper and swap its launch line for a probe."""
    source = WRAPPER.read_text(encoding="utf-8")
    lines = source.splitlines()
    replaced = 0
    for index, line in enumerate(lines):
        if line.startswith(LAUNCH_LINE_PREFIX):
            lines[index] = PROBE
            replaced += 1
    assert replaced == 1, "wrapper launch line not found exactly once"

    target = tmp_path / "agent_chats"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    target.chmod(0o755)
    return target


def _run(script: Path, env: dict) -> str:
    """Run the probe wrapper with a clean session environment."""
    base = {
        key: value
        for key, value in os.environ.items()
        if key not in ("SESSION_ID", "TOPSAILAI_SESSION_ID")
    }
    base.update(env)
    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=base,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_wrapper_does_not_export_session_id_when_neither_alias_is_set(
    tmp_path: Path,
) -> None:
    """An unset environment must stay unset so the CLI can generate an id."""
    script = _probe_wrapper(tmp_path)

    assert _run(script, {}) == "present=False value=None"


def test_wrapper_preserves_an_explicitly_empty_session_id(tmp_path: Path) -> None:
    """An explicit empty value must reach the CLI as the opt-out signal."""
    script = _probe_wrapper(tmp_path)

    assert _run(script, {"SESSION_ID": ""}) == "present=True value=''"


def test_wrapper_forwards_topsailai_session_id_to_the_legacy_alias(
    tmp_path: Path,
) -> None:
    """A configured prefixed alias is still published as SESSION_ID."""
    script = _probe_wrapper(tmp_path)

    assert _run(script, {"TOPSAILAI_SESSION_ID": "abc"}) == "present=True value='abc'"


def test_wrapper_preserves_an_explicitly_empty_prefixed_alias(tmp_path: Path) -> None:
    """An empty prefixed alias is an opt-out, not a missing value."""
    script = _probe_wrapper(tmp_path)

    assert _run(script, {"TOPSAILAI_SESSION_ID": ""}) == "present=True value=''"


def test_wrapper_keeps_an_explicit_session_id_over_the_prefixed_alias(
    tmp_path: Path,
) -> None:
    """An explicit SESSION_ID wins over TOPSAILAI_SESSION_ID."""
    script = _probe_wrapper(tmp_path)

    assert _run(script, {"SESSION_ID": "xyz", "TOPSAILAI_SESSION_ID": "abc"}) == (
        "present=True value='xyz'"
    )


@pytest.mark.parametrize("blank", ["", "   "])
def test_wrapper_blank_values_reach_the_cli_unchanged(
    tmp_path: Path, blank: str
) -> None:
    """Whitespace-only values are forwarded verbatim, not normalized."""
    script = _probe_wrapper(tmp_path)

    assert _run(script, {"SESSION_ID": blank}) == f"present=True value={blank!r}"
