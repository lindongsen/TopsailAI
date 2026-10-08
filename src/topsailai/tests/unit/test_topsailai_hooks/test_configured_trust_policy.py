"""Contract tests for Runtime-owned configured trust policy."""

from __future__ import annotations

from collections import UserDict, UserList, UserString
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType

import pytest

from topsailai.hooks import (
    ArtifactCaptureTrust,
    ArtifactClosureAssertion,
    ArtifactPythonRuntimeAuthority,
    ConfiguredHookPoint,
    ConfiguredHooks,
    ConfiguredModuleFailure,
    ConfiguredPlanSummary,
    ConfiguredPreparationPolicy,
    ConfiguredTrustPolicy,
    DisposeConfiguredResult,
    EventDefinition,
    HookLimits,
    HookSettings,
    PrepareConfiguredResult,
    PublishConfiguredResult,
)
from topsailai.hooks.configured_contracts import ConfiguredScript, PreparedConfigured
from topsailai.hooks.hook_script_contracts import (
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
)
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.artifact_structure import validate_capture_trust_structure
from topsailai.hooks.configured_trust import artifact_capture_trust


def test_configured_records_are_frozen_and_deeply_detached(tmp_path: Path) -> None:
    """Caller mutation must not change a configured contract snapshot."""
    kwargs = {"nested": [1, {"value": "before"}]}
    point = ConfiguredHookPoint(
        "point",
        EventDefinition("test.configured", 1),
        module_folder=tmp_path,
        module_kwargs=kwargs,
    )
    configured = ConfiguredHooks((point,), HookSettings())
    kwargs["nested"][1]["value"] = "after"
    assert configured.hook_points[0].module_kwargs["nested"][1]["value"] == "before"
    with pytest.raises(TypeError):
        configured.hook_points[0].module_kwargs["other"] = 1
    with pytest.raises(FrozenInstanceError):
        configured.policy = ConfiguredPreparationPolicy(timeout_ms=1)


def test_configured_hook_point_accepts_mapping_and_round_trips_frozen_kwargs() -> None:
    """Any valid Mapping and a prior frozen snapshot must remain admissible."""
    proxy = MappingProxyType({"nested": [1, {"value": "before"}]})
    first = ConfiguredHookPoint(
        "point-a",
        EventDefinition("test.eventa", 1),
        module_kwargs=proxy,
    )
    second = ConfiguredHookPoint(
        "point-b",
        EventDefinition("test.eventb", 1),
        module_kwargs=first.module_kwargs,
    )
    assert second.module_kwargs == first.module_kwargs
    assert second.module_kwargs is not first.module_kwargs


def test_configured_hook_point_detaches_mutable_mapping_and_rejects_non_mapping() -> None:
    """Mutable Mapping inputs must detach deeply and non-mappings must reject."""
    kwargs = UserDict({"nested": [1, {"value": "before"}]})
    point = ConfiguredHookPoint(
        "point",
        EventDefinition("test.configured", 1),
        module_kwargs=kwargs,
    )
    kwargs["nested"][1]["value"] = "after"
    assert point.module_kwargs["nested"][1]["value"] == "before"
    for invalid in ((), [], "value", 1, None):
        with pytest.raises(ValueError, match="^invalid configured hook point$"):
            ConfiguredHookPoint(
                "point",
                EventDefinition("test.configured", 1),
                module_kwargs=invalid,
            )



def test_configured_hook_point_bounds_mapping_normalization() -> None:
    """Normalization must reject cycles and budgets while allowing shared values."""
    self_dict: dict[str, object] = {}
    self_dict["self"] = self_dict
    self_list: list[object] = []
    self_list.append(self_list)
    mutual_a: dict[str, object] = {}
    mutual_b = {"a": mutual_a}
    mutual_a["b"] = mutual_b
    for invalid in (self_dict, {"value": self_list}, mutual_a):
        with pytest.raises(ValueError, match="^invalid configured hook point$"):
            ConfiguredHookPoint(
                "point",
                EventDefinition("test.configured", 1),
                module_kwargs=invalid,
            )

    too_deep: dict[str, object] = {}
    nested = too_deep
    for _ in range(17):
        child: dict[str, object] = {}
        nested["child"] = child
        nested = child
    with pytest.raises(ValueError, match="^invalid configured hook point$"):
        ConfiguredHookPoint(
            "point",
            EventDefinition("test.configured", 1),
            module_kwargs=too_deep,
        )
    with pytest.raises(ValueError, match="^invalid configured hook point$"):
        ConfiguredHookPoint(
            "point",
            EventDefinition("test.configured", 1),
            module_kwargs={"items": list(range(1_025))},
        )

    shared = {"value": ["safe"]}
    point = ConfiguredHookPoint(
        "point",
        EventDefinition("test.configured", 1),
        module_kwargs={"left": shared, "right": shared},
    )
    assert point.module_kwargs["left"] == point.module_kwargs["right"]
    assert point.module_kwargs["left"] is not point.module_kwargs["right"]

