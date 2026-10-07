"""Recoverable metadata publication for artifact lease roots."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from topsailai.hooks.artifact_lease_contracts import LeaseMutationResult

if TYPE_CHECKING:
    from topsailai.hooks.artifact_leases import ArtifactLeaseGroup, ArtifactLeaseManager

_PUBLICATION_ISSUER = object()


@dataclass(frozen=True, slots=True)
class PublicationImage:
    """Hold one coherent runtime image and its immutable active lease roots."""

    generation: int
    runtime_values: object
    lease_roots: tuple[ArtifactLeaseGroup, ...]


class PublicationCell:
    """Own one coherent publication image under the runtime transaction lock."""

    __slots__ = ("_issuer", "_lock", "current")

    def __init__(self, current: PublicationImage) -> None:
        """Create one runtime-issued publication cell."""
        if type(current) is not PublicationImage:
            raise TypeError("invalid publication image")
        self._issuer = _PUBLICATION_ISSUER
        self._lock = threading.RLock()
        self.current = current


class PublicationStage:
    """Retain one bounded publication decision until reconciliation."""

    __slots__ = (
        "_issuer", "_manager", "_cell", "_candidate", "_expected", "_replacement",
        "_old_groups", "_changed", "_state",
    )

    def __init__(self) -> None:
        """Reject caller construction of publication authority."""
        raise TypeError("PublicationStage has no public constructor")


@dataclass(frozen=True, slots=True)
class PublicationStageResult:
    """Return one manager-owned stage or a stable rejection."""

    accepted: bool
    stage: PublicationStage | None = None
    errors: tuple[str, ...] = ()


class ArtifactPublicationMixin:
    """Provide a single-image stage, decision, abort, and reconciliation protocol."""

    def _stage_publication(
        self: ArtifactLeaseManager,
        cell: PublicationCell,
        candidate: ArtifactLeaseGroup,
        *,
        expected: PublicationImage,
        replacement: PublicationImage,
        old_groups: tuple[ArtifactLeaseGroup, ...],
        changed: bool,
    ) -> PublicationStageResult:
        """Charge one candidate stage without granting execution authority."""
        if (
            type(cell) is not PublicationCell
            or type(expected) is not PublicationImage
            or type(replacement) is not PublicationImage
            or type(expected.lease_roots) is not tuple
            or type(replacement.lease_roots) is not tuple
            or type(old_groups) is not tuple
            or type(changed) is not bool
        ):
            return PublicationStageResult(False, errors=("invalid_publication_stage",))
        with cell._lock:
            with self._lock:
                if cell._issuer is not _PUBLICATION_ISSUER:
                    return PublicationStageResult(False, errors=("invalid_publication_stage",))
                if getattr(self, "_publication_cell", None) not in (None, cell):
                    return PublicationStageResult(False, errors=("invalid_publication_stage",))
                existing = self._publication_stage
                if existing is not None:
                    if self._matches_pending_stage(
                        existing, cell, candidate, expected, replacement,
                        old_groups, changed,
                    ):
                        return PublicationStageResult(True, existing)
                    return PublicationStageResult(False, errors=("artifact_lease_busy",))
                if cell.current is not expected:
                    return PublicationStageResult(False, errors=("artifact_lease_busy",))
                error = self._validate_candidate(candidate)
                if error is not None:
                    return PublicationStageResult(False, errors=(error,))
                if (
                    type(expected.generation) is not int
                    or type(replacement.generation) is not int
                ):
                    return PublicationStageResult(False, errors=("invalid_publication_stage",))
                if any(
                    not self._owned_group(group)
                    for roots in (expected.lease_roots, replacement.lease_roots, old_groups)
                    for group in roots
                ):
                    return PublicationStageResult(False, errors=("invalid_publication_stage",))
                if len({id(group) for group in old_groups}) != len(old_groups) or any(
                    not any(group is root for root in expected.lease_roots)
                    for group in old_groups
                ):
                    return PublicationStageResult(False, errors=("invalid_publication_stage",))
                for group in expected.lease_roots:
                    if group._mutation is not None:
                        return PublicationStageResult(False, errors=("artifact_lease_busy",))
                    is_old = any(group is old_group for old_group in old_groups)
                    recovered_retirement = (
                        changed
                        and is_old
                        and self._owned_group(group)
                        and not self._valid_group(group)
                        and group._state == "retired"
                        and group._terminal
                        and not group._tokens
                    )
                    if not recovered_retirement and (
                        not self._valid_group(group) or group._state != "active"
                    ):
                        return PublicationStageResult(
                            False, errors=("invalid_publication_stage",)
                        )
                expected_roots = tuple(
                    group for group in expected.lease_roots
                    if not any(group is old_group for old_group in old_groups)
                )
                required_roots = expected_roots + ((candidate,) if changed else old_groups)
                if replacement.lease_roots != required_roots:
                    return PublicationStageResult(False, errors=("invalid_publication_stage",))
                target_generation = expected.generation + 1 if changed else expected.generation
                if replacement is expected or replacement.generation != target_generation:
                    return PublicationStageResult(False, errors=("invalid_publication_stage",))
                stage = object.__new__(PublicationStage)
                stage._issuer = _PUBLICATION_ISSUER
                stage._manager = self
                stage._cell = cell
                stage._candidate = candidate
                stage._expected = expected
                stage._replacement = replacement
                stage._old_groups = old_groups
                stage._changed = changed
                stage._state = "staged"
                try:
                    self._publication_cell = cell
                    self._publication_stage = stage
                    candidate._state = "staged"
                    return PublicationStageResult(True, stage)
                except BaseException:
                    self._abort_stage_locked(stage)
                    raise

    def _commit_publication(
        self: ArtifactLeaseManager, stage: PublicationStage
    ) -> LeaseMutationResult:
        """Decide publication with one cell image replacement and reconcile it."""
        if not self._valid_publication_stage(stage):
            return LeaseMutationResult(False, errors=("invalid_publication_stage",))
        with stage._cell._lock:
            with self._lock:
                if stage._state == "committed":
                    self._clear_publication_stage(stage)
                    return LeaseMutationResult(True, already_settled=True)
                if stage._state == "aborted":
                    return LeaseMutationResult(False, errors=("invalid_publication_stage",))
                candidate = stage._candidate
                if (
                    stage._cell.current is not stage._expected
                    or not self._valid_group(candidate)
                    or candidate._state != "staged"
                    or candidate._terminal
                ):
                    return LeaseMutationResult(False, errors=("invalid_publication_stage",))
                if self._state != "open" or self._clock() >= candidate._expiry:
                    self._abort_stage_locked(stage)
                    return LeaseMutationResult(False, errors=("artifact_candidate_expired",))
                stage._cell.current = stage._replacement
                stage._state = "decided"
                return self._reconcile_stage_locked(stage)

    def _abort_publication(
        self: ArtifactLeaseManager, stage: PublicationStage
    ) -> LeaseMutationResult:
        """Abort only a publication whose cell decision has not happened."""
        if not self._valid_publication_stage(stage):
            return LeaseMutationResult(False, errors=("invalid_publication_stage",))
        with stage._cell._lock:
            with self._lock:
                if stage._state == "aborted":
                    self._clear_publication_stage(stage)
                    return LeaseMutationResult(True, already_settled=True)
                if stage._cell.current is stage._replacement or stage._state in ("decided", "committed"):
                    return LeaseMutationResult(False, errors=("publication_already_committed",))
                self._abort_stage_locked(stage)
                return LeaseMutationResult(True)

    def _reconcile_publication(
        self: ArtifactLeaseManager, stage: PublicationStage
    ) -> LeaseMutationResult:
        """Finish the exact side of the publication decision visible in the cell."""
        if not self._valid_publication_stage(stage):
            return LeaseMutationResult(False, errors=("invalid_publication_stage",))
        with stage._cell._lock:
            with self._lock:
                if stage._state == "committed":
                    self._clear_publication_stage(stage)
                    return LeaseMutationResult(True, already_settled=True)
                if stage._state == "aborted":
                    self._clear_publication_stage(stage)
                    return LeaseMutationResult(True, already_settled=True)
                if stage._cell.current is stage._replacement:
                    stage._state = "decided"
                    return self._reconcile_stage_locked(stage)
                if stage._cell.current is stage._expected:
                    self._abort_stage_locked(stage)
                    return LeaseMutationResult(True)
                return LeaseMutationResult(False, errors=("invalid_publication_stage",))

    def _valid_publication_stage(
        self: ArtifactLeaseManager, stage: object
    ) -> bool:
        """Accept exact issued stages while charging only unfinished decisions."""
        if (
            not isinstance(stage, PublicationStage)
            or getattr(stage, "_issuer", None) is not _PUBLICATION_ISSUER
            or stage._manager is not self
            or stage._cell is not self._publication_cell
        ):
            return False
        if stage._state in ("committed", "aborted"):
            return True
        return self._publication_stage is stage

    def _matches_pending_stage(
        self: ArtifactLeaseManager,
        stage: PublicationStage,
        cell: PublicationCell,
        candidate: ArtifactLeaseGroup,
        expected: PublicationImage,
        replacement: PublicationImage,
        old_groups: tuple[ArtifactLeaseGroup, ...],
        changed: bool,
    ) -> bool:
        """Match a lost stage result only by its complete exact request identity."""
        return (
            stage._state == "staged"
            and stage._cell is cell
            and stage._candidate is candidate
            and stage._expected is expected
            and stage._replacement is replacement
            and len(stage._old_groups) == len(old_groups)
            and all(left is right for left, right in zip(stage._old_groups, old_groups))
            and stage._changed is changed
        )


    def _snapshot_publication_group_counts(
        self: ArtifactLeaseManager,
    ) -> tuple[int, int]:
        """Classify candidates and active roots from an unfinished decision."""
        candidate_count = len(self._candidate_groups)
        active_count = sum(group._state == "active" for group in self._groups.values())
        stage = self._publication_stage
        if stage is None or stage._cell.current is not stage._replacement:
            return candidate_count, active_count
        candidate = stage._candidate
        if self._candidate_groups.get(candidate._group_id) is candidate:
            candidate_count -= 1
        if not stage._changed:
            return candidate_count, active_count
        if candidate._state != "active":
            active_count += 1
        active_count -= sum(group._state == "active" for group in stage._old_groups)
        return candidate_count, active_count

    def _clear_publication_stage(
        self: ArtifactLeaseManager, stage: PublicationStage
    ) -> None:
        """Clear only the exact charged stage after its terminal state is durable."""
        if self._publication_stage is stage:
            self._publication_stage = None

    def _abort_stage_locked(self: ArtifactLeaseManager, stage: PublicationStage) -> None:
        """Restore one undecided candidate without extending its lifetime."""
        if stage._candidate._state == "staged":
            stage._candidate._state = "candidate"
        stage._state = "aborted"
        self._clear_publication_stage(stage)

    def _reconcile_stage_locked(
        self: ArtifactLeaseManager, stage: PublicationStage
    ) -> LeaseMutationResult:
        """Finalize roots after the cell replacement has made the decision."""
        candidate = stage._candidate
        if stage._changed:
            candidate._state = "active"
            if self._candidate_groups.get(candidate._group_id) is candidate:
                self._candidate_groups.pop(candidate._group_id, None)
            for group in stage._old_groups:
                self._settle_group_tokens(group, state="retired")
        else:
            self._settle_group_tokens(candidate, state="settled")
        stage._state = "committed"
        self._clear_publication_stage(stage)
        return LeaseMutationResult(True)
