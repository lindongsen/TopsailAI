"""Shell-free executable hook_script discovery and static validation."""

from __future__ import annotations

import os
import stat
from os import scandir as _scandir
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_TARGET_INVALID = "hook_script target is invalid"
_TARGET_NOT_EXECUTABLE = "configured hook_script file is not executable"
_PATH_ESCAPE = "hook_script path escapes configured root"
_MAX_HEADER_BYTES = 1_048_576


class _ObservationError(Exception):
    """Keep filesystem conversion separate from checkpoint exceptions."""


def _check(checkpoint):
    """Observe the caller's unchanged operation budget when supplied."""
    if checkpoint is not None:
        checkpoint()


def _observe(checkpoint, call, *args, errors=(OSError, RuntimeError, ValueError), **kwargs):
    """Bracket one I/O boundary without catching caller stop exceptions."""
    _check(checkpoint)
    try:
        value = call(*args, **kwargs)
    except errors as error:
        _check(checkpoint)
        raise _ObservationError from error
    _check(checkpoint)
    return value


@contextmanager
def _owned(resource, checkpoint=None):
    """Close once even after a stop, retaining the original primary exception."""
    close = getattr(resource, "close", lambda: None)
    try:
        yield resource
    except BaseException as primary:
        try:
            close()
        except Exception:
            primary.add_note("discovery resource close failed")
        if type(primary) is _ObservationError:
            _check(checkpoint)
        raise
    else:
        try:
            close()
        except OSError as error:
            _check(checkpoint)
            raise _ObservationError from error
        _check(checkpoint)


def _open_owned(checkpoint, opener, *args, errors=(OSError, RuntimeError, ValueError)):
    """Acquire ownership before observing the outcome of opening a resource."""
    _check(checkpoint)
    try:
        resource = opener(*args)
    except errors as error:
        _check(checkpoint)
        raise _ObservationError from error
    return resource


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
    checkpoint: Callable[[], None] | None = None,
) -> HookScriptDiscoveryResult:
    """Discover a file or direct directory children without executing candidates."""
    if type(platform_policy) is not ExecutablePlatformPolicy:
        return _rejected(_TARGET_INVALID)
    target_path = _target_path(target)
    if target_path is None:
        return _rejected(_TARGET_INVALID)
    try:
        target_status = _observe(checkpoint, target_path.lstat, errors=(OSError, ValueError))
    except _ObservationError:
        return _rejected(_TARGET_INVALID)
    if stat.S_ISLNK(target_status.st_mode):
        return _rejected(_TARGET_INVALID)
    if stat.S_ISREG(target_status.st_mode):
        return _discover_file(target_path, platform_policy, checkpoint)
    if stat.S_ISDIR(target_status.st_mode):
        return _discover_directory(
            target_path,
            platform_policy,
            resolve_path or _resolve_strict,
            checkpoint,
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
    checkpoint=None,
) -> HookScriptDiscoveryResult:
    """Validate one directly configured regular file."""
    if not _has_execute_permission(candidate, checkpoint):
        return _rejected(_TARGET_NOT_EXECUTABLE)
    try:
        canonical = _observe(checkpoint, candidate.resolve, strict=True)
    except _ObservationError:
        return _rejected(_TARGET_INVALID)
    if not (_is_admitted(canonical, policy) if checkpoint is None else
            _is_admitted(canonical, policy, checkpoint)):
        return _rejected(_TARGET_NOT_EXECUTABLE)
    return HookScriptDiscoveryResult(True, (HookScriptEntry(canonical, candidate.name),))


def _discover_directory(root_path, policy, resolver, checkpoint=None):
    """Validate direct children with checks between every iterator advance."""
    try:
        root = _observe(checkpoint, root_path.resolve, strict=True)
        children = _open_owned(checkpoint, _scandir, root_path)
        with _owned(children, checkpoint):
            _check(checkpoint)
            entries = []
            while True:
                entry = _observe(checkpoint, next, children, None)
                if entry is None:
                    break
                child = Path(entry.path)
                try:
                    child_status = _observe(checkpoint, child.lstat, errors=(OSError, ValueError))
                except _ObservationError:
                    continue
                if stat.S_ISLNK(child_status.st_mode) or not stat.S_ISREG(child_status.st_mode):
                    continue
                try:
                    canonical = _observe(checkpoint, lambda: Path(resolver(child)), errors=(OSError, RuntimeError, TypeError, ValueError))
                    if not canonical.is_absolute():
                        canonical = _observe(checkpoint, canonical.resolve, strict=True)
                except _ObservationError:
                    continue
                if not canonical.is_relative_to(root):
                    return _rejected(_PATH_ESCAPE)
                if not _has_execute_permission(child, checkpoint) or not (
                        _is_admitted(canonical, policy) if checkpoint is None else
                        _is_admitted(canonical, policy, checkpoint)):
                    continue
                entries.append(HookScriptEntry(canonical, child.name))
    except _ObservationError:
        return _rejected(_TARGET_INVALID)
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


def _has_execute_permission(path: Path, checkpoint=None) -> bool:
    """Return whether any POSIX-style execute bit is present on the entry."""
    try:
        return bool(_observe(checkpoint, path.stat, errors=(OSError,)).st_mode & 0o111)
    except _ObservationError:
        return False


def _is_admitted(path: Path, policy: ExecutablePlatformPolicy, checkpoint=None) -> bool:
    """Apply the selected static executable format policy without launching it."""
    if policy.platform == "windows":
        return _has_allowed_suffix(path, policy.native_suffixes) and _is_pe32_plus(path, checkpoint)
    return _is_elf(path, checkpoint) or _has_allowed_shebang(path, policy.allowed_interpreters, checkpoint)


def _has_allowed_suffix(path: Path, suffixes: tuple[str, ...]) -> bool:
    """Match an explicitly allowed Windows native suffix case-insensitively."""
    lowered_name = path.name.lower()
    return any(lowered_name.endswith(suffix.lower()) for suffix in suffixes)


def _read_prefix(path: Path, limit: int = _MAX_HEADER_BYTES, checkpoint=None) -> bytes | None:
    """Read a bounded prefix, arming closure before the post-open checkpoint."""
    try:
        stream = _open_owned(checkpoint, path.open, "rb", errors=(OSError,))
        with _owned(stream, checkpoint):
            _check(checkpoint)
            return _observe(checkpoint, stream.read, limit, errors=(OSError,))
    except _ObservationError:
        return None


def _is_elf(path: Path, checkpoint=None) -> bool:
    """Recognize the explicit ELF magic used by the POSIX native policy."""
    prefix = _read_prefix(path, 4, checkpoint)
    return prefix == b"\x7fELF"


def _has_allowed_shebang(path: Path, allowed: tuple[str, ...], checkpoint=None) -> bool:
    """Validate an exact shebang executable against the injected allowlist."""
    prefix = _read_prefix(path, 4096, checkpoint)
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


def _is_pe32_plus(path: Path, checkpoint=None) -> bool:
    """Validate bounded PE32+ headers without claiming loader compatibility."""
    data = _read_prefix(path, checkpoint=checkpoint)
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
