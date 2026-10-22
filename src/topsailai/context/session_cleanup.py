"""Session lifecycle cleanup policy outside SQL storage (author: DawsonLin)."""

from datetime import datetime, timedelta

from topsailai.logger import logger


class HistoryCleanupManager:
    """Compose history storage with conservative whole-message retention."""

    def __init__(self, storage, activity_probe):
        """Keep storage and explicitly resolved local activity authority separate."""
        self.storage = storage
        self.activity_probe = activity_probe

    def __getattr__(self, name):
        """Delegate ordinary history operations, including summary pruning."""
        return getattr(self.storage, name)

    def _can_clean_message(self, msg_id):
        """Require stopped evidence for every owner, not just the oldest session."""
        sessions = self.storage.get_message_sessions(msg_id)
        if not sessions:
            return False
        for sid in sessions:
            home = self.storage.get_session_home(sid)
            if home is None or not self.activity_probe.can_clean(sid, home):
                return False
        return True

    def clean_messages(self, before_seconds):
        """Recheck all owners immediately before deleting each old message."""
        deleted = 0
        for msg_id in self.storage.list_cleanup_messages(before_seconds):
            if not self._can_clean_message(msg_id):
                continue
            if not self._can_clean_message(msg_id):
                continue
            count = self.storage.delete_cleanup_message(msg_id, before_seconds)
            deleted += count
            if count:
                logger.info("Deleted old message: msg_id=%s", msg_id)
        return deleted


class SessionCleanupManager:
    """Coordinate session cleanup without contaminating SQL primitives."""

    def __init__(self, storage, activity_probe):
        """Compose a database manager and the boundary-provided activity probe."""
        self.storage = storage
        self.activity_probe = activity_probe

    def _can_clean(self, session_id):
        """Resolve current database provenance before each owner observation."""
        rows = self.storage.list_sessions(sessions=[session_id])
        if not rows:
            return False
        return self.activity_probe.can_clean(session_id, rows[0].topsailai_home or "")

    def delete_session(self, session_id):
        """Preserve running/unknown owners and reverify before SQL deletion."""
        if not self._can_clean(session_id):
            return False
        if not self._can_clean(session_id):
            return False
        return self.storage.delete_session(session_id)

    def evict_sessions(self, new_id):
        """Skip protected candidates and allow the soft limit to be exceeded."""
        candidates = self.storage.list_sessions(order_by="create_time")
        excess = len(candidates) - 100
        for candidate in candidates:
            if excess <= 0:
                break
            if candidate.session_id == new_id:
                continue
            if self.delete_session(candidate.session_id):
                excess -= 1

    def clean_sessions(self, before_seconds):
        """Select old rows while retaining the existing zero-seconds behavior."""
        if before_seconds == 0:
            return 0
        cutoff = datetime.now() - timedelta(seconds=before_seconds)
        candidates = self.storage.list_sessions(order_by="create_time")
        return sum(self.delete_session(row.session_id) for row in candidates
                   if row.create_time < cutoff)
