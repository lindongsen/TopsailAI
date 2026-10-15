"""Strict, resource-free mapping decoders for Hook resource selections."""

from __future__ import annotations

from typing import Any

from topsailai.hooks.resource_selection_contracts import (
    HookPointResourceSelection,
    HookResourceSelection,
)

_ERROR = "invalid Hook resource selection mapping"
_MAX_FILE_MEMBERS = 1024
_MAX_PATH_LENGTH = 4096


def _mapping(value: object) -> dict[str, Any]:
    """Require an exact string-keyed mapping at the JSON boundary."""
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError(_ERROR)
    return value


def _path(value: object) -> str:
    """Validate one bounded unresolved path without resolving or reading it."""
    if type(value) is not str or not value or "\x00" in value:
        raise ValueError(_ERROR)
    if len(value) > _MAX_PATH_LENGTH:
        raise ValueError(_ERROR)
    return value


def _paths(value: object) -> tuple[str, ...]:
    """Validate and detach a bounded exact list of paths."""
    if type(value) is not list or len(value) > _MAX_FILE_MEMBERS:
        raise ValueError(_ERROR)
    paths = tuple(_path(item) for item in value)
    if len(set(paths)) != len(paths):
        raise ValueError(_ERROR)
    return paths


def decode_resource_selection(value: object) -> HookResourceSelection:
    """Decode one file, files, or folder selection with no side effects."""
    raw = _mapping(value)
    if any(key not in {"file", "files", "folder"} for key in raw):
        raise ValueError(_ERROR)
    present = [key for key in ("file", "files", "folder") if key in raw]
    if len(present) != 1:
        raise ValueError(_ERROR)
    source = present[0]
    if source == "file":
        return HookResourceSelection(files=(_path(raw[source]),))
    if source == "files":
        return HookResourceSelection(files=_paths(raw[source]))
    return HookResourceSelection(folder=_path(raw[source]))


def decode_point_resource_selection(value: object) -> HookPointResourceSelection:
    """Decode optional module and script selections without activating them."""
    raw = _mapping(value)
    if any(key not in {"modules", "scripts"} for key in raw):
        raise ValueError(_ERROR)
    selections: dict[str, HookResourceSelection | None] = {
        "modules": None,
        "scripts": None,
    }
    for kind in selections:
        if kind in raw:
            if raw[kind] is None:
                raise ValueError(_ERROR)
            selections[kind] = decode_resource_selection(raw[kind])
    return HookPointResourceSelection(**selections)
