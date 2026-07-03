"""Command history management for the TopsailAI CLI."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional


DEFAULT_HISTORY_MAX_ENTRIES = 100
DEFAULT_HISTORY_MAX_SIZE_MB = 1
DEFAULT_HISTORY_MAX_BACKUPS = 1


class HistoryManager:
    """Manages command history persisted to a JSONL file with rotation."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.history_file = filepath
        self.entries: List[Dict[str, Any]] = []

    def _max_entries(self) -> int:
        """Return the maximum number of entries to keep in memory."""
        value = os.environ.get("TOPSAILAI_HISTORY_MAX_ENTRIES")
        if value is None:
            return DEFAULT_HISTORY_MAX_ENTRIES
        try:
            parsed = int(value)
            return parsed if parsed > 0 else DEFAULT_HISTORY_MAX_ENTRIES
        except (ValueError, TypeError):
            return DEFAULT_HISTORY_MAX_ENTRIES

    def _max_size_bytes(self) -> int:
        """Return the maximum active history file size in bytes."""
        value = os.environ.get("TOPSAILAI_HISTORY_MAX_SIZE_MB")
        if value is None:
            return DEFAULT_HISTORY_MAX_SIZE_MB * 1024 * 1024
        try:
            parsed = int(value)
            if parsed > 0:
                return parsed * 1024 * 1024
        except (ValueError, TypeError):
            pass
        return DEFAULT_HISTORY_MAX_SIZE_MB * 1024 * 1024

    def _max_backups(self) -> int:
        """Return the maximum number of rotated history backups to keep."""
        value = os.environ.get("TOPSAILAI_HISTORY_MAX_BACKUPS")
        if value is None:
            return DEFAULT_HISTORY_MAX_BACKUPS
        try:
            parsed = int(value)
            return parsed if parsed > 0 else DEFAULT_HISTORY_MAX_BACKUPS
        except (ValueError, TypeError):
            return DEFAULT_HISTORY_MAX_BACKUPS

    def _backup_path(self, index: int) -> str:
        """Return the path for the i-th backup file."""
        return f"{self.filepath}.{index}"

    def _rotate_if_needed(self) -> None:
        """Rotate the active history file if it exceeds the size threshold."""
        if not os.path.isfile(self.filepath):
            return

        max_size = self._max_size_bytes()
        try:
            current_size = os.path.getsize(self.filepath)
        except OSError:
            return

        if current_size <= max_size:
            return

        max_backups = self._max_backups()
        print(
            f"[INFO] History file size ({current_size} bytes) exceeds threshold "
            f"({max_size} bytes), rotating..."
        )

        # Shift existing backups upward so the newest backup is always .1.
        for i in range(max_backups, 0, -1):
            src = self._backup_path(i)
            dst = self._backup_path(i + 1)
            if os.path.exists(src):
                try:
                    os.replace(src, dst)
                except OSError as exc:
                    print(f"[WARN] Failed to rotate history backup {src} -> {dst}: {exc}")

        # Evict the oldest backup if it is still outside the allowed range.
        oldest = self._backup_path(max_backups + 1)
        if os.path.exists(oldest):
            try:
                os.remove(oldest)
                print(f"[INFO] Removed oldest history backup: {oldest}")
            except OSError as exc:
                print(f"[WARN] Failed to remove old history backup {oldest}: {exc}")

        # Move the active file to backup slot 1.
        try:
            os.replace(self.filepath, self._backup_path(1))
            print(f"[INFO] Rotated history file to {self._backup_path(1)}")
        except OSError as exc:
            print(f"[WARN] Failed to rotate history file {self.filepath}: {exc}")

    def _normalize_timestamp(self, ts: Any) -> Optional[int]:
        """Convert legacy timestamp formats to milliseconds since epoch."""
        if ts is None:
            return None
        if isinstance(ts, bool):
            # bool is a subclass of int; treat it as invalid.
            return None
        if isinstance(ts, int):
            return ts if ts >= 1_000_000_000_000 else ts * 1000
        if isinstance(ts, float):
            return int(ts) if ts >= 1_000_000_000_000.0 else int(ts * 1000)
        if isinstance(ts, str):
            ts = ts.strip()
            if not ts:
                return None
            # Try numeric parsing first.
            try:
                numeric = float(ts)
                return self._normalize_timestamp(numeric)
            except ValueError:
                pass
            # Fall back to ISO 8601 parsing.
            try:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp() * 1000)
            except (ValueError, TypeError, OverflowError):
                return None
        return None

    def _read_last_lines(self, n: int) -> List[str]:
        """Return up to the last n non-empty lines from the file.

        Reads the file from the end in chunks so huge history files do not
        need to be loaded entirely into memory.
        """
        if n <= 0:
            return []

        lines: List[str] = []
        try:
            with open(self.filepath, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()

                # Some file-like objects (e.g. mocks) may not return an int
                # from tell(). Fall back to a straightforward read in that
                # case; real files on disk always return an integer here.
                if not isinstance(size, int):
                    f.seek(0)
                    result: List[str] = []
                    for line in f.readlines():
                        if isinstance(line, bytes):
                            line = line.decode("utf-8", errors="replace")
                        line = line.strip()
                        if line:
                            result.append(line)
                    return result[:n]

                if size == 0:
                    return []

                chunk_size = 8192
                buffer = b""
                pos = size

                while pos > 0:
                    start = max(0, pos - chunk_size)
                    read_size = pos - start
                    f.seek(start)
                    chunk = f.read(read_size)
                    buffer = chunk + buffer
                    pos = start

                    while True:
                        newline_pos = buffer.rfind(b"\n")
                        if newline_pos == -1:
                            break
                        line = buffer[newline_pos + 1 :]
                        if line:
                            lines.append(line.decode("utf-8", errors="replace"))
                            if len(lines) >= n:
                                return list(reversed(lines))
                        buffer = buffer[:newline_pos]

                # First line of the file has no leading newline.
                if buffer and len(lines) < n:
                    lines.append(buffer.decode("utf-8", errors="replace"))

                return list(reversed(lines))
        except OSError:
            return []

    def load_all(self) -> None:
        """Load the most recent history entries up to the configured limit."""
        if not os.path.isfile(self.filepath):
            return

        max_entries = self._max_entries()
        recent_lines = self._read_last_lines(max_entries)
        self.entries = []
        for line in recent_lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if isinstance(entry, dict):
                    ts = entry.get("ts")
                    normalized = self._normalize_timestamp(ts)
                    if normalized is not None:
                        entry["ts"] = normalized
                    self.entries.append(entry)
            except json.JSONDecodeError:
                continue

    def append(self, scope: str, session_id: str, text: str) -> None:
        """Append a new entry to memory and persist to disk."""
        entry = {
            "scope": scope,
            "session_id": session_id,
            "ts": int(time.time() * 1000),
            "text": text,
        }
        self.entries.append(entry)
        self._persist_entry(entry)

    def _persist_entry(self, entry: Dict[str, Any]) -> None:
        """Append a single entry to the JSONL file, rotating if necessary."""
        self._rotate_if_needed()
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def add(self, text: str, scope: str = "workspace", session_id: str = "") -> None:
        """Backward-compatible alias for append()."""
        self.append(scope, session_id, text)

    def save_all(self) -> None:
        """Persist all in-memory entries to disk (idempotent for JSONL)."""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                for entry in self.entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def search(self, keyword: str) -> List[str]:
        """Return command texts containing *keyword* (case-insensitive)."""
        keyword_lower = keyword.lower()
        results: List[str] = []
        for entry in self.entries:
            text = entry.get("text", "")
            if keyword_lower in text.lower():
                results.append(text)
        return results

    def filter_entries(
        self, scope: str, session_id: Optional[str] = None
    ) -> List[str]:
        """Return command texts matching the given scope and session."""
        results: List[str] = []
        for entry in self.entries:
            if entry.get("scope") != scope:
                continue
            if scope == "session" and session_id is not None:
                if entry.get("session_id") != session_id:
                    continue
            text = entry.get("text", "")
            if text:
                results.append(text)
        return results


def load_readline_history(
    manager: HistoryManager, scope: str, session_id: Optional[str]
) -> None:
    """Clear readline history and load filtered entries for the current context."""
    try:
        import readline
    except ImportError:
        return
    try:
        readline.clear_history()
    except AttributeError:
        return
    texts = manager.filter_entries(scope, session_id)
    for text in texts:
        try:
            readline.add_history(text)
        except AttributeError:
            break
