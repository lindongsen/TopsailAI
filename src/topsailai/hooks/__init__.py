"""Public foundational contracts for the standalone unified hooks framework."""


from topsailai.hooks.artifact_contracts import (
    ArtifactCapturePolicy,
    ArtifactCaptureRequest,
    ArtifactCaptureResult,
    ArtifactCaptureTrust,
    ArtifactCleanupDebt,
    ArtifactClosureAssertion,
    ArtifactDisposeResult,
    ArtifactFileIdentity,
    ArtifactInterpreterEvidence,
    ArtifactInventoryEntry,
    ArtifactPythonRuntimeAuthority,
    ArtifactValidationEvidence,
)
from topsailai.hooks.artifact_store import (
    ArtifactCaptureOwner,
    CapturedArtifact,
    get_artifact_recovery_owner,
)
from topsailai.hooks.configuration import HookLimits, HookSettings
from topsailai.hooks.configured_bootstrap import (
    ConfiguredHookBinding,
    ConfiguredHookBootstrap,
    load_configured_hook_bootstrap,
    load_configured_trust_manifest,
)
from topsailai.hooks.configured_executor import (
    ConfiguredHookExecutor,
    HookOperation,
    HookPointBlockedError,
)
from topsailai.hooks.configured_registration import (
    ConfiguredHookRegistrar,
    RegistrationEnsureResult,
    RegistrationFailureKind,
    RegistrationState,
)
from topsailai.hooks.configured_contracts import (
    ConfiguredHookPoint,
    is_valid_hook_name,
    ConfiguredHooks,
    ConfiguredModuleFailure,
    ConfiguredPlanSummary,
    ConfiguredRegistrationResult,
    ConfiguredPreparationPolicy,
    ConfiguredScript,
    ConfiguredTrustPolicy,
)
from topsailai.hooks.contracts import (
    Binding,
    DispatchReport,
    EventDefinition,
    HookContext,
    HookEvent,
    HookOutcome,
    HookStatus,
    JsonValue,
    RegistrationHandle,
    RegistrationResult,
    RegistrySnapshot,
    ReloadResult,
)
from topsailai.hooks.hook_script import (
    HookPointBindingPlan,
    HookScriptBinding,
    HookScriptEntryResult,
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
    HookScriptRunner,
    HookScriptSettlement,
    build_hook_point_binding_plan,
    build_hook_point_binding_plan_from_discovery,
    execute_configured_hook_script,
    hook_script_ready,
    settle_configured_empty_hook_script,
    settle_unconfigured_hook_script,
)
from topsailai.hooks.hook_script_discovery import (
    ExecutablePlatformPolicy,
    HookScriptDiscoveryResult,
    HookScriptEntry,
    discover_hook_script_entries,
)
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration
from topsailai.hooks.hook_point_decorator import HookInvocationView, hook_point
from topsailai.hooks.module_discovery_policy import ModuleDiscoveryPolicy
from topsailai.hooks.registry import HookRegistry
from topsailai.hooks.runtime import CloseReport, HookRuntime, HookScope
from topsailai.hooks.script_runner import OwnedHookScriptRunner
from topsailai.hooks.validation import ValidationError, freeze_json, validate_payload

from topsailai.hooks.result_contracts import (
    HandlerIdentity,
    ReturnedValue,
    ResultDiagnostic,
    ResultTiming,
    ResultCleanup,
    ResultDecision,
    HandlerResult,
    HookPointResult,
)

