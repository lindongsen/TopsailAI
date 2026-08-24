"""Parse and resolve inline story-memory references."""

import logging
import re
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)

MEMORY_REF_RE = re.compile(r"@memory\[([^\]]+)\]")


@dataclass(frozen=True)
class TitleIndex:
    """Lookup tables for exact and normalized memory titles."""

    exact: dict[str, tuple[str, ...]]
    normalized: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class MemoryRefResult:
    """Resolved canonical ids and references that could not be resolved."""

    resolved_ids: tuple[str, ...]
    ambiguous_titles: tuple[str, ...]
    unknown_titles: tuple[str, ...]


def parse_memory_refs(text: str) -> list[str]:
    """Extract trimmed memory titles while preserving their source order."""
    if not isinstance(text, str):
        return []
    return [match.strip() for match in MEMORY_REF_RE.findall(text)]


def normalize_title(title: str) -> str:
    """Case-fold a title and collapse all runs of whitespace."""
    return " ".join(title.split()).casefold()


def _freeze_title_map(values: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    """Deduplicate lookup values while retaining their input order."""
    return {key: tuple(dict.fromkeys(ids)) for key, ids in values.items()}


def build_title_index(titles: Iterable[str] | None) -> TitleIndex:
    """Build an in-memory title index without reading the memory workspace."""
    exact: dict[str, list[str]] = {}
    normalized: dict[str, list[str]] = {}
    for canonical_id in titles or ():
        if not isinstance(canonical_id, str):
            continue
        exact.setdefault(canonical_id, []).append(canonical_id)
        normalized.setdefault(normalize_title(canonical_id), []).append(canonical_id)
    return TitleIndex(
        exact=_freeze_title_map(exact),
        normalized=_freeze_title_map(normalized),
    )


def resolve_ref(title: str, index: TitleIndex) -> tuple[str | None, str | None]:
    """Resolve one title, returning its id and an optional failure reason."""
    exact_ids = index.exact.get(title, ())
    if len(exact_ids) == 1:
        return exact_ids[0], None
    if len(exact_ids) > 1:
        logger.warning("ambiguous exact memory title reference: [%s]", title)
        return None, "ambiguous"

    normalized_ids = index.normalized.get(normalize_title(title), ())
    if len(normalized_ids) == 1:
        return normalized_ids[0], None
    if len(normalized_ids) > 1:
        logger.warning("ambiguous normalized memory title reference: [%s]", title)
        return None, "ambiguous"

    logger.warning("unknown memory title reference: [%s]", title)
    return None, "unknown"


def collect_canonical_ids(text: str, index: TitleIndex) -> MemoryRefResult:
    """Resolve and deduplicate all memory references in one response text."""
    resolved_ids: list[str] = []
    ambiguous_titles: list[str] = []
    unknown_titles: list[str] = []
    seen_ids: set[str] = set()
    seen_failures: set[tuple[str, str]] = set()

    for title in parse_memory_refs(text):
        canonical_id, reason = resolve_ref(title, index)
        if canonical_id is not None:
            if canonical_id not in seen_ids:
                resolved_ids.append(canonical_id)
                seen_ids.add(canonical_id)
            continue

        failure = (reason or "unknown", title)
        if failure in seen_failures:
            continue
        seen_failures.add(failure)
        if reason == "ambiguous":
            ambiguous_titles.append(title)
        else:
            unknown_titles.append(title)

    return MemoryRefResult(
        resolved_ids=tuple(resolved_ids),
        ambiguous_titles=tuple(ambiguous_titles),
        unknown_titles=tuple(unknown_titles),
    )