def test_configured_script_rejects_unsafe_environment_values(tmp_path: Path) -> None:
    """Configured caller environments must enforce C04 without host access."""
    invalid_pairs = (
        ("PYTHONPATH", "value"),
        ("LD_PRELOAD", "value"),
        ("BASH_ENV", "value"),
        ("BAD=NAME", "value"),
        ("NAME", "bad\x00value"),
        ("NAME", "bad\ud800value"),
    )
    for pair in invalid_pairs:
        with pytest.raises(ValueError, match="^invalid configured script$"):
            ConfiguredScript(
                tmp_path / "hook",
                ExecutablePlatformPolicy("posix"),
                environment_allowlist=(pair[0],),
                environment_snapshot=(pair,),
            )
        with pytest.raises(ValueError, match="^invalid configured script$"):
            ConfiguredScript(
                tmp_path / "hook",
                ExecutablePlatformPolicy("posix"),
                options=HookScriptExecutionOptions(environment=(pair,)),
            )

    script = ConfiguredScript(
        tmp_path / "hook",
        ExecutablePlatformPolicy("posix"),
        options=HookScriptExecutionOptions(environment=(("OPTION_NAME", "option"),)),
        environment_allowlist=("SAFE_NAME",),
        environment_snapshot=(("SAFE_NAME", "value"),),
    )
    assert script.options.environment == (("OPTION_NAME", "option"),)
    assert script.environment_snapshot == (("SAFE_NAME", "value"),)


def test_trust_policy_validates_structure_and_maps_to_u07_authority(tmp_path: Path) -> None:
    """Configured trust must be an immutable host-only adapter to U07 authority."""
    root = tmp_path / "source"
    policy = ConfiguredTrustPolicy((root,))
    mapped = artifact_capture_trust(policy)
    assert type(mapped) is ArtifactCaptureTrust
    assert mapped.source_roots == (root,)
    assert mapped.closure_assertions == ()
    assert mapped.python_runtime is None
    with pytest.raises(ValueError, match="^invalid configured trust policy$"):
        ConfiguredTrustPolicy(())
    with pytest.raises(ValueError, match="^invalid configured trust policy$"):
        ConfiguredTrustPolicy((Path("relative"),))
    with pytest.raises(ValueError, match="^invalid configured trust policy$"):
        ConfiguredTrustPolicy((root,), allow_native_scripts=1)


def test_trust_policy_rejects_malformed_nested_authority(tmp_path: Path) -> None:
    """Nested authority must satisfy the authoritative U07 structure contract."""
    digest = "a" * 64
    with pytest.raises(ValueError, match="^invalid configured trust policy$"):
        ConfiguredTrustPolicy(
            (tmp_path,),
            python_runtime=ArtifactPythonRuntimeAuthority(Path("python"), digest),
        )
    with pytest.raises(ValueError, match="^invalid configured trust policy$"):
        ConfiguredTrustPolicy(
            (tmp_path,),
            python_runtime=ArtifactPythonRuntimeAuthority(tmp_path / "python", [digest]),
        )
    with pytest.raises(ValueError, match="^invalid configured trust policy$"):
        ConfiguredTrustPolicy(
            (tmp_path,),
            closure_assertions=(
                ArtifactClosureAssertion(
                    Path("plugin.py"), "python_source", "plugin", digest, digest, digest
                ),
            ),
        )