__all__ = [
    "HandlerIdentity",
    "ReturnedValue",
    "ResultDiagnostic",
    "ResultTiming",
    "ResultCleanup",
    "ResultDecision",
    "HandlerResult",
    "HookPointResult",

    "ArtifactCaptureOwner",
    "ArtifactCapturePolicy",
    "ArtifactCaptureRequest",
    "ArtifactCaptureResult",
    "ArtifactCaptureTrust",
    "ArtifactCleanupDebt",
    "ArtifactClosureAssertion",
    "ArtifactDisposeResult",
    "ArtifactFileIdentity",
    "ArtifactInterpreterEvidence",
    "ArtifactInventoryEntry",
    "ArtifactPythonRuntimeAuthority",
    "ArtifactValidationEvidence",
    "CapturedArtifact",
    "Binding",
    "ConfiguredHookBinding",
    "ConfiguredHookBootstrap",
    "ConfiguredHookExecutor",
    "ConfiguredHookRegistrar",
    "ConfiguredHookPoint",
    "is_valid_hook_name",
    "ConfiguredHooks",
    "ConfiguredModuleFailure",
    "ConfiguredPlanSummary",
    "ConfiguredRegistrationResult",
    "ConfiguredPreparationPolicy",
    "ConfiguredScript",
    "ConfiguredTrustPolicy",
    "CloseReport",
    "DispatchReport",
    "EventDefinition",
    "ExecutablePlatformPolicy",
    "HookContext",
    "HookEvent",
    "HookLimits",
    "HookOutcome",
    "HookInvocationView",
    "HookOperation",
    "HookPointBlockedError",
    "HookPointCatalog",
    "HookPointDeclaration",
    "HookPointBindingPlan",
    "HookRegistry",
    "HookRuntime",
    "HookScope",
    "ModuleDiscoveryPolicy",
    "OwnedHookScriptRunner",
    "HookScriptBinding",
    "HookScriptDiscoveryResult",
    "HookScriptEntry",
    "HookScriptEntryResult",
    "HookScriptExecutionOptions",
    "HookScriptExecutionPolicy",
    "HookScriptRunner",
    "HookScriptSettlement",
    "HookSettings",
    "HookStatus",
    "JsonValue",
    "RegistrationEnsureResult",
    "RegistrationFailureKind",
    "RegistrationState",
    "RegistrationHandle",
    "RegistrationResult",
    "RegistrySnapshot",
    "ReloadResult",
    "ValidationError",
    "build_hook_point_binding_plan",
    "build_hook_point_binding_plan_from_discovery",
    "discover_hook_script_entries",
    "execute_configured_hook_script",
    "freeze_json",
    "get_artifact_recovery_owner",
    "hook_point",
    "hook_script_ready",
    "load_configured_hook_bootstrap",
    "load_configured_trust_manifest",
    "settle_configured_empty_hook_script",
    "settle_unconfigured_hook_script",
    "validate_payload",
]


# The prototype is independent of legacy application-bound dispatch.
from threading import RLock as _HookPointLock

_point_configuration = None
_point_configuration_lock = _HookPointLock()


def initialize_hook_points(config=None):
    """Read prototype environment once, or publish an explicit detached snapshot."""
    import json
    import os
    from topsailai.hooks.point_entry import decode_points

    global _point_configuration
    if config is None:
        config = json.loads(os.environ.get("TOPSAILAI_HOOK_POINTS", "{}"))
    candidate = decode_points(config)
    with _point_configuration_lock:
        _point_configuration = candidate
    return candidate


def invoke_hook_point(name, **payload):
    """Resolve bundled and configured resources without application assembly."""
    import logging
    from topsailai.hooks.point_entry import execute_point
    from topsailai.hooks.point_entry_results import unavailable_result

    try:
        with _point_configuration_lock:
            points = _point_configuration
            if points is None:
                points = initialize_hook_points()
        return execute_point(name, points, payload=payload)
    except Exception:
        logging.getLogger(__name__).exception("Hook Point %s initialization failed", name)
        return unavailable_result(name, "initialization_failed")


__all__ += ["initialize_hook_points", "invoke_hook_point"]


def hook__llm__before__first_byte_wait_tick(**payload):
    """Forward structured wait observations without interpreting Module returns."""
    return invoke_hook_point("hook__llm__before__first_byte_wait_tick", **payload)


__all__ += ["hook__llm__before__first_byte_wait_tick"]
