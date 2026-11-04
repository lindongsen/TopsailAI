"""Environment audit helpers exposed as /env_audit.* slash instructions."""

# List form: the action name is the function name, so this module registers
# /env_audit.dump and /env_audit.check.
#
# Scenario: the agent behaves differently than expected and you suspect a stray
# TOPSAILAI_* variable. Printing the whole environment into the LLM context would
# leak credentials, so these actions read the real process environment, mask
# values whose names match the project's own sensitive-key list, and print the
# result for you instead.

import os

from topsailai.utils.print_tool import PRINT_STEP_SENSITIVE_ARG_KEYS

PREFIX = "TOPSAILAI_"
MASK = "***"


def _is_sensitive(name: str) -> bool:
    """Report whether a variable name looks like it carries a credential.

    Args:
        name: The environment variable name.

    Returns:
        True when the lowered name contains any sensitive keyword.
    """
    lowered = name.lower()
    return any(word in lowered for word in PRINT_STEP_SENSITIVE_ARG_KEYS)


def _topsailai_vars() -> list[tuple[str, str]]:
    """Collect the TOPSAILAI_* variables of this process.

    Returns:
        Sorted name/value pairs, with sensitive values already masked.
    """
    pairs = []
    for name in sorted(os.environ):
        if not name.startswith(PREFIX):
            continue
        value = os.environ[name]
        pairs.append((name, MASK if _is_sensitive(name) else value))
    return pairs


def dump(prefix: str = "") -> str:
    """Print the TOPSAILAI_* variables of this process with secrets masked.

    Args:
        prefix: Optional extra name filter applied after the TOPSAILAI_ prefix.

    Returns:
        One name=value line per variable, or a message when nothing matches.
    """
    pairs = _topsailai_vars()
    if prefix:
        pairs = [(name, value) for name, value in pairs if prefix in name]
    if not pairs:
        return f"no {PREFIX}* variable matches prefix={prefix!r}"

    lines = [f"{PREFIX}* variables: {len(pairs)}"]
    lines.extend(f"  {name}={value}" for name, value in pairs)
    return "\n".join(lines)


def check(name: str = "") -> str:
    """Report whether one variable is set, without revealing its value.

    Args:
        name: The exact variable name to inspect.

    Returns:
        The set/unset state, the value length, and whether it is masked.
    """
    if not name:
        return "Usage: /env_audit.check <NAME>"

    if name not in os.environ:
        return f"{name}: unset"

    value = os.environ[name]
    sensitive = _is_sensitive(name)
    shown = MASK if sensitive else (value if value else "<empty>")
    return f"{name}: set len={len(value)} sensitive={sensitive} value={shown}"


INSTRUCTIONS = [dump, check]
