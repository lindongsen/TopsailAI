"""Persist driver lifecycle metadata and bounded script logs.

Author: DawsonLin
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _timestamp():
    """Return a local timestamp including the UTC offset."""
    return datetime.now().astimezone().isoformat()


class DriverRuntime:
    """Own one run's metadata publication and script logging handler."""

    def __init__(self, directory, session_id, poll_interval, logger,
                 max_bytes=10 * 1024 * 1024, backups=5):
        """Validate the filename and initialize a detached run record."""
        if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}", session_id):
            raise ValueError("session_id must be a safe filename of at most 200 characters")
        if max_bytes <= 0 or backups <= 0:
            raise ValueError("log size and backup count must be positive")
        self.directory = Path(directory)
        self.meta_path = self.directory / (session_id + ".meta")
        self.log_path = self.directory / (session_id + ".log")
        self.logger = logger
        self.handler = None
        self.original_level = logger.level
        self.data = {
            "version": 1, "run_id": uuid.uuid4().hex,
            "session_id": session_id, "pid": os.getpid(),
            "start_time": _timestamp(), "end_time": None,
            "status": "running", "target_status": None,
            "poll_interval": poll_interval, "exit_code": None,
            "stop_reason": None,
        }
        self.max_bytes = max_bytes
        self.backups = backups

    def _publish(self):
        """Atomically publish a complete JSON snapshot without partial reads."""
        self.data["updated_at"] = _timestamp()
        temporary = self.meta_path.with_name(self.meta_path.name + "." + self.data["run_id"] + ".tmp")
        try:
            temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
            os.replace(temporary, self.meta_path)
        finally:
            if temporary.exists():
                temporary.unlink()
                self.logger.warning("deleted unpublished metadata temporary file %s", temporary)

    def __enter__(self):
        """Open the bounded log and publish startup state before polling."""
        self.directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(self.log_path, maxBytes=self.max_bytes,
                                      backupCount=self.backups, encoding="utf-8")
        self.handler = handler
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
        try:
            self._publish()
            return self
        except BaseException:
            self._close()
            raise

    def update_target(self, status):
        """Record the latest successful target observation."""
        self.data["target_status"] = status
        self._publish()

    def set_stop_reason(self, reason):
        """Remember the semantic reason for a normal stop."""
        self.data["stop_reason"] = reason

    def _close(self):
        """Detach and close only the handler owned by this run."""
        if self.handler is not None:
            self.logger.removeHandler(self.handler)
            self.handler.close()
            self.handler = None
        self.logger.setLevel(self.original_level)

    def __exit__(self, kind, error, traceback):
        """Finalize state for normal, signaled and failed termination."""
        code = 0
        if isinstance(error, SystemExit):
            code = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
        elif error is not None:
            code = 130 if isinstance(error, KeyboardInterrupt) else 1
        self.data.update(status="stopped" if code == 0 else "failed",
                         exit_code=code, end_time=_timestamp())
        if self.data["stop_reason"] is None:
            self.data["stop_reason"] = "completed" if error is None else type(error).__name__
        try:
            if error is not None and not isinstance(error, (SystemExit, KeyboardInterrupt)):
                self.logger.error("driver failed", exc_info=(kind, error, traceback))
            self.logger.info("driver stopped: reason=%s exit_code=%s",
                             self.data["stop_reason"], code)
            self._publish()
        finally:
            self._close()
        return False
