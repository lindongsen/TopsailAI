"""Armed recovery custody for unpublished Hook Point capture. Author: DawsonLin."""
from __future__ import annotations

from topsailai.hooks.artifact_contracts import ArtifactDisposeResult


class HookPointCandidate:
    """Retain physical ownership independently of immutable semantic success."""
    def __init__(self, backend):
        """Arm bounded recovery before the first capture or child launch."""
        self._backend = backend
        self._capture_owner = None
        self._plan = None
        self._probe_debts = set()
        self._closed = False

    @property
    def plan(self):
        """Expose only a completed live unpublished plan."""
        if self._plan is None or self._closed:
            raise RuntimeError("candidate is not live and complete")
        return self._plan

    def cleanup_debts(self):
        """Inspect only exact debts introduced by this candidate's probe calls."""
        process = () if self._backend is None else tuple(d for d in self._backend.cleanup_debts() if d.debt_id in self._probe_debts)
        artifacts = () if self._capture_owner is None else self._capture_owner.cleanup_debts()
        return process + artifacts

    def retry_cleanup(self, debt_id):
        """Settle exact process debt before permitting captured-byte disposal."""
        if debt_id in self._probe_debts:
            if not self._backend.retry_cleanup(debt_id):
                return False
            self._probe_debts.discard(debt_id)
            result = self.close()
            return result.accepted and not result.cleanup_pending
        if self._probe_debts or self._capture_owner is None:
            return False
        if not any(d.debt_id == debt_id for d in self._capture_owner.cleanup_debts()):
            return False
        if not self._capture_owner.retry_cleanup(debt_id):
            return False
        result = self.close()
        return result.accepted and not result.cleanup_pending

    def close(self):
        """Invalidate semantics but retain every owner until cleanup confirms absence."""
        already = self._closed
        self._closed = True
        if self._probe_debts:
            return ArtifactDisposeResult(False, already, True, ("probe_cleanup_pending",))
        if self._capture_owner is not None:
            result = self._capture_owner.close()
            if not result.accepted or result.cleanup_pending:
                return result
        return ArtifactDisposeResult(True, already)

    def __enter__(self):
        """Return an already-armed candidate for caller-controlled lifetime."""
        return self

    def __exit__(self, exc_type, exc, traceback):
        """Preserve body interruption and attach custody for unresolved cleanup."""
        try:
            result = self.close()
            if result.cleanup_pending:
                if exc is None:
                    raise CandidateBuildError("candidate_cleanup_pending", self)
                exc.recovery_owner = self
        except BaseException as error:
            if exc is None or (isinstance(exc, Exception) and not isinstance(error, Exception)):
                error.recovery_owner = self
                if exc is not None:
                    _preserve_body_diagnosis(exc, error)
                raise
            exc.recovery_owner = self
        if exc is not None and self.cleanup_debts():
            exc.recovery_owner = self
        return False


def _preserve_body_diagnosis(body, cleanup):
    """Keep body evidence while removing back edges to the propagated interrupt."""
    pending, seen = [body], set()
    while pending:
        error = pending.pop()
        if id(error) in seen:
            continue
        seen.add(id(error))
        for attribute in ("__cause__", "__context__"):
            edge = getattr(error, attribute)
            if edge is cleanup:
                setattr(error, attribute, None)
            elif edge is not None:
                pending.append(edge)
    cleanup.__context__ = body


class CandidateBuildError(ValueError):
    """Return stable failure classification plus exact retryable resource custody."""
    def __init__(self, category, recovery_owner):
        """Keep recovery reachable without describing a partial semantic candidate."""
        super().__init__(category)
        self.category = category
        self.recovery_owner = recovery_owner
