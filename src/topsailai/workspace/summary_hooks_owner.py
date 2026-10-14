"""Explicit process-shared summarize Hooks composition. Author: DawsonLin."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from topsailai.hooks.configured_contracts import (
    ConfiguredHookPoint, ConfiguredHooks, ConfiguredScript, ConfiguredTrustPolicy,
    SummaryPointDisposition, SummaryPreparationRequest,
)
from topsailai.hooks.configured_executor import ConfiguredHookExecutor
from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.configuration import HookSettings
from topsailai.hooks.points.catalog import SUMMARY_CATALOG, PHASE_ONE_DECLARATIONS
from topsailai.hooks.runtime import CloseReport, HookRuntime

logger = logging.getLogger(__name__)


def build_summary_preparation_request(
    *, points_root: Path | None = None, settings: HookSettings | None = None,
    disabled_hook_names: frozenset[str] = frozenset(),
    script_platform_policy: ExecutablePlatformPolicy | None = None,
) -> SummaryPreparationRequest:
    """Bind each phase-one point directory without discovering or authorizing files."""
    if script_platform_policy is not None and (
        type(script_platform_policy) is not ExecutablePlatformPolicy
        or script_platform_policy.platform != "posix"
        or script_platform_policy.native_suffixes
    ):
        raise ValueError("summary Scripts require an explicit POSIX shebang-only policy")
    if points_root is None:
        points_root = Path(__file__).resolve().parents[1] / "hooks/points/context"
    if not isinstance(points_root, Path) or not points_root.is_absolute():
        raise ValueError("summary point root must be an absolute Path")
    configuration = ConfiguredHooks(hook_points=tuple(ConfiguredHookPoint(
        hook_name=point.name, definition=point.definition,
        module_folder=points_root / point.name.removeprefix("hook__context__").replace("__", "_") / "modules",
        inject_hook_context=True,
        script=_summary_script_source(points_root, point.name, script_platform_policy, disabled_hook_names),
    ) for point in PHASE_ONE_DECLARATIONS),
        settings=HookSettings() if settings is None else settings)
    return SummaryPreparationRequest(configuration, SUMMARY_CATALOG, disabled_hook_names)


def _summary_script_source(points_root, point_name, policy, disabled_names):
    """Select optional named sources without following links or granting authority."""
    if policy is None or point_name in disabled_names:
        return None
    target = points_root / point_name.removeprefix("hook__context__").replace("__", "_") / "scripts"
    try:
        target.lstat()
    except FileNotFoundError:
        return None
    return ConfiguredScript(target=target, platform_policy=policy)


@dataclass(frozen=True, slots=True)
class SummaryStartupReport:
    """Expose detached point outcomes and bounded-label startup metrics."""

    dispositions: tuple[SummaryPointDisposition, ...]
    ready: bool
    metrics: tuple[tuple[str, str, str, int], ...]


@dataclass(frozen=True, slots=True)
class SummaryCloseResult:
    """Retain stage reports and exact cleanup custody without claiming settlement."""

    scope_report: CloseReport | None = None
    runtime_report: CloseReport | None = None
    attempted_debt_ids: tuple[str, ...] = ()
    resolved_debt_ids: tuple[str, ...] = ()
    unresolved_debts: tuple = ()
    failed_stages: tuple[str, ...] = ()
    fully_closed: bool = False


def _identity(request, trust_policy, temp_root):
    """Validate deployment inputs before allocation and freeze comparison identity."""
    if type(request) is not SummaryPreparationRequest or type(trust_policy) is not ConfiguredTrustPolicy:
        raise ValueError("invalid summary Hooks inputs")
    if type(temp_root) is not str or not os.path.isabs(temp_root):
        raise ValueError("summary Hooks temporary root must be absolute")
    if request.catalog != SUMMARY_CATALOG:
        raise ValueError("summary Hooks require the phase-one catalog")
    return request, trust_policy, os.path.normpath(temp_root)


class SummaryHooksOwner:
    """Own eager startup and explicit application-only bounded shutdown."""

    def __init__(self, *, request, trust_policy, temp_root):
        """Compose only the prepared path; retain failed startup cleanup custody."""
        self.identity = _identity(request, trust_policy, temp_root)
        self._lock = threading.RLock()
        self._closing = False
        self._finished = False
        self._completed_stages = set()
        self._failed_stages = []
        self._attempted = []
        self._known_debt_ids = set()
        self._scope_report = None
        self._runtime_report = None
        self.close_result = SummaryCloseResult()
        self.runtime = None
        self.scope = None
        self.registrar = None
        self.executor = None
        self.startup_report = None
        self._shutdown_ms = request.configuration.settings.limits.shutdown_timeout_ms
        try:
            self.runtime = HookRuntime(request.configuration.settings,
                temp_root=temp_root, configured_trust=trust_policy)
            self.scope = self.runtime.open_scope(metadata={"owner": "summary_hooks"})
            self.registrar = ConfiguredHookRegistrar.from_prepared(self.runtime, self.scope, request)
            self.executor = ConfiguredHookExecutor(self.runtime, self.scope, self.registrar, request.catalog)
            dispositions = tuple(SummaryPointDisposition(item.hook_name, item.kind, item.reason)
                for item in self.registrar.dispositions)
            self.startup_report = SummaryStartupReport(dispositions, True,
                tuple((item.hook_name, item.kind, item.reason, 1) for item in dispositions))
            for item in dispositions:
                level = logging.WARNING if item.kind != "registered" else logging.INFO
                logger.log(level, "summary_hook_startup point=%s kind=%s reason=%s",
                    item.hook_name, item.kind, item.reason)
        except BaseException as primary:
            # Retain the exact owner even if cleanup is interrupted before returning.
            primary.summary_hooks_owner = self
            try:
                self.close()
            except BaseException as cleanup:
                if isinstance(cleanup, (KeyboardInterrupt, SystemExit)):
                    cleanup.summary_hooks_owner = self
                    raise
                logger.error("summary_hook_shutdown stage=startup_cleanup reason=internal_error")
            raise

    @property
    def closing(self):
        """Expose terminal admission state without giving sessions close authority."""
        return self._closing

    def _record(self):
        """Checkpoint available reports and exact debt identities before fallible work."""
        debts = () if self.runtime is None else tuple(self.runtime.cleanup_debts())
        self._known_debt_ids.update(debt.debt_id for debt in debts)
        unresolved_ids = {debt.debt_id for debt in debts}
        self.close_result = SummaryCloseResult(
            self._scope_report, self._runtime_report, tuple(self._attempted),
            tuple(sorted(self._known_debt_ids - unresolved_ids)), debts,
            tuple(self._failed_stages),
            self._finished and not self._failed_stages and not debts)

    def _stage(self, name, operation):
        """Attempt each close stage once, preserving host interrupts for resumption."""
        if name in self._completed_stages:
            return
        try:
            report = operation()
            if name == "scope":
                self._scope_report = report
            elif name == "runtime":
                self._runtime_report = report
        except (KeyboardInterrupt, SystemExit):
            self._record()
            raise
        except Exception:
            self._failed_stages.append(name)
            logger.error("summary_hook_shutdown stage=%s reason=internal_error", name)
        self._completed_stages.add(name)
        self._record()

    def close(self) -> SummaryCloseResult:
        """Stop Registrar, Scope, Runtime, then retry exact debt at most twice."""
        with self._lock:
            if self._finished:
                return self.close_result
            self._closing = True
            deadline = time.monotonic() + self._shutdown_ms / 1000
            remaining_ms = lambda: max(1, int((deadline - time.monotonic()) * 1000))
            if self.registrar is not None:
                self._stage("registrar", self.registrar.stop_admission)
            if self.scope is not None:
                self._stage("scope", lambda: self.scope.close(deadline_ms=remaining_ms()))
            if self.runtime is not None:
                self._stage("runtime", lambda: self.runtime.close(deadline_ms=remaining_ms()))
            self._record()
            try:
                self._retry_debts(deadline)
            except (KeyboardInterrupt, SystemExit):
                self._record()
                raise
            self._finished = True
            self._record()
            return self.close_result

    def _retry_debts(self, deadline):
        """Reconcile reported exact debts sequentially under one finite budget."""
        for _ in range(2):
            pending = self.close_result.unresolved_debts
            if not pending or time.monotonic() >= deadline:
                return
            for debt in pending:
                if time.monotonic() >= deadline:
                    return
                if self._attempted.count(debt.debt_id) >= 2:
                    continue
                self._attempted.append(debt.debt_id)
                self._record()
                try:
                    self.runtime.retry_cleanup(debt.debt_id)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception:
                    self._failed_stages.append("cleanup")
                    logger.error("summary_hook_shutdown stage=cleanup reason=internal_error")
                self._record()


_owner_lock = threading.Lock()
_owner: SummaryHooksOwner | None = None


def acquire_summary_hooks_owner(
    *, request: SummaryPreparationRequest, trust_policy: ConfiguredTrustPolicy,
    temp_root: str,
) -> SummaryHooksOwner:
    """Acquire the first successful configured owner without caching empty startup."""
    global _owner
    identity = _identity(request, trust_policy, temp_root)
    with _owner_lock:
        if _owner is not None:
            if _owner.identity != identity:
                raise RuntimeError("conflicting summary Hooks configuration")
            if _owner.closing:
                raise RuntimeError("summary Hooks owner is closing")
            return _owner
        owner = SummaryHooksOwner(request=request, trust_policy=trust_policy, temp_root=temp_root)
        _owner = owner
        return owner
