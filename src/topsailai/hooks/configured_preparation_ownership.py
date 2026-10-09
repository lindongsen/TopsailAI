"""Private aggregate ownership for configured preparation."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from topsailai.hooks.artifact_cleanup import require_fd_metadata_absent
from topsailai.hooks.artifact_leases import ArtifactLeaseManager
from topsailai.hooks.module_discovery import ModuleCleanupOwner


@dataclass(slots=True)
class CaptureShard:
    """Own one independent U07 manager, group, and captured leases."""

    index: int
    manager: ArtifactLeaseManager
    group: object
    leases: list[object] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AggregateCleanupDebt:
    """Identify one bounded cleanup obligation and its exact owner."""

    debt_id: str
    category: str
    owner: object
    underlying_id: str | None = None


class ConfiguredRootOwner:
    """Own descriptor-relative configured roots and pinned identities."""

    __slots__ = (
        "_root", "_root_fd", "_root_identity", "_children", "_identities",
        "_closed", "_cleanup_pending", "_failed_slots",
    )

    def __init__(self, root: Path, ownership=None) -> None:
        """Open and validate the parent and fixed child directories."""
        self._root = root
        self._root_fd = -1
        self._root_identity: tuple[int, int, int, int, int] | None = None
        self._children: dict[str, int] = {}
        self._identities: dict[str, tuple[int, int, int, int, int]] = {}
        self._closed = False
        self._cleanup_pending = False
        self._failed_slots: set[int] = set()
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            if ownership is not None:
                ownership.adopt_root(self)
            self._root_fd = os.open(root, flags)
            self._validate_fd(self._root_fd)
            self._root_identity = self._identity(os.fstat(self._root_fd))
            for name in ("configured-artifacts", "configured-discovery"):
                try:
                    os.mkdir(name, mode=0o700, dir_fd=self._root_fd)
                except FileExistsError:
                    pass
                fd = os.open(name, flags, dir_fd=self._root_fd)
                self._children[name] = fd
                self._validate_fd(fd)
                self._identities[name] = self._identity(os.fstat(fd))
        except BaseException as primary:
            cleanup_error = None
            try:
                self.close()
            except BaseException as error:
                cleanup_error = error
            if isinstance(primary, (KeyboardInterrupt, SystemExit)):
                _attach_root_recovery_owner(primary, self)
                raise primary
            if isinstance(cleanup_error, (KeyboardInterrupt, SystemExit)):
                _attach_root_recovery_owner(cleanup_error, self)
                raise cleanup_error
            error = ValueError("trust_rejected")
            _attach_root_recovery_owner(error, self)
            raise error from None

    @staticmethod
    def _identity(status: os.stat_result) -> tuple[int, int, int, int, int]:
        """Return the pinned device, inode, owner, type, and mode."""
        return (status.st_dev, status.st_ino, status.st_uid, stat.S_IFMT(status.st_mode), stat.S_IMODE(status.st_mode))

    @classmethod
    def _validate_fd(cls, fd: int) -> None:
        """Require an owner-only directory descriptor and absent metadata."""
        status = os.fstat(fd)
        if cls._identity(status)[2:] != (os.geteuid(), stat.S_IFDIR, 0o700):
            raise ValueError("trust_rejected")
        try:
            require_fd_metadata_absent(fd, directory=True)
        except Exception as exc:
            raise ValueError("trust_rejected") from exc

    def _revalidate_root(self) -> None:
        """Require the root pathname to identify the held parent descriptor."""
        if self._closed or self._root_fd < 0 or self._root_identity is None:
            raise ValueError("trust_rejected")
        self._validate_fd(self._root_fd)
        if self._identity(os.fstat(self._root_fd)) != self._root_identity:
            raise ValueError("trust_rejected")
        try:
            observed = os.stat(self._root, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("trust_rejected") from exc
        if self._identity(observed) != self._root_identity:
            raise ValueError("trust_rejected")

    def _revalidate_child(self, name: str) -> None:
        """Validate held descriptor and no-follow pathname identity."""
        self._revalidate_root()
        fd = self._children.get(name)
        expected = self._identities.get(name)
        if fd is None or expected is None:
            raise ValueError("trust_rejected")
        self._validate_fd(fd)
        if self._identity(os.fstat(fd)) != expected:
            raise ValueError("trust_rejected")
        try:
            observed = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("trust_rejected") from exc
        if self._identity(observed) != expected:
            raise ValueError("trust_rejected")

    def child(self, name: str) -> Path:
        """Return a fixed child path only after identity revalidation."""
        self._revalidate_child(name)
        return self._root / name

    def revalidate(self) -> None:
        """Revalidate the parent and every child before a handoff."""
        self._revalidate_root()
        for name in tuple(self._children):
            self._revalidate_child(name)

    def close_slot(self, slot: str) -> bool:
        """Close only an exact currently owned root or child descriptor slot."""
        if self._closed:
            return True
        self._cleanup_pending = True
        try:
            descriptor = int(slot)
        except (TypeError, ValueError):
            return False
        name = next((key for key, value in self._children.items() if value == descriptor), None)
        if descriptor != self._root_fd and name is None:
            return False
        try:
            os.close(descriptor)
        except OSError:
            return False
        self._failed_slots.discard(descriptor)
        if name is not None:
            self._children.pop(name, None)
            self._identities.pop(name, None)
        else:
            self._root_fd = -1
        self._closed = self._root_fd < 0 and not self._children
        if self._closed:
            self._cleanup_pending = False
        return True

    def close(self) -> bool:
        """Close descriptors while retaining failed slots for retry."""
        if self._closed:
            return True
        self._cleanup_pending = True
        settled = True
        for name, fd in tuple(self._children.items()):
            try:
                os.close(fd)
            except OSError:
                self._failed_slots.add(fd)
                settled = False
            else:
                self._failed_slots.discard(fd)
                self._children.pop(name, None)
                self._identities.pop(name, None)
        if self._root_fd >= 0:
            try:
                os.close(self._root_fd)
            except OSError:
                self._failed_slots.add(self._root_fd)
                settled = False
            else:
                self._failed_slots.discard(self._root_fd)
                self._root_fd = -1
        if settled:
            self._closed = True
            self._cleanup_pending = False
        return settled

    def requires_recovery(self) -> bool:
        """Return whether exact descriptor custody remains recoverable."""
        return self._root_fd >= 0 or bool(self._children)

    def cleanup_debts(self) -> tuple[object, ...]:
        """Return every exact owned descriptor after cleanup begins."""
        if not self._cleanup_pending:
            return ()
        slots = list(self._children.values())
        if self._root_fd >= 0:
            slots.append(self._root_fd)
        return tuple(
            type("RootCleanupDebt", (), {"debt_id": str(slot)})()
            for slot in sorted(set(slots))
        )


def _attach_root_recovery_owner(error: BaseException, owner: ConfiguredRootOwner) -> None:
    """Attach exact root authority only when constructor cleanup remains pending."""
    if owner.requires_recovery():
        setattr(error, "__topsailai_configured_root_recovery_owner__", owner)


def get_configured_root_recovery_owner(error: BaseException) -> ConfiguredRootOwner | None:
    """Return private root authority retained by constructor failure."""
    owner = getattr(error, "__topsailai_configured_root_recovery_owner__", None)
    return owner if isinstance(owner, ConfiguredRootOwner) else None


class PreparationOwnership:
    """Aggregate all recovery authorities and enforce cleanup precedence."""

    __slots__ = ("root_owner", "shards", "module_owners", "state", "deadline", "_debts", "_u07_debts", "_module_hook_names")

    def __init__(self, root_owner: ConfiguredRootOwner | None, deadline: float) -> None:
        """Create an empty open aggregate."""
        self.root_owner = root_owner
        self.shards: list[CaptureShard] = []
        self.module_owners: list[ModuleCleanupOwner] = []
        self.state = "open"
        self.deadline = deadline
        self._debts: dict[str, AggregateCleanupDebt] = {}
        self._u07_debts: dict[str, object] = {}
        self._module_hook_names: dict[int, str] = {}

    def adopt_root(self, root_owner: ConfiguredRootOwner) -> None:
        """Adopt one root owner without performing I/O."""
        if self.state != "open" or self.root_owner is not None:
            raise RuntimeError("cleanup_pending")
        self.root_owner = root_owner

    def register_shard(self, shard: CaptureShard) -> None:
        """Register a distinct shard before its first capture."""
        if self.state != "open" or any(item.manager is shard.manager or item.group is shard.group for item in self.shards):
            raise RuntimeError("cleanup_pending")
        self.shards.append(shard)

    def register_module_owner(self, owner: ModuleCleanupOwner, hook_name: str | None = None) -> None:
        """Register one distinct Hook discovery owner."""
        if self.state != "open" or any(item is owner for item in self.module_owners):
            raise RuntimeError("cleanup_pending")
        index = len(self.module_owners)
        self.module_owners.append(owner)
        self._module_hook_names[index] = hook_name if hook_name else str(index)

    def mark_pending(self) -> None:
        """Latch pending cleanup and prevent successor work."""
        if self.state != "closed":
            self.state = "cleanup_pending"
            root = self.root_owner
            if root is not None and hasattr(root, "_cleanup_pending"):
                root._cleanup_pending = True

    def requires_recovery(self) -> bool:
        """Return whether aggregate or subordinate ownership is not fully closed."""
        if self.state != "closed":
            return True
        root = self.root_owner
        if root is not None:
            predicate = getattr(root, "requires_recovery", None)
            if predicate is not None and predicate():
                return True
            if getattr(root, "_closed", True) is False:
                return True
        return bool(self.cleanup_debts())

    def cleanup_debts(self) -> tuple[AggregateCleanupDebt, ...]:
        """Return stable bounded debt IDs from the current exact owners."""
        debts: list[AggregateCleanupDebt] = []
        for index, owner in enumerate(self.module_owners):
            for debt in owner.cleanup_debts()[:16]:
                debt_id = f"u03:{self._module_hook_names.get(index, str(index))}:{debt.debt_id}"
                debts.append(AggregateCleanupDebt(debt_id, "u03", owner, debt.debt_id))
        for shard in self.shards:
            for debt in shard.manager.snapshot().cleanup_debts[:16]:
                debt_id = f"u07:{shard.index}:{debt.debt_id}"
                self._u07_debts.setdefault(debt_id, debt)
                debts.append(AggregateCleanupDebt(debt_id, "u07", shard.manager, debt.debt_id))
        if self.root_owner is not None:
            root_debts = getattr(self.root_owner, "cleanup_debts", None)
            if root_debts is not None:
                root_slots = root_debts()
            else:
                root_slots = tuple(
                    type("RootCleanupDebt", (), {"debt_id": str(slot)})()
                    for slot in sorted(getattr(self.root_owner, "_failed_slots", ()))
                )
            for debt in root_slots:
                debts.append(AggregateCleanupDebt(f"root:{debt.debt_id}", "root", self.root_owner, debt.debt_id))
        return tuple(debts)

    def retry_cleanup(self, debt_id: str) -> bool:
        """Route one exact aggregate debt to its owning authority."""
        for debt in self.cleanup_debts():
            if debt.debt_id != debt_id:
                continue
            if debt.category == "u03":
                return debt.owner.retry_cleanup(debt.underlying_id)
            if debt.category == "u07":
                exact_debt = self._u07_debts.get(debt_id)
                if exact_debt is None:
                    return False
                result = debt.owner.retry_cleanup(exact_debt, deadline=self.deadline)
                return result.accepted
            close_slot = getattr(debt.owner, "close_slot", None)
            if close_slot is not None:
                return bool(close_slot(debt.underlying_id))
            return debt.owner.close()
        return False

    def settle(self) -> bool:
        """Settle U03 first, then U07 shards, then root."""
        if self.state == "closed":
            return True
        if any(not _settle_module_owner(owner) for owner in self.module_owners):
            self.mark_pending()
            return False
        for shard in self.shards:
            try:
                shard.manager.release_group(shard.group)
                result = shard.manager.close(deadline=self.deadline)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                self.mark_pending()
                return False
            if not result.accepted or result.cleanup_pending:
                self.mark_pending()
                return False
        if self.root_owner is not None and not self.root_owner.close():
            self.mark_pending()
            return False
        self.state = "closed"
        return True

    def transfer_to_image(self) -> None:
        """Freeze the aggregate only after all resources are settled or retained."""
        if self.state != "open" or self.cleanup_debts():
            raise RuntimeError("cleanup_pending")
        if self.root_owner is not None:
            self.root_owner.revalidate()
        self.state = "transferred"


def _settle_module_owner(owner: ModuleCleanupOwner) -> bool:
    """Settle one U03 owner while retaining unresolved debt."""
    for debt in owner.cleanup_debts()[:16]:
        if not owner.retry_cleanup(debt.debt_id):
            return False
    return not owner.cleanup_debts()
