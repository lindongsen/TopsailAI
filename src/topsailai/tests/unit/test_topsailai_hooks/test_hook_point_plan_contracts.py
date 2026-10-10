"""Unpublished complete candidate semantic contracts. Author: DawsonLin."""
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from topsailai.hooks.contracts import ValidationError
from topsailai.hooks.module_invocation_protocol import ModuleInvocation


def api():
    """Require the additive contract within each RED test body."""
    from topsailai.hooks import hook_point_plan_contracts as contracts
    return contracts


def source(name="A", **kwargs):
    """Construct one valid explicit Module source."""
    values = dict(registered_name=name, source_path=Path("/trusted/plugin.py"),
        logical_name="plugin", kind="python_source", handler_ref="plugin:main")
    values.update(kwargs)
    return api().ModuleSource(**values)


def test_invocation_detachment_and_alias():
    """Preserve arbitrary aliases and detach nested caller arguments."""
    c = api()
    args, kwargs = [{"nested": [1]}], {"key": [2]}
    invocation = ModuleInvocation(args, kwargs)
    item = source("", invocation=invocation)
    args[0]["nested"].append(3)
    kwargs["key"].append(4)
    assert item.registered_name == ""
    assert tuple(item.invocation.args[0]["nested"]) == (1,)
    assert tuple(item.invocation.kwargs["key"]) == (2,)
    with pytest.raises((TypeError, FrozenInstanceError)):
        item.invocation.kwargs["key"] = ()
    with pytest.raises(FrozenInstanceError):
        item.registered_name = "changed"
    assert c.ModuleSource.__dataclass_params__.frozen


@pytest.mark.parametrize("change", [
    {"kind": "script"}, {"handler_ref": "/plugin.py:main"},
    {"handler_ref": "plugin:other"}, {"logical_name": "bad-name"},
    {"source_path": Path("relative.py")}, {"registered_name": 3},
    {"registered_name": "\ud800"}, {"enabled": 1}, {"invocation": {}},
])
def test_malformed_source_rejected(change):
    """Reject malformed sources before capture allocation."""
    c = api()
    values = dict(registered_name="A", source_path=Path("/trusted/plugin.py"),
        logical_name="plugin", kind="python_source", handler_ref="plugin:main")
    values.update(change)
    with pytest.raises(ValidationError):
        c.ModuleSource(**values)


def test_empty_plan_has_exact_terminal_and_schema():
    """Require one default even without physical inventory."""
    c = api()
    plan = c.HookPointPlan("point", (), c.DefaultScriptHook(()))
    assert plan.default_script_hook.identity.name == "hook_script"
    assert plan.default_script_hook.identity.kind == "default_script_hook"
    assert plan.modules == () and len(plan.handlers) == 1
    assert len(plan.fingerprint) == 64
    for change in ({"schema_version": True}, {"hook_point_name": ""},
                   {"modules": [object()]}, {"default_script_hook": object()}):
        values = dict(hook_point_name="point", modules=(), default_script_hook=c.DefaultScriptHook(()))
        values.update(change)
        with pytest.raises(ValidationError):
            c.HookPointPlan(**values)


def captured(kind="script", index=0, name="A"):
    """Make structural-only records, never claim filesystem admission."""
    from topsailai.hooks.result_contracts import HandlerIdentity
    c = api()
    common = dict(identity=HandlerIdentity(kind + str(index), name, kind),
        artifact_identity="a" * 64, inventory_index=index,
        relative_path=f"entry-{index:06d}/plugin.py", captured_path=Path(f"/sealed/entry-{index:06d}/plugin.py"),
        content_sha256="b" * 64, deployment_sha256="c" * 64)
    if kind == "module":
        return c.CapturedModule(source=source(name), **common)
    return c.CapturedScript(source_path=Path("/trusted/plugin.py"), logical_name="plugin.py", **common)