def test_trust_policy_maps_non_default_valid_authority(tmp_path: Path) -> None:
    """A valid non-default policy must map to the same accepted U07 authority."""
    digest = "b" * 64
    assertion = ArtifactClosureAssertion(
        tmp_path / "plugin.py", "python_source", "plugin", digest, digest, digest
    )
    runtime = ArtifactPythonRuntimeAuthority(tmp_path / "python", digest)
    policy = ConfiguredTrustPolicy(
        (tmp_path,),
        allowed_interpreters=(tmp_path / "sh",),
        allow_native_scripts=True,
        closure_assertions=(assertion,),
        python_runtime=runtime,
    )
    mapped = artifact_capture_trust(policy)
    assert validate_capture_trust_structure(mapped)
    assert mapped.closure_assertions == (assertion,)
    assert mapped.python_runtime == runtime
    assert policy.closure_assertions[0] is not assertion
    assert policy.python_runtime is not runtime


def test_configured_hook_point_rejects_relative_module_folder() -> None:
    """Configured module folders must be absolute path values."""
    with pytest.raises(ValueError, match="^invalid configured hook point$"):
        ConfiguredHookPoint(
            "point",
            EventDefinition("test.configured", 1),
            module_folder=Path("relative"),
        )


def test_configured_script_detaches_options_and_rejects_relative_cwd(tmp_path: Path) -> None:
    """Nested script options must be immutable snapshots with absolute paths."""
    argv = ["before"]
    script = ConfiguredScript(
        tmp_path / "hook",
        ExecutablePlatformPolicy("posix"),
        options=HookScriptExecutionOptions(argv=argv),
    )
    argv.append("after")
    assert script.options.argv == ("before",)
    with pytest.raises(ValueError, match="^invalid configured script$"):
        ConfiguredScript(
            tmp_path / "hook",
            ExecutablePlatformPolicy("posix"),
            options=HookScriptExecutionOptions(cwd=Path("relative")),
        )


def test_configured_script_rejects_malformed_option_iterables(tmp_path: Path) -> None:
    """Configured options must reject invalid iterable shapes before detachment."""
    malformed = (
        HookScriptExecutionOptions(argv="abc"),
        HookScriptExecutionOptions(argv=b"abc"),
        HookScriptExecutionOptions(argv={"argument": "value"}),
        HookScriptExecutionOptions(environment=("XY",)),
        HookScriptExecutionOptions(environment=b"XY"),
        HookScriptExecutionOptions(environment={"X": "Y"}),
    )
    for options in malformed:
        with pytest.raises(ValueError, match="^invalid configured script$"):
            ConfiguredScript(
                tmp_path / "hook",
                ExecutablePlatformPolicy("posix"),
                options=options,
            )


def test_configured_script_detaches_valid_option_collections(tmp_path: Path) -> None:
    """Supported list and tuple inputs must remain detached without semantic changes."""
    argv = ["before"]
    environment = [["NAME", "before"]]
    script = ConfiguredScript(
        tmp_path / "hook",
        ExecutablePlatformPolicy("posix"),
        options=HookScriptExecutionOptions(argv=argv, environment=environment),
    )
    argv.append("after")
    environment[0][1] = "after"
    assert script.options.argv == ("before",)
    assert script.options.environment == (("NAME", "before"),)


def test_configured_script_rejects_relative_platform_interpreter(tmp_path: Path) -> None:
    """The complete configured chain must reject relative interpreter paths."""
    with pytest.raises(ValueError, match="^invalid configured script$"):
        script = ConfiguredScript(
            tmp_path / "hook",
            ExecutablePlatformPolicy("posix", allowed_interpreters=("relative-python",)),
        )
        point = ConfiguredHookPoint(
            "point",
            EventDefinition("test.configured", 1),
            script=script,
        )
        ConfiguredHooks((point,), HookSettings())


def test_configured_script_rejects_mutable_platform_scalar(tmp_path: Path) -> None:
    """Configured platform names must be exact immutable strings."""
    mutable = UserString("posix")
    policy = ExecutablePlatformPolicy(mutable)
    with pytest.raises(ValueError, match="^invalid configured script$"):
        ConfiguredScript(tmp_path / "hook", policy)

    posix = ConfiguredScript(
        tmp_path / "posix-hook", ExecutablePlatformPolicy("posix")
    )
    windows = ConfiguredScript(
        tmp_path / "windows-hook", ExecutablePlatformPolicy("windows")
    )
    assert posix.platform_policy.platform == "posix"
    assert windows.platform_policy.platform == "windows"


