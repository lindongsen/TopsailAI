"""Execution-local captured Module process custody. Author: DawsonLin."""
import threading


class OwnedHookModuleRunner:
    """Retain original launch records independently of shared backend debt state."""
    def __init__(self, backend):
        """Arm execution-local recovery before any captured Module invocation."""
        self._backend = backend
        self._records = []
        self._lock = threading.RLock()

    def execute(self, module, context, timeout_ms):
        """Invoke captured bytes through the backend's existing cleanup transaction."""
        return self._backend.execute_captured_module(
            module, context, timeout_ms, record_receiver=self._receive_record,
        )

    def _receive_record(self, record):
        """Bind the backend's original identity before it creates launch resources."""
        with self._lock:
            self._records.append(record)

    def cleanup_debts(self):
        """Query only records originally admitted by this execution."""
        with self._lock:
            records = tuple(self._records)
        return tuple(debt for record in records
                     for debt in self._backend.cleanup_debts_for_record(record))

    def retry_cleanup(self, debt_id):
        """Reject foreign and unknown debts before reaching backend authority."""
        with self._lock:
            records = tuple(self._records)
        for record in records:
            if record.debt_id == debt_id:
                return self._backend.retry_cleanup(debt_id, record=record)
        return False
