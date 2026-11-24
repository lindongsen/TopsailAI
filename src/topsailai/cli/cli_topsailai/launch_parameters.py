"""Validate caller-supplied launch parameters before any process is spawned.

A caller-fixed session identity and a caller-supplied launch environment are
both public CLI inputs, so they are validated once here instead of in each
command that forwards them. Validation happens before a launch is prepared, so
a rejected request never leaves a partial launch behind.

Author: DawsonLin
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Optional

#: Identity environment aliases. The launch boundary writes both from one
#: value, so a caller must not set either through the environment option.
IDENTITY_ENV_KEYS = ("TOPSAILAI_SESSION_ID", "SESSION_ID")

#: A caller-fixed identity is stricter than the launcher's own rule: dots are
#: rejected because every stdout filename reader splits the name on dots, so a
#: dot-containing identity would be misparsed by the whole workspace layer.
SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")

#: Environment names are POSIX-style identifiers. A name outside this shape is
#: not addressable by a shell and is far more likely a typo than a request.
ENV_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class LaunchParameterError(ValueError):
    """Raised when a caller-supplied launch parameter is unusable."""


def validate_session_id(value: object) -> str:
    """Return *value* as a usable caller-fixed session identity.

    Raises:
        LaunchParameterError: when the value is not a string, is empty, is
            longer than 128 characters, contains a character outside
            ``[A-Za-z0-9_-]``, or contains a dot.
    """
    if not isinstance(value, str):
        raise LaunchParameterError("--session-id must be a string")
    if not value:
        raise LaunchParameterError("--session-id must not be empty")
    if "." in value:
        raise LaunchParameterError(
            "--session-id must not contain a dot, because session filenames "
            "are parsed by splitting on dots"
        )
    if not SESSION_ID_PATTERN.fullmatch(value):
        raise LaunchParameterError(
            "--session-id must match [A-Za-z0-9_-]{1,128}"
        )
    return value


def parse_env_overrides(entries: Optional[Iterable[str]]) -> dict[str, str]:
    """Return the caller's ``KEY=VALUE`` pairs as one mapping.

    An empty value is preserved, because a caller may deliberately export an
    empty string and the launch boundary must not turn that into "unset".

    Raises:
        LaunchParameterError: when an entry has no ``=``, has an empty or
            malformed name, repeats a name with a different value, or names one
            of the identity aliases that the launch boundary owns.
    """
    overrides: dict[str, str] = {}
    for entry in entries or ():
        if not isinstance(entry, str):
            raise LaunchParameterError("--env must be KEY=VALUE text")
        name, separator, value = entry.partition("=")
        if not separator:
            raise LaunchParameterError(
                f"--env must be KEY=VALUE, got {entry!r}"
            )
        if not ENV_NAME_PATTERN.fullmatch(name):
            raise LaunchParameterError(
                f"--env name must match [A-Za-z_][A-Za-z0-9_]*, got {name!r}"
            )
        if name in IDENTITY_ENV_KEYS:
            raise LaunchParameterError(
                f"--env must not set {name}; use --session-id instead"
            )
        if name in overrides and overrides[name] != value:
            raise LaunchParameterError(
                f"--env repeats {name} with conflicting values"
            )
        overrides[name] = value
    return overrides


def describe_overrides(overrides: Mapping[str, str]) -> str:
    """Return a stable, value-free description of the overridden names.

    Only names are published, so a caller can confirm which variables it set
    without the launch output disclosing their values.
    """
    return ", ".join(sorted(overrides))
