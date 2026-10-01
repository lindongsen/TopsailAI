"""RED contracts for configured Hooks module discovery and entry validation."""

from __future__ import annotations

import importlib.machinery
import os
from pathlib import Path

import pytest

import topsailai.hooks.module_discovery as discovery_module
from topsailai.tests.unit.test_topsailai_hooks.module_discovery_helpers import (
    compile_extension,
    manifest_entries,
    require_discovery_contract,
    write_module,
)


def _discover(folder: Path, hook_point: str = "conversation.started"):
    """Invoke the future production contract after an attributable in-body check."""
    discovery = require_discovery_contract()
    return discovery(module_folder=folder, hook_point=hook_point)


def test_discovers_only_direct_source_children(tmp_path: Path) -> None:
    """Discovery includes direct source files but never recursively scans children."""
    write_module(tmp_path, "direct")
    nested = tmp_path / "nested"
    nested.mkdir()
    write_module(nested, "indirect")

    result = _discover(tmp_path)

    assert result.accepted
    assert [entry.logical_name for entry in manifest_entries(result)] == ["direct"]


def test_discovers_real_interpreter_compatible_extension(tmp_path: Path) -> None:
    """A real loadable extension using a complete interpreter suffix is admitted."""
    extension = compile_extension(tmp_path, "compiled_hook")

    result = _discover(tmp_path)

    entries = manifest_entries(result)
    assert result.accepted and len(entries) == 1
    assert entries[0].logical_name == "compiled_hook"
    assert entries[0].source_path == extension.resolve()
    assert entries[0].entry_name == "main"
    assert entries[0].entry_valid


def test_complete_suffix_is_removed_to_form_logical_name(tmp_path: Path) -> None:
    """The longest complete runtime suffix is removed, not only its final extension."""
    suffix = max(importlib.machinery.EXTENSION_SUFFIXES, key=len)
    candidate = tmp_path / f"native_name{suffix}"
    candidate.write_bytes(b"not-loadable")

    result = _discover(tmp_path)

    entries = manifest_entries(result)
    assert result.accepted and len(entries) == 1
    assert entries[0].logical_name == "native_name"
    assert entries[0].load_status == "load_error"


def test_ignores_non_candidates_and_symlinks(tmp_path: Path) -> None:
    """Generic files, hidden files, and symlinks are excluded."""
    write_module(tmp_path, "kept")
    (tmp_path / "notes.txt").write_text("not a module", encoding="utf-8")
    (tmp_path / ".hidden.py").write_text("def main(): pass\n", encoding="utf-8")
    (tmp_path / "linked.py").symlink_to(tmp_path / "kept.py")

    result = _discover(tmp_path)

    assert result.accepted
    assert [entry.logical_name for entry in manifest_entries(result)] == ["kept"]


def test_duplicate_logical_identity_rejects_manifest_atomically(tmp_path: Path) -> None:
    """Source and compatible extension variants with one logical name are ambiguous."""
    write_module(tmp_path, "duplicate")
    suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
    (tmp_path / f"duplicate{suffix}").write_bytes(b"duplicate")

    result = _discover(tmp_path)

    assert not result.accepted
    assert manifest_entries(result) == ()
    assert result.errors == ("duplicate module identity",)


def test_identity_and_order_are_stable_and_case_sensitive(tmp_path: Path) -> None:
    """Manifest order uses logical Unicode code points and stable canonical identity."""
    for name in ("zeta", "Alpha", "beta"):
        write_module(tmp_path, name)

    first = _discover(tmp_path, hook_point="agent2llm.finished")
    second = _discover(tmp_path, hook_point="agent2llm.finished")

    first_entries = manifest_entries(first)
    assert [entry.logical_name for entry in first_entries] == ["Alpha", "beta", "zeta"]
    assert [entry.stable_identity for entry in first_entries] == [
        ("agent2llm.finished", str(tmp_path.resolve()), name)
        for name in ("Alpha", "beta", "zeta")
    ]
    assert [entry.stable_identity for entry in manifest_entries(second)] == [
        entry.stable_identity for entry in first_entries
    ]


