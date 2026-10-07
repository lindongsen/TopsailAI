"""Recoverable metadata transactions for artifact lease tokens and groups."""

from __future__ import annotations


class ArtifactLeaseTransactionMixin:
    """Reconcile exact token publication and settlement under the manager lock."""

    def _publish_token(self, lease) -> None:
        """Arm token publication before its first registry mutation."""
        group = lease._group
        if group._mutation is None:
            group._mutation = ("issue", lease)
        self._reconcile_group_mutation(group)

    def _issue_token(self, lease):
        """Publish one pre-armed token through retry-safe idempotent insertions."""
        if lease._released:
            return lease
        self._tokens[lease._token_id] = lease
        lease._group._tokens.add(lease._token_id)
        lease._version.tokens.add(lease._token_id)
        lease._version.retired_at = None
        return lease

    def _release_token(self, lease) -> None:
        """Release exact authority through retry-safe idempotent removals."""
        if lease._released:
            return
        self._tokens.pop(lease._token_id, None)
        lease._group._tokens.discard(lease._token_id)
        lease._version.tokens.discard(lease._token_id)
        if not lease._version.tokens and lease._version.retired_at is None:
            lease._version.retired_at = self._clock()
        lease._released = True

    def _charged_token_count(self) -> int:
        """Count live tokens plus the sole pending capture reservation."""
        return len(self._tokens) + int(
            self._receipt is not None and self._receipt._reserved_token
        )

    def _settle_group_tokens(self, group, *, state: str) -> None:
        """Finish prior work, then arm exact custody for whole-group settlement."""
        self._reconcile_group_mutation(group)
        if group._mutation is None:
            leases = tuple(
                self._tokens[token_id]
                for token_id in tuple(group._tokens)
                if token_id in self._tokens
            )
            group._mutation = ("settle", (state, leases))
        self._reconcile_group_mutation(group)

    def _reconcile_group_mutation(self, group: object) -> None:
        """Finish a previously armed group mutation before observing its result."""
        if not self._owned_group(group):
            return
        if group._mutation is None:
            return
        operation, value = group._mutation
        if operation == "issue":
            self._issue_token(value)
            group._mutation = None
            return
        if operation == "release":
            self._release_token(value)
            group._mutation = None
            self._remove_group_if_settled(group)
            return
        if operation != "settle":
            return
        state, leases = value
        for lease in leases:
            self._release_token(lease)
        group._state = state
        group._terminal = True
        self._remove_group_if_settled(group)
        group._mutation = None

    def _remove_group_if_settled(self, group) -> None:
        """Drop terminal metadata only after receipt and tokens settle."""
        if group._terminal and not group._tokens and not group._pending_capture:
            self._unregister_candidate(group)
