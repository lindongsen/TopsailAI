"""Read the build identity from the packaging-generated ``version`` file.

Author: DawsonLin

The packaging tool writes a small JSON record beside this package at build time,
so an installed CLI can report the exact build it belongs to. The record is the
single source of truth: nothing in this module hardcodes a version, because a
second copy of that fact is what this module exists to remove.

The file is a build artifact and is absent in a source checkout. A missing file
is therefore normal, not an error, and the reader falls back to ``dev``.

A version request must never fail. Every failure mode -- absent file, unreadable
file, oversized file, invalid JSON, wrong field type -- logs one warning to
stderr and falls back to ``dev``. The warning goes to stderr so stdout stays a
single parseable line.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional

#: Name of the generated record, relative to the package root.
VERSION_FILE_NAME = "version"

#: Fallback reported when no usable record exists.
UNKNOWN_VERSION = "dev"

#: Upper bound on the record size. The real record is a few hundred bytes, so a
#: larger file is not a record and must not be parsed into memory.
MAX_VERSION_FILE_BYTES = 4096

#: Schema version this reader understands.
SUPPORTED_SCHEMA_VERSION = 1


def get_version_file_path() -> str:
    """Return the absolute path of the generated ``version`` record.

    This module lives at ``<package-root>/cli_topsailai/version.py``, so the
    package root is three levels up. The packager maps the source package
    directory onto the same installed path, so one walk resolves both layouts.
    """
    package_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(package_root, VERSION_FILE_NAME)


def _warn(message: str) -> None:
    """Report a non-fatal version-record problem on stderr."""
    print(f"[WARN] {message}", file=sys.stderr)


def read_version_info(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the parsed version record, or ``None`` when it is unusable.

    ``None`` means "no usable record", which the caller renders as
    :data:`UNKNOWN_VERSION`. A record whose ``version`` field is not a non-empty
    string is treated as unusable, because a record that cannot name a build is
    not a version.
    """
    record_path = path or get_version_file_path()

    try:
        size = os.path.getsize(record_path)
    except OSError:
        # Absent file is the normal source-checkout case; stay silent.
        return None

    if size > MAX_VERSION_FILE_BYTES:
        _warn(
            f"version record {record_path} is {size} bytes, above the "
            f"{MAX_VERSION_FILE_BYTES}-byte limit; reporting {UNKNOWN_VERSION}"
        )
        return None

    try:
        with open(record_path, "r", encoding="utf-8") as handle:
            content = handle.read(MAX_VERSION_FILE_BYTES + 1)
    except OSError as error:
        _warn(f"cannot read version record {record_path}: {error}; reporting {UNKNOWN_VERSION}")
        return None

    try:
        record = json.loads(content)
    except (ValueError, UnicodeDecodeError) as error:
        _warn(f"version record {record_path} is not valid JSON: {error}; reporting {UNKNOWN_VERSION}")
        return None

    if not isinstance(record, dict):
        _warn(f"version record {record_path} is not a JSON object; reporting {UNKNOWN_VERSION}")
        return None

    version = record.get("version")
    if not isinstance(version, str) or not version.strip():
        _warn(
            f"version record {record_path} has no usable 'version' string; "
            f"reporting {UNKNOWN_VERSION}"
        )
        return None

    schema_version = record.get("schema_version")
    if schema_version is not None and schema_version != SUPPORTED_SCHEMA_VERSION:
        _warn(
            f"version record {record_path} declares schema_version "
            f"{schema_version!r}, expected {SUPPORTED_SCHEMA_VERSION}; "
            "reading the known fields anyway"
        )

    return record


def get_version_string(path: Optional[str] = None) -> str:
    """Return the build version, or :data:`UNKNOWN_VERSION` when unavailable."""
    record = read_version_info(path)
    if record is None:
        return UNKNOWN_VERSION
    return record["version"].strip()