def test_callable_main_validation_is_per_candidate(tmp_path: Path) -> None:
    """Missing or non-callable main is bounded per module and does not reject peers."""
    write_module(tmp_path, "good")
    write_module(tmp_path, "missing", "VALUE = 1\n")
    write_module(tmp_path, "noncallable", "main = 1\n")

    result = _discover(tmp_path)

    entries = manifest_entries(result)
    assert result.accepted
    assert [(entry.logical_name, entry.entry_valid) for entry in entries] == [
        ("good", True),
        ("missing", False),
        ("noncallable", False),
    ]
    assert [entry.load_status for entry in entries] == ["ready", "invalid_entry", "invalid_entry"]


def test_isolated_load_failure_does_not_suppress_independent_module(tmp_path: Path) -> None:
    """A worker-local import failure does not suppress a later valid candidate."""
    marker = tmp_path / "import-worker-pid"
    write_module(
        tmp_path,
        "broken",
        f"import os\nfrom pathlib import Path\nPath({str(marker)!r}).write_text(str(os.getpid()))\nraise RuntimeError('sentinel')\n",
    )
    write_module(tmp_path, "continues_after_broken")

    result = _discover(tmp_path)

    entries = manifest_entries(result)
    assert result.accepted
    assert [(entry.logical_name, entry.load_status) for entry in entries] == [
        ("broken", "load_error"),
        ("continues_after_broken", "ready"),
    ]
    assert marker.exists(), "recognized candidates must be probed in an isolated worker"
    assert int(marker.read_text(encoding="utf-8")) != os.getpid()
    assert "broken" not in __import__("sys").modules


def _supported_generic_suffix() -> str:
    """Return a generic native suffix supported by this interpreter."""
    for suffix in (".so", ".pyd"):
        if suffix in importlib.machinery.EXTENSION_SUFFIXES:
            return suffix
    pytest.skip("runtime exposes no generic native extension suffix")


def test_enumerates_every_runtime_extension_suffix(tmp_path: Path) -> None:
    """Every complete native suffix supported by the interpreter is recognized."""
    expected = []
    for index, suffix in enumerate(importlib.machinery.EXTENSION_SUFFIXES):
        logical_name = f"native_{index}"
        (tmp_path / f"{logical_name}{suffix}").write_bytes(b"candidate")
        expected.append((logical_name, (tmp_path / f"{logical_name}{suffix}").resolve()))

    candidates = discovery_module._enumerate_candidates(tmp_path.resolve())

    assert sorted(candidates) == sorted(expected)


def test_loads_real_extension_with_supported_generic_suffix(tmp_path: Path) -> None:
    """A loadable extension using a supported generic suffix is admitted."""
    suffix = _supported_generic_suffix()
    extension = compile_extension(tmp_path, "generic_hook", suffix=suffix)

    result = _discover(tmp_path)

    entries = manifest_entries(result)
    assert result.accepted and len(entries) == 1
    assert entries[0].logical_name == "generic_hook"
    assert entries[0].source_path == extension.resolve()
    assert entries[0].load_status == "ready"
    assert entries[0].entry_valid


def test_invalid_generic_binary_does_not_suppress_valid_module(tmp_path: Path) -> None:
    """A recognized invalid generic binary is retained without suppressing peers."""
    suffix = _supported_generic_suffix()
    (tmp_path / f"broken_generic{suffix}").write_bytes(b"not-loadable")
    write_module(tmp_path, "valid_peer")

    result = _discover(tmp_path)

    assert result.accepted
    assert [
        (entry.logical_name, entry.load_status, entry.entry_valid) for entry in result.entries
    ] == [
        ("broken_generic", "load_error", False),
        ("valid_peer", "ready", True),
    ]


