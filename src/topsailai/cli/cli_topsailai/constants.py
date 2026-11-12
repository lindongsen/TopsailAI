"""Shared constants for the TopsailAI CLI."""

from __future__ import annotations

import re
from typing import Tuple

# Special session identifiers used for transient sessions.
TEMP_SESSION_ID = "topsailai"
TEMP_SESSION_MARKER = "(temp)"

# Backward-compatible aliases used by the legacy monolith and tests.
_TEMP_SESSION_ID = TEMP_SESSION_ID
_TEMP_SESSION_MARKER = TEMP_SESSION_MARKER

# Default configuration file name.
DEFAULT_TOPSAILAI_YAML = "topsailai.yaml"

# Default timeout/limit values.
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_TIMEOUT = 30
DEFAULT_LIMIT = 100

# Pattern used to extract environment variable references from command strings.
ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")

# Interactive command aliases. The leading "/" is optional in workspace,
# session and project scope, so every alias is accepted with and without it.
SESSION_COMMAND_ALIASES = ("messages",)
REFRESH_COMMAND_ALIASES = ("list", "l")


def _command_spellings(name: str, aliases: Tuple[str, ...]) -> Tuple[str, ...]:
    """Return every accepted spelling of one interactive command.

    Each name and alias contributes both the bare and the "/"-prefixed form,
    because the leading "/" is optional in workspace, session and project
    scope.
    """
    return tuple(
        spelling
        for token in (name,) + aliases
        for spelling in (token, "/" + token)
    )


SESSION_COMMAND_SPELLINGS = _command_spellings("session", SESSION_COMMAND_ALIASES)

# "r" / "/r" are the pre-existing short form of /refresh and stay accepted.
REFRESH_COMMAND_SPELLINGS = _command_spellings(
    "refresh", REFRESH_COMMAND_ALIASES
) + ("r", "/r")

# Every accepted spelling of the "include completed rows" form of /refresh.
REFRESH_ALL_COMMAND_SPELLINGS = tuple(
    spelling + " all" for spelling in REFRESH_COMMAND_SPELLINGS
)

# Runtime command aliases, declared once so recognition, completion and help
# cannot drift apart. The key is the bare alias token and the value is the
# canonical command token it expands to. The leading "/" is optional in runtime
# scope, so each alias is accepted with and without it.
#
# These aliases are expanded by the runtime recognizer instead of being declared
# in topsailai.yaml: /ctx.btw extracts its free-form message only from the "cmd"
# template, so a YAML alias would silently drop the message body, and
# agent.models is not a YAML command at all but the /agent.<instruction>
# shortcut.
RUNTIME_COMMAND_ALIASES = {
    "btw": "ctx.btw",
    "model": "agent.models",
}