def test_configured_script_rejects_mutable_nested_scalars(tmp_path: Path) -> None:
    """All nested script scalar fields must use exact immutable types."""
    bad_option_values = (
        HookScriptExecutionOptions(argv=(UserString("arg"),)),
        HookScriptExecutionOptions(environment=((UserString("NAME"), "value"),)),
        HookScriptExecutionOptions(environment=(("NAME", UserString("value")),)),
    )
    for options in bad_option_values:
        with pytest.raises(ValueError, match="^invalid configured script$"):
            ConfiguredScript(
                tmp_path / "hook", ExecutablePlatformPolicy("posix"), options=options
            )

    bad_policies = (
        HookScriptExecutionPolicy(entry_timeout_ms=True),
        HookScriptExecutionPolicy(max_entries=True),
    )
    for policy in bad_policies:
        with pytest.raises(ValueError, match="^invalid configured script$"):
            ConfiguredScript(
                tmp_path / "hook", ExecutablePlatformPolicy("posix"), policy=policy
            )


def test_configured_hooks_detach_settings_snapshot() -> None:
    """Configured hooks must own a fresh validated settings and limits snapshot."""
    limits = HookLimits()
    settings = HookSettings(limits=limits)
    configured = ConfiguredHooks((), settings)
    object.__setattr__(limits, "workers", 0)
    object.__setattr__(settings, "enabled", False)
    assert configured.settings is not settings
    assert configured.settings.limits is not limits
    assert configured.settings.enabled is True
    assert configured.settings.limits.workers == 4


def test_configured_script_owns_absolute_platform_policy_snapshot(tmp_path: Path) -> None:
    """A valid platform policy must be detached through the complete configured chain."""
    interpreter = str(tmp_path / "python")
    policy = ExecutablePlatformPolicy(
        "posix",
        allowed_interpreters=(interpreter,),
        native_suffixes=(".bin",),
    )
    script = ConfiguredScript(tmp_path / "hook", policy)
    point = ConfiguredHookPoint(
        "point",
        EventDefinition("test.configured", 1),
        script=script,
    )
    configured = ConfiguredHooks((point,), HookSettings())
    object.__setattr__(policy, "allowed_interpreters", ("relative-python",))
    object.__setattr__(policy, "native_suffixes", (".changed",))
    saved = configured.hook_points[0].script
    assert saved is not None
    assert saved.platform_policy is not policy
    assert saved.platform_policy.allowed_interpreters == (interpreter,)
    assert saved.platform_policy.native_suffixes == (".bin",)


def test_configured_hook_point_enforces_one_combined_json_budget() -> None:
    """Module positional and keyword values must share one JSON budget."""
    with pytest.raises(ValueError, match="^invalid configured hook point$"):
        ConfiguredHookPoint(
            "point",
            EventDefinition("test.configured", 1),
            module_args=tuple(range(600)),
            module_kwargs={str(index): index for index in range(600)},
        )
    with pytest.raises(ValueError, match="^invalid configured hook point$"):
        ConfiguredHookPoint(
            "point",
            EventDefinition("test.configured", 1),
            module_args=("a" * 32_768,),
            module_kwargs={"value": "b" * 32_768},
        )


def test_prepared_configured_has_no_caller_construction_surface() -> None:
    """Only the private Runtime owner factory may issue a candidate."""
    assert not hasattr(PreparedConfigured, "_ISSUER")
    with pytest.raises(TypeError):
        PreparedConfigured(object(), object())


def test_configured_hook_point_rejects_malformed_event_definition() -> None:
    """Nested event definitions must satisfy the authoritative event contract."""
    malformed = (
        EventDefinition(["test", "configured"], 1),
        EventDefinition("test.configured", True),
        EventDefinition("test.configured", 0),
        EventDefinition("test.configured", 1, payload_limit_bytes=[]),
        EventDefinition("test.configured", 1, payload_limit_bytes=-1),
        EventDefinition("test.configured", 1, payload_limit_bytes=65_537),
    )
    for definition in malformed:
        with pytest.raises(ValueError, match="^invalid configured hook point$"):
            ConfiguredHookPoint("point", definition)


