"""Shell-free executable hook_script discovery and static validation."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_TARGET_INVALID = "hook_script target is invalid"
_TARGET_NOT_EXECUTABLE = "configured hook_script file is not executable"
_PATH_ESCAPE = "hook_script path escapes configured root"
_MAX_HEADER_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class ExecutablePlatformPolicy:
    """Define an injected, shell-free executable static-admission policy."""

    platform: str
    allowed_interpreters: tuple[str, ...] = ()
    native_suffixes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject ambiguous policy values before filesystem discovery."""
        if self.platform not in ("posix", "windows"):
            raise ValueError("platform must be posix or windows")
        if type(self.allowed_interpreters) is not tuple or any(
            type(value) is not str or not value for value in self.allowed_interpreters
        ):
            raise ValueError("allowed_interpreters must contain non-empty strings")
        if type(self.native_suffixes) is not tuple or any(
            type(value) is not str or not value for value in self.native_suffixes
        ):
            raise ValueError("native_suffixes must contain non-empty strings")


@dataclass(frozen=True, slots=True)
class HookScriptEntry:
    """Describe one canonical executable admitted by static validation."""

    source_path: Path
    basename: str
    registered_name: str | None = None

    @property
    def final_registered_name(self) -> str:
        """Use the explicit identity verbatim, with legacy basename fallback."""
        return self.basename if self.registered_name is None else self.registered_name


@dataclass(frozen=True, slots=True)
class HookScriptDiscoveryResult:
    """Return one atomically accepted immutable executable snapshot."""

    accepted: bool
    entries: tuple[HookScriptEntry, ...] = ()
    errors: tuple[str, ...] = ()


def discover_hook_script_entries(
    target: os.PathLike[str] | str,
    platform_policy: ExecutablePlatformPolicy,
    *,
    resolve_path: Callable[[Path], Path] | None = None,
) -> HookScriptDiscoveryResult:
    """Discover a file or direct directory children without executing candidates."""
    if type(platform_policy) is not ExecutablePlatformPolicy:
        return _rejected(_TARGET_INVALID)
    target_path = _target_path(target)
    if target_path is None:
        return _rejected(_TARGET_INVALID)
    try:
        target_status = target_path.lstat()
    except (OSError, ValueError):
        return _rejected(_TARGET_INVALID)
    if stat.S_ISLNK(target_status.st_mode):
        return _rejected(_TARGET_INVALID)
    if stat.S_ISREG(target_status.st_mode):
        return _discover_file(target_path, platform_policy)
    if stat.S_ISDIR(target_status.st_mode):
        return _discover_directory(
            target_path,
            platform_policy,
            resolve_path or _resolve_strict,
        )
    return _rejected(_TARGET_INVALID)


def _target_path(target: object) -> Path | None:
    """Convert one non-empty path-like target without resolving a symbolic link."""
    if not isinstance(target, (str, os.PathLike)):
        return None
    try:
        raw_target = os.fspath(target)
    except (TypeError, ValueError):
        return None
    if not isinstance(raw_target, str) or not raw_target:
        return None
    try:
        return Path(raw_target)
    except (TypeError, ValueError):
        return None


def _discover_file(
    candidate: Path,
    policy: ExecutablePlatformPolicy,
) -> HookScriptDiscoveryResult:
    """Validate one directly configured regular file."""
    if not _has_execute_permission(candidate):
        return _rejected(_TARGET_NOT_EXECUTABLE)
    try:
        canonical = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return _rejected(_TARGET_INVALID)
    if not _is_admitted(canonical, policy):
        return _rejected(_TARGET_NOT_EXECUTABLE)
    return HookScriptDiscoveryResult(True, (HookScriptEntry(canonical, candidate.name),))


