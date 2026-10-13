"""Cross-process session exclusion without third-party dependencies.

Author: DawsonLin
"""
import json
import logging
import os
from pathlib import Path


logger = logging.getLogger(__name__)


class DriverAlreadyRunning(RuntimeError):
    """Report an existing or unverifiable session owner."""


class SessionMutex:
    """Hold an OS file lock through runtime cleanup and attempt exit deletion."""

    def __init__(self, meta_path):
        """Bind the lock to one session metadata path."""
        self.meta_path = Path(meta_path)
        self.path = self.meta_path.with_suffix(".lock")
        self.file = None
        self.owned = False

    def acquire(self):
        """Acquire without waiting and then verify any previous owner."""
        self.file = self.path.open("a+b")
        try:
            self._lock()
            self._check_owner()
            self.owned = True
        except BaseException:
            self.release()
            raise

    def _lock(self):
        """Use the platform's nonblocking exclusive lock primitive."""
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0, os.SEEK_END)
                if self.file.tell() == 0:
                    self.file.write(b"\0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise DriverAlreadyRunning("session lock unavailable: " + str(self.meta_path)) from error

    def _check_owner(self):
        """Reject live or unverifiable metadata without changing its files."""
        try:
            with self.meta_path.open(encoding="utf-8") as source:
                text = source.read(65537)
        except FileNotFoundError:
            return
        try:
            if len(text) > 65536:
                raise ValueError("metadata too large")
            data = json.loads(text)
            pid = data.get("pid") if isinstance(data, dict) else None
            if type(pid) is not int or pid <= 0:
                raise ValueError("invalid PID")
        except (ValueError, UnicodeError) as error:
            raise DriverAlreadyRunning("cannot verify session metadata: " + str(self.meta_path)) from error
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        except (OSError, OverflowError) as error:
            raise DriverAlreadyRunning("cannot verify session PID: " + str(pid)) from error
        raise DriverAlreadyRunning("driver already running for session, PID=" + str(pid))

    def release(self):
        """Release the descriptor before attempting to delete an admitted lock."""
        if self.file is None:
            return
        owner, self.file = self.file, None
        owner.close()
        owned, self.owned = self.owned, False
        if not owned:
            return
        try:
            if self.path.exists():
                self.path.unlink()
                logger.warning("deleted driver lock file %s", self.path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("cannot delete driver lock file %s", self.path, exc_info=True)
