"""Owned temporary storage for isolated hook operations."""

from __future__ import annotations

import os
import shutil
import stat
import threading
import uuid
from pathlib import Path

from topsailai.hooks.process_state import CleanupDebt


def validate_temporary_root(temp_root: str, plugin_root: Path) -> Path | None:
    """Validate one explicit private host-owned root without creating it."""
    if type(temp_root) is not str or not temp_root or "\x00" in temp_root:
        return None
    lexical = Path(temp_root)
    if not lexical.is_absolute() or ".." in lexical.parts:
        return None
    try:
        if _has_symlink_component(lexical):
            return None
        root = lexical.resolve(strict=True)
        root_stat = root.stat()
        if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_uid != os.geteuid():
            return None
        mode = stat.S_IMODE(root_stat.st_mode)
        if mode & 0o077 or mode & 0o700 != 0o700:
            return None
        if root == plugin_root or root.is_relative_to(plugin_root):
            return None
        if _has_extended_acl(root):
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return root


def _has_symlink_component(path: Path) -> bool:
    """Return whether any existing lexical component is a symbolic link."""
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if stat.S_ISLNK(current.lstat().st_mode):
            return True
    return False


def _has_extended_acl(path: Path) -> bool:
    """Reject access or default ACL metadata that broadens private mode bits."""
    if not hasattr(os, "listxattr"):
        return True
    names = set(os.listxattr(path, follow_symlinks=False))
    return bool(names & {"system.posix_acl_access", "system.posix_acl_default"})


class TemporaryStorageOwner:
    """Own one invocation directory and exact retryable removal authority."""

    def __init__(self, host_root: Path) -> None:
        self._host_root = host_root
        self._candidate_path: Path | None = None
        self._uncertain_path: Path | None = None
        self._path: Path | None = None
        self._debt: CleanupDebt | None = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        """Return the allocated invocation directory."""
        if self._path is None:
            raise RuntimeError("temporary storage is not allocated")
        return self._path

    def allocate(self) -> bool:
        """Allocate one private invocation directory without owning collisions."""
        for _ in range(128):
            path = self._host_root / f"discovery-{uuid.uuid4().hex}"
            with self._lock:
                self._candidate_path = path
            _before_directory_create(path)
            creation_returned = False
            creation_unresolved = True
            try:
                try:
                    os.mkdir(path, mode=0o700)
                    creation_returned = True
                except FileExistsError:
                    creation_unresolved = False
                    _after_directory_collision(path)
                    self._discard_candidate(path)
                    continue
                except OSError:
                    creation_unresolved = False
                    self._discard_candidate(path)
                    return False
                self._claim_created_path(path)
            except BaseException:
                if creation_returned:
                    self._complete_partial_claim(path)
                elif creation_unresolved:
                    self._preserve_interrupted_creation(path, False)
                else:
                    self._discard_candidate(path)
                raise
            try:
                path.chmod(0o700)
            except OSError:
                self.cleanup()
                return False
            return True
        with self._lock:
            self._candidate_path = None
        return False

    def _claim_created_path(self, path: Path) -> None:
        """Promote one confirmed successful creation to owned storage."""
        with self._lock:
            if self._path == path:
                self._candidate_path = None
                self._ensure_debt_locked()
                return
            if self._candidate_path != path:
                raise RuntimeError("temporary storage candidate changed")
            self._path = path
            self._candidate_path = None
            _after_candidate_promoted(path)
            self._ensure_debt_locked()

    def _complete_partial_claim(self, path: Path) -> None:
        """Complete an interrupted confirmed claim without replacing its exception."""
        try:
            with self._lock:
                if self._path is None and self._candidate_path == path:
                    self._path = path
                if self._path == path:
                    self._candidate_path = None
                    self._ensure_debt_locked()
        except BaseException:
            pass

    def _discard_candidate(self, path: Path) -> None:
        """Withdraw a non-owned candidate without touching its filesystem path."""
        with self._lock:
            if self._candidate_path == path:
                self._candidate_path = None

    def _preserve_interrupted_creation(self, path: Path, creation_returned: bool) -> None:
        """Retain safe recovery without inferring ownership from path existence."""
        try:
            if creation_returned:
                self._claim_created_path(path)
                return
            with self._lock:
                if self._candidate_path == path:
                    self._candidate_path = None
                    self._uncertain_path = path
                    self._ensure_debt_locked()
        except BaseException:
            pass

    def cleanup_debts(self) -> tuple[CleanupDebt, ...]:
        """Return the exact unresolved storage-removal obligation."""
        with self._lock:
            return () if self._debt is None else (self._debt,)

    def retain_cleanup_debt(self) -> None:
        """Retain removal authority while process cleanup remains unsettled."""
        with self._lock:
            if (self._path is not None or self._uncertain_path is not None) and self._debt is None:
                self._ensure_debt_locked()

    def cleanup(self) -> bool:
        """Remove only confirmed owned storage and retain uncertain creation debt."""
        with self._lock:
            self._candidate_path = None
            if self._path is None:
                return self._settle_uncertain_locked()
            path = self._path
            self._ensure_debt_locked()
            try:
                parent = path.parent.resolve(strict=True)
                if parent != self._host_root or path.is_symlink():
                    return False
                if path.exists():
                    shutil.rmtree(path)
            except Exception:
                return False
            except BaseException:
                raise
            self._path = None
            self._debt = None
        try:
            print(f"Deleted owned hook temporary directory: {path}")
        except Exception:
            pass
        return True

    def _settle_uncertain_locked(self) -> bool:
        """Settle an uncertain creation only after confirming the path is absent."""
        if self._uncertain_path is None:
            self._debt = None
            return True
        try:
            self._uncertain_path.lstat()
        except FileNotFoundError:
            self._uncertain_path = None
            self._debt = None
            return True
        except OSError:
            self._ensure_debt_locked()
            return False
        self._ensure_debt_locked()
        return False

    def _ensure_debt_locked(self) -> None:
        """Create one stable removal debt while the owner lock is held."""
        if self._debt is None:
            self._debt = CleanupDebt(
                f"storage-{uuid.uuid4().hex}",
                "storage",
                None,
                "owned temporary storage removal not confirmed",
            )

    def retry_cleanup(self, debt_id: str) -> bool:
        """Retry the one exact storage-removal obligation."""
        with self._lock:
            if self._debt is None:
                return True
            if self._debt.debt_id != debt_id:
                return False
        return self.cleanup()


def _before_directory_create(path: Path) -> None:
    """Provide an observable boundary before exclusive directory creation."""


def _after_candidate_promoted(path: Path) -> None:
    """Provide an observable boundary after ownership promotion."""


def _after_directory_collision(path: Path) -> None:
    """Provide an observable boundary after non-owned collision withdrawal."""
