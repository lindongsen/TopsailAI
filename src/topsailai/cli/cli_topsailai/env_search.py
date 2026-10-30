"""Search configurable environment-variable names by source precedence."""

from __future__ import annotations

import os
import re
import shlex
from typing import Iterable, List, Optional, Sequence, Tuple

from cli_topsailai.paths import get_topsailai_home

_ENV_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*(?:#\s*)?(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*="
)


def get_environment_search_sources() -> List[str]:
    """Return environment configuration sources in lookup order."""
    project_folder = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    home = get_topsailai_home()
    return [
        os.path.join(home, ".env.local"),
        os.path.join(home, ".env"),
        os.path.join(project_folder, "env_template"),
    ]


def parse_search_terms(raw_args: str) -> List[str]:
    """Parse one or more shell-style search terms from command arguments."""
    try:
        terms = shlex.split(raw_args)
    except ValueError as error:
        raise ValueError(f"Invalid search arguments: {error}") from error
    return [term.casefold() for term in terms if term]


def read_environment_names(path: str) -> List[str]:
    """Read assignment names from one environment file without reading values."""
    names: List[str] = []
    seen = set()
    with open(path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            match = _ENV_ASSIGNMENT_PATTERN.match(line)
            if not match:
                continue
            name = match.group(1)
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def find_environment_variables(
    terms: Sequence[str], sources: Optional[Iterable[str]] = None
) -> Optional[Tuple[str, List[str]]]:
    """Return matches from the first source with any case-insensitive OR match."""
    normalized_terms = [term.casefold() for term in terms if term]
    if not normalized_terms:
        return None

    for path in sources or get_environment_search_sources():
        try:
            names = read_environment_names(path)
        except FileNotFoundError:
            continue
        matches = [
            name
            for name in names
            if any(term in name.casefold() for term in normalized_terms)
        ]
        if matches:
            return path, matches
    return None
