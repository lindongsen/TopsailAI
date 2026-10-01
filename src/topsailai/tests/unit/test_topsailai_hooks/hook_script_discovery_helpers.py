"""Fixtures for future executable hook_script discovery contracts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable


MISSING_CONTRACT = (
    "R6 hook_script executable discovery contract missing: "
    "discover_hook_script_entries and ExecutablePlatformPolicy"
)


def require_script_discovery_contract() -> tuple[Callable[..., Any], type[Any]]:
    """Return future production APIs or fail attributably inside the test body."""
    try:
        from topsailai.hooks.hook_script_discovery import (
            ExecutablePlatformPolicy,
            discover_hook_script_entries,
        )
    except (ImportError, ModuleNotFoundError) as exc:
        raise AssertionError(MISSING_CONTRACT) from exc
    assert callable(discover_hook_script_entries), MISSING_CONTRACT
    assert isinstance(ExecutablePlatformPolicy, type), MISSING_CONTRACT
    return discover_hook_script_entries, ExecutablePlatformPolicy


def discover(
    target: Path,
    *,
    platform: str = "posix",
    allowed_interpreters: tuple[str, ...] = ("/usr/bin/env", "/bin/sh"),
    native_suffixes: tuple[str, ...] = (".exe",),
    resolve_path: Callable[[Path], Path] | None = None,
) -> Any:
    """Invoke future static discovery with one explicit injected platform policy."""
    discovery, policy_type = require_script_discovery_contract()
    policy = policy_type(
        platform=platform,
        allowed_interpreters=allowed_interpreters,
        native_suffixes=native_suffixes,
    )
    arguments: dict[str, object] = {"target": target, "platform_policy": policy}
    if resolve_path is not None:
        arguments["resolve_path"] = resolve_path
    return discovery(**arguments)


def write_script(
    folder: Path,
    name: str,
    *,
    shebang: str = "#!/bin/sh",
    executable: bool = True,
) -> Path:
    """Write one inert text fixture and set an explicit POSIX mode."""
    path = folder / name
    path.write_text(f"{shebang}\nexit 97\n", encoding="utf-8")
    path.chmod(0o700 if executable else 0o600)
    return path


def write_native(
    folder: Path,
    name: str,
    *,
    executable: bool = True,
    file_format: str = "elf",
) -> Path:
    """Write inert native-format fixture bytes without executing the candidate."""
    if file_format == "elf":
        content = b"\x7fELF-static-admission-fixture"
    elif file_format == "pe":
        pe_offset = 0x80
        optional_header_size = 0xF0
        section_table_offset = pe_offset + 4 + 20 + optional_header_size
        content = bytearray(section_table_offset + 40)
        content[0:2] = b"MZ"
        content[0x3C:0x40] = pe_offset.to_bytes(4, "little")
        content[pe_offset : pe_offset + 4] = b"PE\x00\x00"
        coff_offset = pe_offset + 4
        content[coff_offset : coff_offset + 2] = (0x8664).to_bytes(2, "little")
        content[coff_offset + 2 : coff_offset + 4] = (1).to_bytes(2, "little")
        content[coff_offset + 16 : coff_offset + 18] = optional_header_size.to_bytes(
            2, "little"
        )
        content[coff_offset + 18 : coff_offset + 20] = (0x0022).to_bytes(2, "little")
        optional_offset = coff_offset + 20
        content[optional_offset : optional_offset + 2] = (0x020B).to_bytes(2, "little")
        content[section_table_offset : section_table_offset + 8] = b".text\x00\x00\x00"
    else:
        raise ValueError(f"unsupported native fixture format: {file_format}")
    path = folder / name
    path.write_bytes(content)
    path.chmod(0o700 if executable else 0o600)
    return path


def make_fifo(path: Path) -> Path:
    """Create a special-file fixture without ever opening or executing it."""
    os.mkfifo(path)
    return path


def result_entries(result: Any) -> tuple[Any, ...]:
    """Require an immutable entry collection from the future result."""
    assert hasattr(result, "entries"), "script discovery result must expose entries"
    assert type(result.entries) is tuple, "script discovery entries must be immutable"
    return result.entries
