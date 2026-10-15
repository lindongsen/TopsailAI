"""Application-owned lifecycle for configured Hook resources."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

from topsailai.hooks.application_access import HookApplicationAccess, bind_hook_application
from topsailai.hooks.configured_contracts import (
    ConfiguredTrustPolicy,
    SummaryPointDisposition,
    SummaryPreparationRequest,
)
from topsailai.hooks.configured_executor import ConfiguredHookExecutor
from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
from topsailai.hooks.hook_point_catalog import HookPointCatalog
from topsailai.hooks.runtime import CloseReport, HookRuntime


@dataclass(frozen=True, slots=True)
class HooksStartupCounts:
    """Bound counts for one prepared startup result."""

    registered: int = 0
    disabled: int = 0
    unavailable: int = 0


@dataclass(frozen=True, slots=True)
class HooksStartupReport:
    """Expose bounded startup dispositions for one application."""

    enabled: bool
    dispositions: tuple[SummaryPointDisposition, ...] = ()
    counts: HooksStartupCounts = HooksStartupCounts()


@dataclass(frozen=True, slots=True)
class HooksCloseResult:
    """Retain lifecycle reports and exact unresolved cleanup debts."""

    registrar_stopped: bool = False
    scope_report: CloseReport | None = None
    runtime_report: CloseReport | None = None
    attempted_debt_ids: tuple[str, ...] = ()
    unresolved_debts: tuple[object, ...] = ()
    failed_stages: tuple[str, ...] = ()
    interrupted_stages: tuple[str, ...] = ()
    fully_closed: bool = False
    historical_failed_stages: tuple[str, ...] = ()
    historical_interrupted_stages: tuple[str, ...] = ()
    access_stopped: bool = False
    debt_observation_succeeded: bool = False


class HooksApplication:
    """Own one application-level configured Hook resource graph."""

    def __init__(
        self,
        *,
        request: SummaryPreparationRequest | None = None,
        trust_policy: ConfiguredTrustPolicy | None = None,
        temp_root: str | None = None,
    ) -> None:
        """Validate inputs, eagerly prepare resources, and retain ownership."""
        supplied = (request is not None, trust_policy is not None, temp_root is not None)
        if any(supplied) and not all(supplied):
            raise ValueError("Hook application inputs must be supplied together")
        if not any(supplied):
            self.request = None
            self.runtime = self.scope = self.registrar = self.executor = None
            self.access = HookApplicationAccess(None)
            self.startup_report = HooksStartupReport(False)
            self._close_result = HooksCloseResult(fully_closed=True)
            self._closed = True
            self._binding_context = None
            return
        if type(request) is not SummaryPreparationRequest:
            raise ValueError("invalid Hook application request")
        if type(trust_policy) is not ConfiguredTrustPolicy:
            raise ValueError("invalid Hook application trust policy")
        if type(temp_root) is not str or not os.path.isabs(temp_root):
            raise ValueError("Hook application temp_root must be absolute")
        if type(request.catalog) is not HookPointCatalog:
            raise ValueError("invalid Hook application catalog")

        self.request = request
        self.runtime = self.scope = self.registrar = self.executor = self.access = None
        self.startup_report = None
        self._close_result = HooksCloseResult()
        self._closed = False
        self._binding_context = None
        self._shutdown_ms = request.configuration.settings.limits.shutdown_timeout_ms
        try:
            self.runtime = HookRuntime(
                request.configuration.settings,
                temp_root=temp_root,
                configured_trust=trust_policy,
            )
            self.scope = self.runtime.open_scope(metadata={"owner": "hooks_application"})
            self.registrar = ConfiguredHookRegistrar.from_prepared(
                self.runtime, self.scope, request
            )
            self.executor = ConfiguredHookExecutor(
                self.runtime, self.scope, self.registrar, request.catalog
            )
            self.access = HookApplicationAccess(self.executor)
            dispositions = tuple(self.registrar.dispositions)
            self.startup_report = HooksStartupReport(
                True,
                dispositions,
                HooksStartupCounts(
                    registered=sum(item.kind == "registered" for item in dispositions),
                    disabled=sum(item.kind == "disabled_by_configuration" for item in dispositions),
                    unavailable=sum(item.kind == "unavailable_preparation_failure" for item in dispositions),
                ),
            )
        except BaseException:
            try:
                self.close()
            except BaseException:
                pass
            raise

    @property
    def close_result(self) -> HooksCloseResult:
        """Return the latest bounded close result."""
        return self._close_result

    @property
    def closing(self) -> bool:
        """Return whether application admission has been stopped."""
        return self._closed

    @contextmanager
    def bind(self) -> Iterator["HooksApplication"]:
        """Bind this application's access for the complete managed body."""
        if self.access is None:
            yield self
            return
        with bind_hook_application(self.access):
            yield self

    @staticmethod
    def _debt_id(debt: object) -> str | None:
        """Extract only the bounded debt identity used in close evidence."""
        value = getattr(debt, "debt_id", None)
        return value if isinstance(value, str) else None

    def close(self) -> HooksCloseResult:
        """Stop admission and close each incomplete owned stage independently."""
        if self._close_result.fully_closed:
            return self._close_result
        self._closed = True
        deadline = time.monotonic() + self._shutdown_ms / 1000
        prior = self._close_result
        failed = list(dict.fromkeys(prior.failed_stages))
        interrupted = list(dict.fromkeys(prior.interrupted_stages))
        historical_failed = list(dict.fromkeys(prior.historical_failed_stages))
        historical_interrupted = list(dict.fromkeys(prior.historical_interrupted_stages))
        registrar_stopped = prior.registrar_stopped
        scope_report = prior.scope_report
        runtime_report = prior.runtime_report
        access_stopped = prior.access_stopped
        debt_observation_succeeded = prior.debt_observation_succeeded
        first_interrupt: BaseException | None = None
        allowed_stages = {"access", "registrar", "scope", "runtime", "debt_observation"}

        def remember(items: list[str], name: str) -> None:
            """Record one bounded stage token in first-observed order."""
            if name in allowed_stages and name not in items:
                items.append(name)

        def clear_stage(name: str) -> None:
            """Remove a recovered stage from current unresolved diagnostics."""
            while name in failed:
                failed.remove(name)
            while name in interrupted:
                interrupted.remove(name)

        def stage(name: str, operation: Callable[[], object]) -> object | None:
            """Run one cleanup stage while preserving later independent stages."""
            nonlocal first_interrupt
            try:
                result = operation()
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError) as error:
                if first_interrupt is None:
                    first_interrupt = error
                remember(interrupted, name)
                remember(historical_interrupted, name)
                return None
            except BaseException:
                remember(failed, name)
                remember(historical_failed, name)
                return None
            clear_stage(name)
            return result

        if self.access is not None and not access_stopped:
            result = stage("access", self.access.stop_admission)
            if result is not None or ("access" not in failed and "access" not in interrupted):
                access_stopped = True
        if not registrar_stopped and self.registrar is not None:
            result = stage("registrar", self.registrar.stop_admission)
            if result is not None or ("registrar" not in failed and "registrar" not in interrupted):
                registrar_stopped = True
        if scope_report is None and self.scope is not None:
            remaining = max(1, int((deadline - time.monotonic()) * 1000))
            result = stage("scope", lambda: self.scope.close(deadline_ms=remaining))
            if isinstance(result, CloseReport):
                scope_report = result
        if runtime_report is None and self.runtime is not None:
            remaining = max(1, int((deadline - time.monotonic()) * 1000))
            result = stage("runtime", lambda: self.runtime.close(deadline_ms=remaining))
            if isinstance(result, CloseReport):
                runtime_report = result
            debt_observation_succeeded = False

        debts: list[object] = []
        for debt in prior.unresolved_debts:
            if not any(existing is debt for existing in debts):
                debts.append(debt)
        for report in (scope_report, runtime_report):
            if report is None:
                continue
            for debt in report.cleanup_debts:
                if not any(existing is debt for existing in debts):
                    debts.append(debt)

        if self.runtime is None:
            debt_observation_succeeded = True
        elif not debt_observation_succeeded or debts:
            debt_result = stage("debt_observation", self.runtime.cleanup_debts)
            if debt_result is not None:
                debts = []
                for debt in tuple(debt_result):
                    if not any(existing is debt for existing in debts):
                        debts.append(debt)
                debt_observation_succeeded = True
            else:
                debt_observation_succeeded = False
                remember(failed, "debt_observation") if "debt_observation" not in interrupted else None

        failed = list(dict.fromkeys(failed))
        interrupted = list(dict.fromkeys(interrupted))
        debts_tuple = tuple(debts)
        complete = (
            (self.access is None or access_stopped)
            and (self.registrar is None or registrar_stopped)
            and (self.scope is None or scope_report is not None)
            and (self.runtime is None or runtime_report is not None)
            and (self.runtime is None or debt_observation_succeeded)
            and not failed
            and not interrupted
            and not debts_tuple
        )
        self._close_result = HooksCloseResult(
            registrar_stopped=registrar_stopped,
            scope_report=scope_report,
            runtime_report=runtime_report,
            attempted_debt_ids=prior.attempted_debt_ids,
            unresolved_debts=debts_tuple,
            failed_stages=tuple(failed),
            interrupted_stages=tuple(interrupted),
            fully_closed=complete,
            historical_failed_stages=tuple(historical_failed),
            historical_interrupted_stages=tuple(historical_interrupted),
            access_stopped=access_stopped,
            debt_observation_succeeded=debt_observation_succeeded,
        )
        if first_interrupt is not None:
            raise first_interrupt
        return self._close_result

    def __enter__(self) -> "HooksApplication":
        """Bind the application for a synchronous context."""
        self._binding_context = self.bind()
        self._binding_context.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        """Close while bound, then restore the exact prior binding."""
        cleanup_error = None
        try:
            try:
                self.close()
            except BaseException as error:
                cleanup_error = error
            if cleanup_error is not None and exc_type is None:
                raise cleanup_error
        finally:
            if self._binding_context is not None:
                self._binding_context.__exit__(exc_type, exc, traceback)
