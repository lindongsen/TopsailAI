"""Shared constants for the TopsailAI CLI."""

import re

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