def _discover_directory(
    root_path: Path,
    policy: ExecutablePlatformPolicy,
    resolver: Callable[[Path], Path],
) -> HookScriptDiscoveryResult:
    """Validate direct regular-file children and publish one atomic snapshot."""
    try:
        root = root_path.resolve(strict=True)
        children = tuple(root_path.iterdir())
    except (OSError, RuntimeError, ValueError):
        return _rejected(_TARGET_INVALID)
    entries: list[HookScriptEntry] = []
    for child in children:
        try:
            child_status = child.lstat()
        except (OSError, ValueError):
            continue
        if stat.S_ISLNK(child_status.st_mode) or not stat.S_ISREG(child_status.st_mode):
            continue
        try:
            canonical = Path(resolver(child))
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if not canonical.is_absolute():
            try:
                canonical = canonical.resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                continue
        if not canonical.is_relative_to(root):
            return _rejected(_PATH_ESCAPE)
        if not _has_execute_permission(child) or not _is_admitted(canonical, policy):
            continue
        entries.append(HookScriptEntry(canonical, child.name))
    entries.sort(key=lambda entry: (entry.basename, entry.source_path.name))
    return HookScriptDiscoveryResult(True, tuple(entries))


def _resolve_strict(path: Path) -> Path:
    """Resolve one candidate through the injectable filesystem boundary."""
    return path.resolve(strict=True)


def discover_configured_hook_scripts(
    *,
    scripts: tuple[os.PathLike[str] | str, ...] | None,
    folder: os.PathLike[str] | str | None,
    platform_policy: ExecutablePlatformPolicy,
    max_resources: int | None = None,
) -> HookScriptDiscoveryResult:
    """Discover atomically, optionally bounding configured resource admission."""
    if max_resources is not None and (type(max_resources) is not int or max_resources < 1):
        return _rejected(_TARGET_INVALID)
    if (scripts is None) == (folder is None):
        return _rejected(_TARGET_INVALID)
    if scripts is not None:
        if type(scripts) is not tuple:
            return _rejected(_TARGET_INVALID)
        if max_resources is not None and len(scripts) > max_resources:
            return _rejected("registration_capacity_exceeded")
        entries: list[HookScriptEntry] = []
        for target in scripts:
            result = discover_hook_script_entries(target, platform_policy)
            if not result.accepted or len(result.entries) != 1:
                return result if not result.accepted else _rejected(_TARGET_INVALID)
            entries.append(result.entries[0])
        return _unique_entries(entries)
    return _discover_recursive_directory(folder, platform_policy, max_resources)


def _discover_recursive_directory(
    target: os.PathLike[str] | str | None,
    policy: ExecutablePlatformPolicy,
    max_resources: int | None = None,
) -> HookScriptDiscoveryResult:
    """Recursively discover scripts without traversing symbolic-link directories."""
    root_path = _target_path(target)
    if root_path is None:
        return _rejected(_TARGET_INVALID)
    try:
        status = root_path.lstat()
        root = root_path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return _rejected(_TARGET_INVALID)
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        return _rejected(_TARGET_INVALID)
    entries: list[tuple[str, HookScriptEntry]] = []
    try:
        for directory, names, files in os.walk(root_path, followlinks=False):
            base = Path(directory)
            names[:] = sorted(
                name for name in names if not (base / name).is_symlink()
            )
            for name in (files if max_resources is not None else sorted(files)):
                candidate = base / name
                try:
                    candidate_status = candidate.lstat()
                except (OSError, ValueError):
                    return _rejected(_TARGET_INVALID)
                if stat.S_ISLNK(candidate_status.st_mode) or not stat.S_ISREG(candidate_status.st_mode):
                    continue
                if not _has_execute_permission(candidate):
                    continue
                try:
                    canonical = candidate.resolve(strict=True)
                except (OSError, RuntimeError, ValueError):
                    return _rejected(_TARGET_INVALID)
                if not canonical.is_relative_to(root):
                    return _rejected(_PATH_ESCAPE)
                if max_resources is not None and len(entries) == max_resources:
                    return _rejected("registration_capacity_exceeded")
                if not _is_admitted(canonical, policy):
                    return _rejected(_TARGET_NOT_EXECUTABLE)
                relative = candidate.relative_to(root_path).as_posix()
                entries.append((relative, HookScriptEntry(canonical, candidate.name)))
    except (OSError, ValueError):
        return _rejected(_TARGET_INVALID)
    entries.sort(key=lambda item: item[0])
    return _unique_entries([entry for _, entry in entries])


