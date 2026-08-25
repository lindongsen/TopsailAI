"""Parse and resolve inline story-memory references."""

import logging
import re
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)

MEMORY_REF_RE = re.compile(r"@memory\[([^\]]+)\]")
COMPACT_TIME_PREFIX_RE = re.compile(r"^\d{14}\.(.+)$")
MARKDOWN_EXTENSION = ".md"


@dataclass(frozen=True)
class TitleIndex:
    """Lookup tables for exact, normalized, and alias memory titles."""

    exact: dict[str, tuple[str, ...]]
    normalized: dict[str, tuple[str, ...]]
    aliases: dict[str, tuple[str, ...]]


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


def _expand_title_variants(title: str) -> list[str]:
    """Return deterministic extension and compact-prefix title variants."""
    variants = [title]
    if title.casefold().endswith(MARKDOWN_EXTENSION):
        variants.append(title[:-len(MARKDOWN_EXTENSION)])

    for variant in tuple(variants):
        match = COMPACT_TIME_PREFIX_RE.fullmatch(variant)
        if match:
            variants.append(match.group(1))

    return list(dict.fromkeys(variants))


def _unique_candidates(candidate_groups: Iterable[Iterable[str]]) -> tuple[str, ...]:
    """Merge candidate groups without changing their canonical input order."""
    return tuple(
        dict.fromkeys(
            candidate
            for candidates in candidate_groups
            for candidate in candidates
        )
    )


def _freeze_title_map(values: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    """Deduplicate lookup values while retaining their input order."""
    return {key: tuple(dict.fromkeys(ids)) for key, ids in values.items()}


def build_title_index(titles: Iterable[str] | None) -> TitleIndex:
    """Build an in-memory title index without reading the memory workspace."""
    exact: dict[str, list[str]] = {}
    normalized: dict[str, list[str]] = {}
    aliases: dict[str, list[str]] = {}
    for canonical_id in titles or ():
        if not isinstance(canonical_id, str):
            continue
        exact.setdefault(canonical_id, []).append(canonical_id)
        normalized.setdefault(normalize_title(canonical_id), []).append(canonical_id)
        for variant in _expand_title_variants(canonical_id)[1:]:
            aliases.setdefault(normalize_title(variant), []).append(canonical_id)
    return TitleIndex(
        exact=_freeze_title_map(exact),
        normalized=_freeze_title_map(normalized),
        aliases=_freeze_title_map(aliases),
    )


def resolve_ref(
    title: str,
    index: TitleIndex,
    *,
    bare_title_enabled: bool = True,
) -> tuple[str | None, str | None]:
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

    if bare_title_enabled:
        candidates = _unique_candidates(
            index.aliases.get(normalize_title(variant), ())
            for variant in _expand_title_variants(title)
        )
        if len(candidates) == 1:
            return candidates[0], None
        if len(candidates) > 1:
            logger.warning("ambiguous bare memory title reference: [%s]", title)
            return None, "ambiguous"

    logger.warning("unknown memory title reference: [%s]", title)
    return None, "unknown"


def collect_canonical_ids(
    text: str,
    index: TitleIndex,
    *,
    bare_title_enabled: bool = True,
) -> MemoryRefResult:
    """Resolve and deduplicate all memory references in one response text."""
    resolved_ids: list[str] = []
    ambiguous_titles: list[str] = []
    unknown_titles: list[str] = []
    seen_ids: set[str] = set()
    seen_failures: set[tuple[str, str]] = set()

    for title in parse_memory_refs(text):
        canonical_id, reason = resolve_ref(
            title,
            index,
            bare_title_enabled=bare_title_enabled,
        )
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