def test_configured_hook_point_owns_event_definition_snapshot() -> None:
    """A valid event definition and schema must be detached from caller state."""
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
    }
    definition = EventDefinition("test.configured", 1, schema, 1_024)
    point = ConfiguredHookPoint("point", definition)
    schema["properties"]["value"]["type"] = "integer"
    object.__setattr__(definition, "name", "test.changed")
    object.__setattr__(definition, "payload_schema", {"type": "integer"})
    assert point.definition is not definition
    assert point.definition.name == "test.configured"
    assert point.definition.major_version == 1
    assert point.definition.payload_limit_bytes == 1_024
    assert point.definition.payload_schema["properties"]["value"]["type"] == "string"


def test_configured_hooks_require_bijective_point_event_mapping() -> None:
    """Configured hook points and event identities must map one-to-one."""
    point_a_event_a = ConfiguredHookPoint(
        "point-a",
        EventDefinition("test.eventa", 1),
    )
    point_a_event_b = ConfiguredHookPoint(
        "point-a",
        EventDefinition("test.eventb", 1),
    )
    point_b_event_a = ConfiguredHookPoint(
        "point-b",
        EventDefinition("test.eventa", 1),
    )
    point_b_event_b = ConfiguredHookPoint(
        "point-b",
        EventDefinition("test.eventb", 1),
    )
    invalid_mappings = (
        (point_a_event_a, point_a_event_a),
        (point_a_event_a, point_a_event_b),
        (point_a_event_a, point_b_event_a),
    )
    for hook_points in invalid_mappings:
        with pytest.raises(ValueError, match="^invalid configured hooks$"):
            ConfiguredHooks(hook_points, HookSettings())

    configured = ConfiguredHooks(
        (point_a_event_a, point_b_event_b),
        HookSettings(),
    )
    assert configured.hook_points == (point_a_event_a, point_b_event_b)

def test_passive_configured_records_detach_collection_inputs() -> None:
    """Passive result and summary records must own immutable collection snapshots."""
    binding_ids = ["binding"]
    artifact_identities = ["a" * 64]
    module_failures = [ConfiguredModuleFailure("failed", "load_error")]
    summary = ConfiguredPlanSummary(
        "point",
        "test.configured",
        1,
        binding_ids,
        artifact_identities,
        module_failures,
    )
    binding_ids.append("changed")
    artifact_identities.append("b" * 64)
    module_failures.append(ConfiguredModuleFailure("changed", "invalid_entry"))
    assert summary.binding_ids == ("binding",)
    assert summary.artifact_identities == ("a" * 64,)
    assert summary.module_failures == (
        ConfiguredModuleFailure("failed", "load_error"),
    )

    prepare_errors = ["trust_policy_missing"]
    prepare = PrepareConfiguredResult(False, 3, errors=prepare_errors)
    prepare_errors.append("changed")
    assert prepare.errors == ("trust_policy_missing",)

    plans = [summary]
    publish_errors: list[str] = []
    publish = PublishConfiguredResult(True, 3, plans=plans, errors=publish_errors)
    plans.append(summary)
    publish_errors.append("changed")
    assert publish.plans == (summary,)
    assert publish.plans is not plans
    assert publish.plans[0] is not summary
    assert publish.errors == ()

    dispose_errors = ["cleanup_pending"]
    dispose = DisposeConfiguredResult(
        True, 3, cleanup_pending=True, errors=dispose_errors
    )
    dispose_errors.append("changed")
    assert dispose.errors == ("cleanup_pending",)


def test_passive_configured_records_reject_custom_collection_lookalikes() -> None:
    """Only explicit tuple/list compatibility inputs may cross collection boundaries."""
    invalid = UserList(["value"])
    failure = ConfiguredModuleFailure("failed", "load_error")
    summary = ConfiguredPlanSummary(
        "point", "test.configured", 1, (), (), ()
    )
    constructors = (
        lambda: ConfiguredPlanSummary("point", "test.configured", 1, invalid, (), ()),
        lambda: ConfiguredPlanSummary("point", "test.configured", 1, (), invalid, ()),
        lambda: ConfiguredPlanSummary("point", "test.configured", 1, (), (), UserList([failure])),
        lambda: PrepareConfiguredResult(False, 0, errors=invalid),
        lambda: PublishConfiguredResult(False, 0, plans=UserList([summary])),
        lambda: PublishConfiguredResult(False, 0, errors=invalid),
        lambda: DisposeConfiguredResult(False, 0, errors=invalid),
    )
    for construct in constructors:
        with pytest.raises(ValueError):
            construct()