def test_foreign_abi_fallback_is_excluded_without_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A foreign ABI tag left by generic matching is not a valid logical name."""
    generic = _supported_generic_suffix()
    supported = set(importlib.machinery.EXTENSION_SUFFIXES)
    foreign_suffix = f".foreign-abi-for-test{generic}"
    assert foreign_suffix not in supported
    (tmp_path / f"foreign_hook{foreign_suffix}").write_bytes(b"foreign")

    def reject_probe(*args: object, **kwargs: object) -> object:
        raise AssertionError("foreign ABI candidate must not be probed")

    monkeypatch.setattr(discovery_module, "_probe_candidate", reject_probe)

    result = _discover(tmp_path)

    assert result.accepted
    assert result.entries == ()


def test_longest_runtime_suffix_wins_even_when_short_suffix_is_listed_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enumeration sorts overlapping suffixes before deriving the logical name."""
    short_suffix = ".so"
    long_suffix = ".tagged.so"
    candidate = tmp_path / f"long_name{long_suffix}"
    candidate.write_bytes(b"candidate")
    monkeypatch.setattr(
        importlib.machinery,
        "EXTENSION_SUFFIXES",
        [short_suffix, long_suffix],
    )

    candidates = discovery_module._enumerate_candidates(tmp_path.resolve())

    assert candidates == [("long_name", candidate.resolve())]


def test_source_and_generic_native_duplicate_rejects_without_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Source and supported generic native identities are atomically ambiguous."""
    generic = _supported_generic_suffix()
    write_module(tmp_path, "duplicate_generic")
    (tmp_path / f"duplicate_generic{generic}").write_bytes(b"candidate")

    def reject_probe(*args: object, **kwargs: object) -> object:
        raise AssertionError("duplicates must be rejected before probing")

    monkeypatch.setattr(discovery_module, "_probe_candidate", reject_probe)

    result = _discover(tmp_path)

    assert not result.accepted
    assert result.entries == ()
    assert result.errors == ("duplicate module identity",)


def test_tagged_and_generic_native_duplicate_rejects_without_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two supported native suffixes cannot select one import-precedence winner."""
    generic = _supported_generic_suffix()
    tagged = next(
        (suffix for suffix in importlib.machinery.EXTENSION_SUFFIXES if suffix != generic),
        None,
    )
    if tagged is None:
        pytest.skip("runtime exposes no overlapping tagged extension suffix")
    (tmp_path / f"duplicate_native{generic}").write_bytes(b"generic")
    (tmp_path / f"duplicate_native{tagged}").write_bytes(b"tagged")

    def reject_probe(*args: object, **kwargs: object) -> object:
        raise AssertionError("duplicates must be rejected before probing")

    monkeypatch.setattr(discovery_module, "_probe_candidate", reject_probe)

    result = _discover(tmp_path)

    assert not result.accepted
    assert result.entries == ()
    assert result.errors == ("duplicate module identity",)


def test_generic_suffix_is_not_accepted_when_runtime_does_not_support_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generic native suffixes are never added outside the runtime support list."""
    unsupported = ".pyd" if ".pyd" not in importlib.machinery.EXTENSION_SUFFIXES else ".so"
    controlled_suffixes = [
        suffix for suffix in importlib.machinery.EXTENSION_SUFFIXES if suffix != unsupported
    ]
    assert unsupported not in controlled_suffixes
    (tmp_path / f"unsupported_generic{unsupported}").write_bytes(b"candidate")
    monkeypatch.setattr(importlib.machinery, "EXTENSION_SUFFIXES", controlled_suffixes)

    candidates = discovery_module._enumerate_candidates(tmp_path.resolve())

    assert candidates == []


def test_candidate_filtering_boundaries_remain_closed(tmp_path: Path) -> None:
    """Hidden, linked, directory, initializer, and invalid names remain excluded."""
    write_module(tmp_path, "kept_boundary")
    write_module(tmp_path, "__init__")
    write_module(tmp_path, "invalid-name")
    (tmp_path / ".hidden_boundary.py").write_text("def main(): pass\n", encoding="utf-8")
    directory = tmp_path / "directory.py"
    directory.mkdir()
    (tmp_path / "linked_boundary.py").symlink_to(tmp_path / "kept_boundary.py")

    candidates = discovery_module._enumerate_candidates(tmp_path.resolve())

    assert candidates == [("kept_boundary", (tmp_path / "kept_boundary.py").resolve())]
