"""Explicit legacy prepared test resources, not an application owner. Author: DawsonLin."""

import logging
from pathlib import Path
from types import SimpleNamespace

from topsailai.hooks.configured_contracts import (
    ConfiguredHookPoint, ConfiguredHooks, ConfiguredScript, ConfiguredPreparationRequest,
)
from topsailai.hooks.configuration import HookSettings
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from tests.summary_catalog_support import SUMMARY_CATALOG, PHASE_ONE_DECLARATIONS
from topsailai.hooks.runtime import HookRuntime
from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
from topsailai.hooks.configured_executor import ConfiguredHookExecutor


def build_summary_preparation_request(
    *, points_root: Path | None = None, settings: HookSettings | None = None,
    disabled_hook_names: frozenset[str] = frozenset(),
    script_platform_policy: ExecutablePlatformPolicy | None = None,
) -> ConfiguredPreparationRequest:
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
    return ConfiguredPreparationRequest(configuration, SUMMARY_CATALOG, disabled_hook_names)


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


def prepared_graph(*, request, trust_policy, temp_root):
    """Assemble retained APIs explicitly; assert exact fixture cleanup without retries."""
    runtime = HookRuntime(request.configuration.settings,
        temp_root=temp_root, configured_trust=trust_policy)
    scope = runtime.open_scope(metadata={"owner": "legacy_test"})
    registrar = None

    def close():
        """Close fixture resources and fail rather than invent a successful cleanup."""
        if registrar is not None:
            registrar.stop_admission()
        scope_report = scope.close()
        runtime_report = runtime.close()
        debts = tuple(runtime.cleanup_debts())
        assert not scope_report.cleanup_debts and not runtime_report.cleanup_debts and not debts
        return SimpleNamespace(fully_closed=True, unresolved_debts=(), failed_stages=(),
            scope_report=scope_report, runtime_report=runtime_report)

    try:
        registrar = ConfiguredHookRegistrar.from_prepared(runtime, scope, request)
        executor = ConfiguredHookExecutor(runtime, scope, registrar, request.catalog)
        dispositions = registrar.dispositions
        for item in dispositions:
            logging.getLogger(__name__).log(
                logging.INFO if item.kind == "registered" else logging.WARNING,
                "legacy_prepared point=%s kind=%s reason=%s", item.hook_name, item.kind, item.reason)
        return SimpleNamespace(runtime=runtime, scope=scope, registrar=registrar,
            executor=executor, close=close, startup_report=SimpleNamespace(
                ready=True, dispositions=dispositions,
                metrics=tuple((d.hook_name, d.kind, d.reason, 1) for d in dispositions)))
    except BaseException:
        close()
        raise