def test_passive_configured_records_accept_tuple_controls() -> None:
    """C02 tuple inputs must remain valid after passive-record hardening."""
    failure = ConfiguredModuleFailure("failed", "invalid_entry")
    summary = ConfiguredPlanSummary(
        "point", "test.configured", 1, ("binding",), ("a" * 64,), (failure,)
    )
    assert PrepareConfiguredResult(False, 0, errors=("cancelled",)).errors == ("cancelled",)
    assert PublishConfiguredResult(True, 1, plans=(summary,)).plans == (summary,)
    assert DisposeConfiguredResult(True, 1).errors == ()



def test_configured_plan_summary_requires_canonical_artifact_identities() -> None:
    """Artifact identities must already be unique and lexicographically sorted."""
    valid = ConfiguredPlanSummary(
        "point", "test.configured", 1, (), ("a" * 64, "b" * 64)
    )
    assert valid.artifact_identities == ("a" * 64, "b" * 64)
    for invalid in (("a" * 64, "a" * 64), ("b" * 64, "a" * 64)):
        with pytest.raises(ValueError, match="^invalid configured plan summary$"):
            ConfiguredPlanSummary("point", "test.configured", 1, (), invalid)


def test_passive_results_enforce_c02_cross_field_invariants() -> None:
    """Accepted and rejected result shapes must obey the C02 lifecycle contract."""
    summary = ConfiguredPlanSummary(
        "point", "test.configured", 1, (), ("a" * 64,)
    )
    invalid_results = (
        lambda: PrepareConfiguredResult(True, 0, errors=("invalid_configuration",)),
        lambda: PrepareConfiguredResult(False, 0, errors=()),
        lambda: PrepareConfiguredResult(
            False, 0, errors=("invalid_scope", "runtime_closed")
        ),
        lambda: PublishConfiguredResult(
            False, 0, plans=(summary,), errors=("invalid_plan",)
        ),
        lambda: PublishConfiguredResult(
            False, 0, changed=True, errors=("invalid_plan",)
        ),
        lambda: PublishConfiguredResult(True, 0, errors=("invalid_plan",)),
        lambda: DisposeConfiguredResult(True, 0, errors=("invalid_scope",)),
        lambda: DisposeConfiguredResult(
            True, 0, cleanup_pending=True, errors=()
        ),
        lambda: DisposeConfiguredResult(
            False, 0, errors=("invalid_scope", "runtime_closed")
        ),
    )
    for construct in invalid_results:
        with pytest.raises(ValueError):
            construct()

    assert PrepareConfiguredResult(False, 0, errors=("invalid_scope",)).errors == (
        "invalid_scope",
    )
    assert PublishConfiguredResult(True, 1, plans=(summary,)).errors == ()
    assert PublishConfiguredResult(False, 1, errors=("invalid_plan",)).plans == ()
    cleanup = DisposeConfiguredResult(
        True, 1, cleanup_pending=True, errors=("cleanup_pending",)
    )
    assert cleanup.errors == ("cleanup_pending",)
    assert DisposeConfiguredResult(False, 1, errors=("invalid_candidate",)).errors == (
        "invalid_candidate",
    )


def test_successful_publication_requires_canonical_plan_order() -> None:
    """Successful publication summaries must be unique and sorted by hook point."""
    first = ConfiguredPlanSummary("a", "test.a", 1, (), ())
    second = ConfiguredPlanSummary("b", "test.b", 1, (), ())
    assert PublishConfiguredResult(True, 1, plans=(first, second)).plans == (first, second)
    for invalid in ((second, first), (first, first)):
        with pytest.raises(ValueError, match="^invalid configured publication result$"):
            PublishConfiguredResult(True, 1, plans=invalid)
