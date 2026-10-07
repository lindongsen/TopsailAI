"""Capture receipt reservation and interruption reconciliation helpers."""

from __future__ import annotations

import secrets
import threading

from topsailai.hooks.artifact_contracts import ArtifactCapturePolicy
from topsailai.hooks.artifact_lease_contracts import (
    CaptureReceiptResult,
    LeaseAcquireResult,
)
from topsailai.hooks.artifact_retention import valid_deadline


class ArtifactLeaseReceiptMixin:
    """Provide slot-bound capture receipt transitions for a lease manager."""

    def _acquire_physical(self, owner: object) -> bool:
        """Acquire physical serialization for one exact caller token."""
        return self._physical.acquire(blocking=False, owner=owner)

    def _release_physical(self, owner: object) -> bool:
        """Release physical serialization only for its exact caller token."""
        return self._physical.release_if_owned(owner)

    def _reserve_capture(
        self, group, requests, policy, deadline,
        recovery: list | None = None,
    ) -> CaptureReceiptResult:
        """Reserve receipt, token, version, and candidate capacity before I/O."""
        if type(requests) is not tuple or type(policy) is not ArtifactCapturePolicy:
            return CaptureReceiptResult(False, errors=("invalid_lease_argument",))
        if deadline is not None and not valid_deadline(deadline):
            return CaptureReceiptResult(False, errors=("invalid_lease_argument",))
        with self._lock:
            error = self._validate_candidate(group)
            if error is not None:
                return CaptureReceiptResult(False, errors=(error,))
            if self._receipt is not None or group._pending_capture:
                return CaptureReceiptResult(False, errors=("artifact_lease_busy",))
            if self._charged_token_count() >= self._max_tokens or len(self._versions) >= self._max_versions:
                return CaptureReceiptResult(False, errors=("artifact_lease_capacity_exceeded",))
            receipt = self._new_capture_receipt()
            receipt._issuer = self._execution_identity
            receipt._manager = self
            receipt._receipt_id = secrets.token_hex(16)
            receipt._group = group
            receipt._state = "reserved"
            receipt._slot = None
            receipt._artifact = None
            receipt._reserved_entries = len(requests)
            receipt._reserved_bytes = 0 if not requests else policy.max_total_bytes
            receipt._reserved_token = True
            receipt._reserved_version = True
            receipt._deadline = group._expiry if deadline is None else min(group._expiry, deadline)
            if recovery is not None:
                recovery.append(receipt)
            group._pending_capture = receipt
            self._receipt = receipt
            return CaptureReceiptResult(True, receipt)

    def _bind_capture_slot(self, slot: object) -> None:
        """Bind the exact U07 slot to the sole unfinished receipt."""
        with self._lock:
            if self._receipt is not None and self._receipt._state == "reserved":
                self._receipt._slot = slot
                self._receipt._state = "bound"

    def _finish_capture(
        self, receipt, cancellation: threading.Event | None
    ) -> LeaseAcquireResult:
        """Adopt issued bytes only after candidate and liveness revalidation."""
        with self._lock:
            group = receipt._group
            error = None
            if not self._valid_group(group) or receipt is not self._receipt:
                error = "invalid_lease_group"
            elif self._state != "open":
                error = "artifact_lease_manager_closed"
            elif group._state != "candidate" or group._terminal:
                error = "invalid_lease_group"
            elif self._clock() >= group._expiry:
                error = "artifact_candidate_expired"
            elif cancellation is not None and cancellation.is_set():
                error = "artifact_lease_cancelled"
            elif self._clock() >= receipt._deadline:
                error = "artifact_lease_timeout"
            elif group._mutation is not None:
                error = "artifact_lease_busy"
            if error is None and receipt._artifact is not None:
                artifact = receipt._artifact
                version = self._new_version(artifact)
                lease = self._new_token(group, version)
                self._versions[id(artifact)] = version
                self._publish_token(lease)
                receipt._state = "adopted"
                self._settle_receipt(receipt)
                return LeaseAcquireResult(True, lease)
            version = None
            if receipt._artifact is not None:
                version = self._new_version(receipt._artifact)
                version.retired_at = self._clock()
                self._versions[id(receipt._artifact)] = version
            receipt._state = "delete_debt"
            self._settle_receipt(receipt)
        if version is not None:
            self._dispose_retired_version(version)
        return LeaseAcquireResult(False, errors=(error or "invalid_lease_group",))

    def _finish_failed_receipt(self, receipt) -> None:
        """Retain owner debt while releasing only lease-layer reservations."""
        with self._lock:
            self._settle_receipt(receipt)

    def _reconcile_interrupted_adoption(
        self, receipt, primary: BaseException
    ) -> None:
        """Keep an adopted token or retain exact cleanup after interruption."""
        with self._lock:
            group = receipt._group
            self._reconcile_group_mutation(group)
            slot_artifact = getattr(receipt._slot, "artifact", None)
            if receipt._artifact is None:
                receipt._artifact = slot_artifact
            version = (
                None if receipt._artifact is None
                else self._versions.get(id(receipt._artifact))
            )
            adopted = version is not None and bool(version.tokens)
            if not adopted and receipt._artifact is not None:
                if version is None:
                    version = self._new_version(receipt._artifact)
                    self._versions[id(receipt._artifact)] = version
                if version.retired_at is None:
                    version.retired_at = self._clock()
            receipt._state = "adopted" if adopted else "delete_debt"
            self._settle_receipt(receipt)
        if not adopted and version is not None:
            self._dispose_after_interruption(version, primary)

    def _dispose_retired_version(self, version) -> None:
        """Attempt authorized cleanup without waiting for another physical owner."""
        physical_owner = object()
        try:
            with self._lock:
                if (
                    self._state == "closing"
                    and self._close_deadline is not None
                    and self._clock() >= self._close_deadline
                ):
                    return
                if not self._acquire_physical(physical_owner):
                    return
                # This post-acquisition check starts the disposal pass. Close
                # linearizes under the same lock before or after this boundary.
                if (
                    self._state == "closing"
                    and self._close_deadline is not None
                    and self._clock() >= self._close_deadline
                ):
                    return
            result = self._owner.dispose(version.artifact)
            if not result.cleanup_pending:
                with self._lock:
                    if self._versions.get(id(version.artifact)) is version:
                        self._versions.pop(id(version.artifact), None)
            else:
                version.cleanup_pending = True
        except BaseException:
            version.cleanup_pending = True
            raise
        finally:
            self._release_physical(physical_owner)

    def _dispose_after_interruption(self, version, primary: BaseException) -> None:
        """Preserve a primary while attempting non-blocking exact cleanup."""
        try:
            self._dispose_retired_version(version)
        except BaseException as cleanup_error:
            try:
                primary.add_note(
                    f"artifact cleanup interrupted: {type(cleanup_error).__name__}"
                )
            except BaseException:
                pass

    def _rollback_receipt_after_interruption(
        self, receipt, primary: BaseException
    ) -> None:
        """Rollback an armed reservation without replacing a host interruption."""
        try:
            self._rollback_receipt(receipt)
        except BaseException as cleanup_error:
            try:
                primary.add_note(
                    f"receipt rollback interrupted: {type(cleanup_error).__name__}"
                )
            except BaseException:
                pass

    def _rollback_receipt(self, receipt) -> None:
        """Rollback a receipt before physical capture starts."""
        with self._lock:
            self._settle_receipt(receipt)

    def _settle_receipt(self, receipt) -> None:
        """Settle only this receipt and its exact candidate pending custody."""
        if receipt._group._pending_capture is receipt:
            receipt._group._pending_capture = False
        receipt._reserved_token = False
        receipt._reserved_version = False
        if self._receipt is receipt:
            self._receipt = None
        if receipt._state not in ("adopted", "delete_debt"):
            receipt._state = "settled"
        self._remove_group_if_settled(receipt._group)
