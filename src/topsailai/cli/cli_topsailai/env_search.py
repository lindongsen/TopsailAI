"""Search configurable environment variables by source precedence."""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from cli_topsailai.paths import get_topsailai_home

_ENV_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*(#\s*)?(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$"
)


@dataclass(frozen=True)
class EnvironmentAssignment:
    """One environment-variable assignment read from a configuration source."""

    name: str
    value: str


@dataclass(frozen=True)
class EnvironmentSearchResult:
    """Unique matching assignments contributed by one configuration source."""

    source: str
    assignments: List[EnvironmentAssignment]


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


def read_environment_assignments(path: str) -> List[EnvironmentAssignment]:
    """Read unique assignments, preferring active lines over commented defaults."""
    assignments: List[EnvironmentAssignment] = []
    assignment_indexes = {}
    commented_names = set()
    with open(path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            match = _ENV_ASSIGNMENT_PATTERN.match(line.rstrip("\r\n"))
            if not match:
                continue
            is_commented = match.group(1) is not None
            name = match.group(2)
            assignment = EnvironmentAssignment(name=name, value=match.group(3))
            if name not in assignment_indexes:
                assignment_indexes[name] = len(assignments)
                assignments.append(assignment)
                if is_commented:
                    commented_names.add(name)
                continue
            if name in commented_names and not is_commented:
                assignments[assignment_indexes[name]] = assignment
                commented_names.remove(name)
    return assignments


def find_environment_variables(
    terms: Sequence[str], sources: Optional[Iterable[str]] = None
) -> List[EnvironmentSearchResult]:
    """Return layered OR matches while suppressing lower-priority duplicate names."""
    normalized_terms = [term.casefold() for term in terms if term]
    if not normalized_terms:
        return []

    results: List[EnvironmentSearchResult] = []
    cached_names = set()
    for path in sources or get_environment_search_sources():
        try:
            assignments = read_environment_assignments(path)
        except FileNotFoundError:
            continue
        matches = []
        for assignment in assignments:
            if assignment.name in cached_names:
                continue
            if not any(term in assignment.name.casefold() for term in normalized_terms):
                continue
            cached_names.add(assignment.name)
            matches.append(assignment)
        if matches:
            results.append(EnvironmentSearchResult(source=path, assignments=matches))
    return results
