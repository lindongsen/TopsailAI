"""Unit tests for topsailai_logf.py."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterator
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import topsailai_logf


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    """Create a fake TOPSAILAI_HOME with a log directory."""
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    return tmp_path


@pytest.fixture
def patched_home(fake_home: Path) -> Iterator[Path]:
    """Patch get_topsailai_home to return the fake home."""
    with mock.patch.object(topsailai_logf, "get_topsailai_home", return_value=str(fake_home)):
        yield fake_home


def test_parse_args_defaults() -> None:
    args = topsailai_logf._parse_args([])
    assert args.ec is False
    assert args.lines == topsailai_logf.DEFAULT_LINES
    assert args.home is None


def test_parse_args_ec() -> None:
    args = topsailai_logf._parse_args(["-e"])
    assert args.ec is True


def test_parse_args_lines_short() -> None:
    args = topsailai_logf._parse_args(["-n", "25"])
    assert args.lines == 25


def test_parse_args_lines_long() -> None:
    args = topsailai_logf._parse_args(["--lines", "50"])
    assert args.lines == 50


def test_parse_args_home_override() -> None:
    args = topsailai_logf._parse_args(["--home", "/tmp/custom"])
    assert args.home == "/tmp/custom"


def test_main_runs_tail_for_default_log(patched_home: Path) -> None:
    log_path = patched_home / "log" / "topsailai.log"
    log_path.write_text("line1\nline2\n")

    with mock.patch("subprocess.call") as mock_call:
        mock_call.return_value = 0
        result = topsailai_logf.main([])

    assert result == 0
    mock_call.assert_called_once_with(
        ["tail", "-f", "-n", str(topsailai_logf.DEFAULT_LINES), str(log_path)]
    )


def test_main_runs_tail_for_ec_log(patched_home: Path) -> None:
    log_path = patched_home / "log" / "topsailai.log.ec"
    log_path.write_text("ec-line1\n")

    with mock.patch("subprocess.call") as mock_call:
        mock_call.return_value = 0
        result = topsailai_logf.main(["-e", "-n", "5"])

    assert result == 0
    mock_call.assert_called_once_with(["tail", "-f", "-n", "5", str(log_path)])


def test_main_uses_home_override() -> None:
    custom_home = Path(os.environ.get("TMPDIR", "/tmp")) / "topsailai_logf_custom"
    custom_home.mkdir(parents=True, exist_ok=True)
    log_dir = custom_home / "log"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "topsailai.log"
    log_path.write_text("custom-line\n")

    try:
        with mock.patch("subprocess.call") as mock_call:
            mock_call.return_value = 0
            result = topsailai_logf.main(["--home", str(custom_home)])

        assert result == 0
        mock_call.assert_called_once_with(
            ["tail", "-f", "-n", str(topsailai_logf.DEFAULT_LINES), str(log_path)]
        )
    finally:
        import shutil
        shutil.rmtree(custom_home, ignore_errors=True)


def test_main_returns_tail_exit_code() -> None:
    with mock.patch("topsailai_logf.get_topsailai_home", return_value="/tmp"):
        with mock.patch("subprocess.call") as mock_call:
            mock_call.return_value = 7
            result = topsailai_logf.main([])

    assert result == 7


def test_main_handles_missing_tail_command() -> None:
    with mock.patch("topsailai_logf.get_topsailai_home", return_value="/tmp"):
        with mock.patch("subprocess.call", side_effect=FileNotFoundError("tail")):
            result = topsailai_logf.main([])

    assert result == 1


def test_main_handles_keyboard_interrupt() -> None:
    with mock.patch("topsailai_logf.get_topsailai_home", return_value="/tmp"):
        with mock.patch("subprocess.call", side_effect=KeyboardInterrupt):
            result = topsailai_logf.main([])

    assert result == 0


def test_main_warns_when_log_file_missing(patched_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch("subprocess.call") as mock_call:
        mock_call.return_value = 0
        result = topsailai_logf.main([])

    assert result == 0
    captured = capsys.readouterr()
    assert "Log file does not exist yet" in captured.err