@pytest.mark.parametrize("change", [
    {"inventory_index": True}, {"artifact_identity": "bad"}, {"content_sha256": "z" * 64},
    {"source_path": "/trusted/plugin.py"}, {"relative_path": "../plugin.py"},
    {"captured_path": Path("/sealed/wrong/plugin.py")}, {"logical_name": "wrong"},
])
def test_captured_script_boundaries(change):
    """Reject incoherent index, source, digest and locator records."""
    from dataclasses import replace
    with pytest.raises(ValidationError):
        replace(captured(), **change)


@pytest.mark.parametrize("change", [{"source": None}, {"identity": None}])
def test_captured_module_boundaries(change):
    """Reject invalid nested Module records before dependent access."""
    from dataclasses import replace
    with pytest.raises(ValidationError):
        replace(captured("module"), **change)


def test_module_alias_and_script_container_correlation():
    """Require exact aliases, kind and bounded collection members."""
    from dataclasses import replace
    from topsailai.hooks.result_contracts import HandlerIdentity
    c = api()
    with pytest.raises(ValidationError):
        replace(captured("module"), identity=HandlerIdentity("M", "other", "module"))
    for scripts in (None, [None], [captured()] * 129, (captured(), captured())):
        with pytest.raises(ValidationError):
            c.DefaultScriptHook(scripts)
    with pytest.raises(ValidationError):
        c.DefaultScriptHook((), configured=1)
    with pytest.raises(ValidationError):
        c.DefaultScriptHook((), identity=HandlerIdentity("other", "hook_script", "default_script_hook"))
    with pytest.raises(ValidationError):
        source("A", handler_ref="other:main")
    with pytest.raises(ValidationError):
        source("é" * 32768)


@pytest.mark.parametrize("values", [
    {"argv": None}, {"argv": [None]}, {"cwd": Path("relative")},
    {"environment": None}, {"environment": [["one"]]},
    {"environment": [["BAD=KEY", "value"]]},
    {"environment": [["KEY", "a"], ["KEY", "b"]]},
])
def test_execution_options_boundaries(values):
    """Validate supported mutable containers before deeply detaching them."""
    from topsailai.hooks.hook_script_contracts import HookScriptExecutionOptions
    c = api()
    with pytest.raises(ValidationError):
        c.HookPointPlan("point", (), c.DefaultScriptHook(()), options=HookScriptExecutionOptions(**values))


def test_plan_correlation_and_configuration_boundaries():
    """Reject cross-record index, identity, source and artifact confusion."""
    from dataclasses import replace
    from topsailai.hooks.hook_script_contracts import HookScriptExecutionPolicy
    from topsailai.hooks.result_contracts import HandlerIdentity
    c = api()
    first = captured("module")
    base = c.HookPointPlan("point", (first,), c.DefaultScriptHook(()))
    for change in ({"options": None}, {"execution_policy": HookScriptExecutionPolicy(max_entries=0)},
                   {"platform_policy": None}):
        with pytest.raises(ValidationError):
            replace(base, **change)
    second_source = c.ModuleSource("B", Path("/trusted/second/plugin.py"), "plugin", "python_source", "plugin:main")
    second = replace(first, identity=HandlerIdentity("M2", "B", "module"), source=second_source,
        inventory_index=1, relative_path="entry-000001/plugin.py", captured_path=Path("/sealed/entry-000001/plugin.py"))
    for item in (replace(second, artifact_identity="d" * 64),
                 replace(second, captured_path=Path("/different/entry-000001/plugin.py")),
                 replace(second, source=replace(second_source, source_path=first.source_path)),
                 replace(second, identity=HandlerIdentity(first.identity.id, "B", "module")),
                 replace(second, inventory_index=2, relative_path="entry-000002/plugin.py", captured_path=Path("/sealed/entry-000002/plugin.py"))):
        with pytest.raises(ValidationError):
            replace(base, modules=(first, item))
    with pytest.raises(ValidationError):
        replace(base, modules=(first, second), capture_policy=__import__("topsailai.hooks.artifact_contracts", fromlist=["ArtifactCapturePolicy"]).ArtifactCapturePolicy(max_entries=1))
    assert replace(base, modules=[first]).modules == (first,)
