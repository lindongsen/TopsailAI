"""Focused tests for immutable Hook resource-selection contracts."""

from __future__ import annotations

import pytest

from topsailai.hooks.resource_selection_contracts import (
    HookPointResourceSelection,
    HookResourceSelection,
)
from topsailai.hooks.resource_selection_mapping import decode_point_resource_selection


@pytest.mark.parametrize(
    ("kind", "source", "expected_files", "expected_folder"),
    [
        ("modules", {"file": "module.py"}, ("module.py",), None),
        ("modules", {"files": ["a.py", "b.py"]}, ("a.py", "b.py"), None),
        ("modules", {"folder": "modules"}, (), "modules"),
        ("scripts", {"file": "run.sh"}, ("run.sh",), None),
        ("scripts", {"files": ["a.sh", "b.sh"]}, ("a.sh", "b.sh"), None),
        ("scripts", {"folder": "scripts"}, (), "scripts"),
    ],
)
def test_contract_matrix_uses_exact_values(
    kind: str,
    source: dict[str, object],
    expected_files: tuple[str, ...],
    expected_folder: str | None,
) -> None:
    """Both Hook kinds use the same immutable source grammar and values."""
    point = decode_point_resource_selection({kind: source})
    selected = getattr(point, kind)
    other = point.scripts if kind == "modules" else point.modules
    assert selected is not None
    assert selected.files == expected_files
    assert selected.folder == expected_folder
    assert other is None


def test_contracts_accept_direct_file_and_folder_forms() -> None:
    """Direct constructors retain explicit files or one folder as immutable values."""
    file_selection = HookResourceSelection(files=("module.py",))
    folder_selection = HookResourceSelection(folder="scripts")
    point = HookPointResourceSelection(modules=file_selection, scripts=folder_selection)
    assert file_selection.files == ("module.py",)
    assert file_selection.folder is None
    assert folder_selection.files == ()
    assert folder_selection.folder == "scripts"
    assert point.modules is file_selection
    assert point.scripts is folder_selection


@pytest.mark.parametrize("path", ["x" * 4096, "目录/脚本.sh", "/absolute/path"])
def test_contract_accepts_boundary_and_unicode_paths(path: str) -> None:
    """Valid boundary and Unicode paths remain unresolved and unchanged."""
    if len(path) == 4096:
        assert HookResourceSelection(files=(path,)).files == (path,)
        assert HookResourceSelection(folder=path).folder == path
    else:
        assert HookResourceSelection(folder=path).folder == path


@pytest.mark.parametrize("value", ["", "a\x00b", "a" * 4097, 1, True, None])
def test_contract_rejects_invalid_folder_values(value: object) -> None:
    """Folder values must be non-empty bounded exact strings without NUL."""
    with pytest.raises((TypeError, ValueError)):
        HookResourceSelection(folder=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("members", [(), ("a", "a"), ("a\x00b",), ("",), ("a" * 4097,)])
def test_contract_rejects_invalid_file_values(members: tuple[str, ...]) -> None:
    """Empty, duplicate, NUL-containing, and oversized values are rejected."""
    with pytest.raises(ValueError):
        HookResourceSelection(files=members)


def test_contract_requires_exact_source_form() -> None:
    """A selection cannot mix sources or omit every source."""
    with pytest.raises(ValueError, match="exactly files or folder"):
        HookResourceSelection()
    with pytest.raises(ValueError, match="exactly files or folder"):
        HookResourceSelection(files=("a",), folder="folder")


def test_contracts_are_frozen_and_slotted() -> None:
    """Contracts reject assignment and do not expose instance dictionaries."""
    selection = HookResourceSelection(files=("a",))
    point = HookPointResourceSelection(modules=selection)
    with pytest.raises((AttributeError, TypeError)):
        selection.files = ("b",)  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        point.modules = None  # type: ignore[misc]
    assert not hasattr(selection, "__dict__")
    assert not hasattr(point, "__dict__")


def test_contract_rejects_mutable_or_wrong_nested_values() -> None:
    """Constructors require detached tuple paths and typed point selections."""
    for value in (["a"], ("a",), True, "a"):
        if type(value) is tuple:
            continue
        with pytest.raises(TypeError, match="immutable tuple"):
            HookResourceSelection(files=value)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="HookResourceSelection"):
        HookPointResourceSelection(modules={})  # type: ignore[arg-type]


@pytest.mark.parametrize("members", [True, ["a"], (True,), (1,), ("a", "b")])
def test_constructor_rejects_non_exact_member_containers_or_values(members: object) -> None:
    """Constructor validation rejects booleans and non-string members safely."""
    if members == ("a", "b"):
        return
    with pytest.raises((TypeError, ValueError)):
        HookResourceSelection(files=members)  # type: ignore[arg-type]


class _StringSubclass(str):
    """A string lookalike rejected by exact-type validation."""


class _MaliciousString(str):
    """A string lookalike whose behavior must never be invoked."""

    def __bool__(self):
        raise AssertionError("custom truth testing must not run")

    def __len__(self):
        raise AssertionError("custom length must not run")

    def __contains__(self, value: object) -> bool:
        raise AssertionError("custom containment must not run")

    def __str__(self) -> str:
        raise AssertionError("custom string conversion must not run")

    def __eq__(self, other: object) -> bool:
        raise AssertionError("custom equality must not run")


class _MaliciousTuple(tuple[str, ...]):
    """A tuple lookalike that must be rejected before custom behavior runs."""

    def __iter__(self):
        raise AssertionError("custom iteration must not run")

    def __len__(self):
        raise AssertionError("custom length must not run")

    def __eq__(self, other: object) -> bool:
        raise AssertionError("custom equality must not run")


def test_contract_rejects_tuple_and_string_subclasses_without_invoking_them() -> None:
    """Exact-container and exact-string checks prevent arbitrary behavior."""
    with pytest.raises(TypeError, match="immutable tuple"):
        HookResourceSelection(files=_MaliciousTuple(("a",)))
    with pytest.raises((TypeError, ValueError)):
        HookResourceSelection(files=(_StringSubclass("a"),))


def test_direct_constructors_reject_malicious_file_and_folder_strings() -> None:
    """Direct file and folder constructors reject strings without calling hooks."""
    malicious_file = _MaliciousString("a")
    malicious_folder = _MaliciousString("folder")
    with pytest.raises((TypeError, ValueError)):
        HookResourceSelection(files=(malicious_file,))
    with pytest.raises((TypeError, ValueError)):
        HookResourceSelection(folder=malicious_folder)


@pytest.mark.parametrize("value", [_StringSubclass("a"), True, 1, None])
def test_constructor_rejects_invalid_folder_types(value: object) -> None:
    """Direct folder construction rejects exact-type violations."""
    with pytest.raises((TypeError, ValueError)):
        HookResourceSelection(folder=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("member", [_StringSubclass("a"), True, 1, None])
def test_constructor_rejects_invalid_file_member_types(member: object) -> None:
    """Direct file construction rejects exact-type violations."""
    with pytest.raises((TypeError, ValueError)):
        HookResourceSelection(files=(member,))  # type: ignore[arg-type]


def test_contract_enforces_file_member_limit() -> None:
    """The 1024-member boundary is accepted and the next member is rejected."""
    accepted = tuple(str(index) for index in range(1024))
    assert HookResourceSelection(files=accepted).files == accepted
    with pytest.raises(ValueError, match="too many files"):
        HookResourceSelection(files=accepted + ("1024",))
