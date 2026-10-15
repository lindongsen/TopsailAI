"""Immutable contracts for passive Hook resource selection."""

from __future__ import annotations

from dataclasses import dataclass

_MAX_FILE_MEMBERS = 1024
_MAX_PATH_LENGTH = 4096


def _validate_path(value: object) -> str:
    """Validate one unresolved, bounded resource path."""
    if type(value) is not str or not value or "\x00" in value:
        raise ValueError("resource paths must be non-empty strings without NUL")
    if len(value) > _MAX_PATH_LENGTH:
        raise ValueError("resource path exceeds maximum length")
    return value


def _validate_files(value: object) -> tuple[str, ...]:
    """Validate and detach an immutable collection of resource paths."""
    if type(value) is not tuple:
        raise TypeError("files must be an immutable tuple")
    if len(value) > _MAX_FILE_MEMBERS:
        raise ValueError("resource selection has too many files")
    paths = tuple(_validate_path(item) for item in value)
    if len(set(paths)) != len(paths):
        raise ValueError("resource selection contains duplicate paths")
    return paths


@dataclass(frozen=True, slots=True)
class HookResourceSelection:
    """Select explicit files or one unresolved folder for one Hook kind."""

    files: tuple[str, ...] = ()
    folder: str | None = None

    def __post_init__(self) -> None:
        """Enforce detached constructor invariants without performing I/O."""
        files = _validate_files(self.files)
        if self.folder is not None:
            _validate_path(self.folder)
        if bool(files) == (self.folder is not None):
            raise ValueError("selection must contain exactly files or folder")
        object.__setattr__(self, "files", files)


@dataclass(frozen=True, slots=True)
class HookPointResourceSelection:
    """Select Modules and Scripts using the same passive source contract."""

    modules: HookResourceSelection | None = None
    scripts: HookResourceSelection | None = None

    def __post_init__(self) -> None:
        """Reject non-contract values while retaining immutable selections."""
        for value in (self.modules, self.scripts):
            if value is not None and type(value) is not HookResourceSelection:
                raise TypeError("point selections must use HookResourceSelection")