def _unique_entries(entries: list[HookScriptEntry]) -> HookScriptDiscoveryResult:
    """Reject duplicate canonical identities without publishing a partial list."""
    paths = tuple(entry.source_path for entry in entries)
    if len(set(paths)) != len(paths):
        return _rejected("duplicate hook_script identity")
    names = tuple(entry.basename for entry in entries)
    if len(set(names)) != len(names):
        return _rejected("duplicate hook_script name")
    return HookScriptDiscoveryResult(True, tuple(entries))


def _has_execute_permission(path: Path) -> bool:
    """Return whether any POSIX-style execute bit is present on the entry."""
    try:
        return bool(path.stat().st_mode & 0o111)
    except OSError:
        return False


def _is_admitted(path: Path, policy: ExecutablePlatformPolicy) -> bool:
    """Apply the selected static executable format policy without launching it."""
    if policy.platform == "windows":
        return _has_allowed_suffix(path, policy.native_suffixes) and _is_pe32_plus(path)
    return _is_elf(path) or _has_allowed_shebang(path, policy.allowed_interpreters)


def _has_allowed_suffix(path: Path, suffixes: tuple[str, ...]) -> bool:
    """Match an explicitly allowed Windows native suffix case-insensitively."""
    lowered_name = path.name.lower()
    return any(lowered_name.endswith(suffix.lower()) for suffix in suffixes)


def _read_prefix(path: Path, limit: int = _MAX_HEADER_BYTES) -> bytes | None:
    """Read only the bounded prefix needed for static format validation."""
    try:
        with path.open("rb") as stream:
            return stream.read(limit)
    except OSError:
        return None


def _is_elf(path: Path) -> bool:
    """Recognize the explicit ELF magic used by the POSIX native policy."""
    prefix = _read_prefix(path, 4)
    return prefix == b"\x7fELF"


def _has_allowed_shebang(path: Path, allowed: tuple[str, ...]) -> bool:
    """Validate an exact shebang executable against the injected allowlist."""
    prefix = _read_prefix(path, 4096)
    if prefix is None or not prefix.startswith(b"#!"):
        return False
    first_line = prefix.splitlines()[0]
    try:
        declaration = first_line[2:].decode("utf-8").strip()
    except UnicodeDecodeError:
        return False
    if not declaration:
        return False
    interpreter = declaration.split(maxsplit=1)[0]
    return interpreter in allowed


def _is_pe32_plus(path: Path) -> bool:
    """Validate bounded PE32+ headers without claiming loader compatibility."""
    data = _read_prefix(path)
    if data is None or len(data) < 0x40 or data[:2] != b"MZ":
        return False
    pe_offset = int.from_bytes(data[0x3C:0x40], "little")
    coff_offset = pe_offset + 4
    if pe_offset < 0x40 or coff_offset + 20 > len(data):
        return False
    if data[pe_offset:coff_offset] != b"PE\x00\x00":
        return False
    machine = int.from_bytes(data[coff_offset : coff_offset + 2], "little")
    section_count = int.from_bytes(data[coff_offset + 2 : coff_offset + 4], "little")
    optional_size = int.from_bytes(data[coff_offset + 16 : coff_offset + 18], "little")
    characteristics = int.from_bytes(data[coff_offset + 18 : coff_offset + 20], "little")
    optional_offset = coff_offset + 20
    section_offset = optional_offset + optional_size
    section_end = section_offset + section_count * 40
    if machine != 0x8664 or section_count < 1 or optional_size != 0xF0:
        return False
    if section_end > len(data) or section_end > _MAX_HEADER_BYTES:
        return False
    if data[optional_offset : optional_offset + 2] != b"\x0b\x02":
        return False
    if characteristics & 0x0022 != 0x0022:
        return False
    return data[section_offset : section_offset + 8] == b".text\x00\x00\x00"


def _rejected(error: str) -> HookScriptDiscoveryResult:
    """Build one immutable atomic rejection result."""
    return HookScriptDiscoveryResult(False, errors=(error,))
