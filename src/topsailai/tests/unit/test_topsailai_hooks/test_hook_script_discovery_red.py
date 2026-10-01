"""RED contracts for executable hook_script discovery and static validation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from topsailai.tests.unit.test_topsailai_hooks.hook_script_discovery_helpers import (
    discover,
    make_fifo,
    result_entries,
    write_native,
    write_script,
)


def test_direct_executable_file_yields_one_canonical_entry(tmp_path: Path) -> None:
    """One directly configured executable file yields exactly one static entry."""
    candidate = write_script(tmp_path, "single-hook")

    result = discover(candidate)

    entries = result_entries(result)
    assert result.accepted and result.errors == ()
    assert len(entries) == 1
    assert entries[0].source_path == candidate.resolve()
    assert entries[0].basename == "single-hook"


def test_directory_discovers_only_direct_children_in_case_sensitive_order(
    tmp_path: Path,
) -> None:
    """Directory discovery is non-recursive and ordered by exact filename."""
    for name in ("alpha", "Zulu", "beta"):
        write_script(tmp_path, name)
    nested = tmp_path / "nested"
    nested.mkdir()
    write_script(nested, "indirect")

    first = discover(tmp_path)
    second = discover(tmp_path)

    expected = ["Zulu", "alpha", "beta"]
    assert [entry.basename for entry in result_entries(first)] == expected
    assert [entry.basename for entry in result_entries(second)] == expected


def test_missing_or_empty_target_rejects_without_entries_or_scan(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Missing and empty configured targets reject before directory enumeration."""
    result = discover(tmp_path / "missing")
    scanned = False

    def forbidden_scan(path: Path) -> tuple[Path, ...]:
        nonlocal scanned
        scanned = True
        raise AssertionError(f"empty hook_script target scanned directory: {path}")

    class EmptyPathLike:
        """Provide an empty path representation through the public PathLike boundary."""

        def __fspath__(self) -> str:
            """Return the empty path representation under test."""
            return ""

    monkeypatch.setattr(Path, "iterdir", forbidden_scan)
    empty_results = (discover(""), discover(EmptyPathLike()))

    assert not result.accepted
    assert result_entries(result) == ()
    assert result.errors == ("hook_script target is invalid",)
    for empty_result in empty_results:
        assert not empty_result.accepted
        assert result_entries(empty_result) == ()
        assert empty_result.errors == ("hook_script target is invalid",)
    assert not scanned


def test_direct_symlink_and_special_file_targets_reject(tmp_path: Path) -> None:
    """Direct symbolic-link and special-file targets are never admitted."""
    regular = write_script(tmp_path, "regular")
    link = tmp_path / "linked"
    link.symlink_to(regular)
    fifo = make_fifo(tmp_path / "special")

    linked_result = discover(link)
    special_result = discover(fifo)

    for result in (linked_result, special_result):
        assert not result.accepted
        assert result_entries(result) == ()
        assert result.errors == ("hook_script target is invalid",)


def test_directory_excludes_symlink_special_and_non_executable_entries(
    tmp_path: Path,
) -> None:
    """Unsafe or non-executable direct children are excluded without recursion."""
    kept = write_script(tmp_path, "kept")
    write_script(tmp_path, "plain-text", executable=False)
    (tmp_path / "linked").symlink_to(kept)
    make_fifo(tmp_path / "special")
    (tmp_path / "child-directory").mkdir()

    result = discover(tmp_path)

    assert result.accepted
    assert [entry.basename for entry in result_entries(result)] == ["kept"]


def test_resolved_candidate_escape_rejects_directory_atomically(tmp_path: Path) -> None:
    """A child resolving outside its configured canonical root rejects the snapshot."""
    candidate = write_script(tmp_path, "candidate")
    outside = write_script(tmp_path.parent, "outside-hook-script")

    def escape_on_resolve(path: Path) -> Path:
        if path == candidate:
            return outside.resolve()
        return path.resolve()

    result = discover(tmp_path, resolve_path=escape_on_resolve)

    assert not result.accepted
    assert result_entries(result) == ()
    assert result.errors == ("hook_script path escapes configured root",)


def test_non_executable_file_rejects_but_empty_directory_is_successful_noop(
    tmp_path: Path,
) -> None:
    """Direct non-executable files reject while an empty candidate set is a no-op."""
    candidate = write_script(tmp_path, "not-executable", executable=False)

    direct = discover(candidate)
    directory = discover(tmp_path)

    assert not direct.accepted
    assert result_entries(direct) == ()
    assert direct.errors == ("configured hook_script file is not executable",)
    assert directory.accepted
    assert result_entries(directory) == ()
    assert directory.errors == ()


def test_posix_static_policy_requires_permission_and_allowed_shebang_or_native(
    tmp_path: Path,
) -> None:
    """POSIX text admission uses exact shebang policy while native files remain direct."""
    allowed = write_script(tmp_path, "allowed", shebang="#!/usr/bin/env python3")
    write_script(tmp_path, "disallowed", shebang="#!/opt/private/python")
    write_script(tmp_path, "missing-shebang", shebang="echo not-a-shebang")
    native = write_native(tmp_path, "native")

    result = discover(
        tmp_path,
        allowed_interpreters=("/usr/bin/env",),
    )

    assert result.accepted
    assert [entry.source_path for entry in result_entries(result)] == [
        allowed.resolve(),
        native.resolve(),
    ]


def test_windows_policy_allows_only_explicit_native_entries(tmp_path: Path) -> None:
    """Windows policy requires PE format and never uses script launch fallback."""
    native = write_native(tmp_path, "accepted.EXE", file_format="pe")
    write_native(tmp_path, "renamed-elf.exe", file_format="elf")
    write_script(tmp_path, "renamed-script.exe")
    truncated = tmp_path / "truncated-mz.exe"
    truncated.write_bytes(b"MZ-truncated")
    truncated.chmod(0o700)
    for name in ("rejected.py", "rejected.bat", "rejected.cmd", "rejected.ps1"):
        write_script(tmp_path, name)

    result = discover(
        tmp_path,
        platform="windows",
        allowed_interpreters=(),
        native_suffixes=(".exe",),
    )

    assert result.accepted
    assert [entry.source_path for entry in result_entries(result)] == [native.resolve()]


def test_discovery_and_validation_never_start_candidate_processes(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Static admission performs no subprocess, shell, or candidate execution."""
    marker = tmp_path / "executed"
    write_script(tmp_path, "must-not-run", shebang="#!/bin/sh")

    def forbidden(*args: object, **kwargs: object) -> None:
        marker.write_text("started", encoding="utf-8")
        raise AssertionError("static discovery attempted process execution")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "system", forbidden)

    result = discover(tmp_path)

    assert result.accepted
    assert len(result_entries(result)) == 1
    assert not marker.exists()
