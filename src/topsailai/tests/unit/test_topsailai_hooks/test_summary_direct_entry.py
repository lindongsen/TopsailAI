"""Direct summary entry validation and real worker tests. Author: DawsonLin."""

import importlib
import json
import os

import pytest

import topsailai.hooks as hooks
from topsailai.hooks.contracts import ValidationError
from topsailai.hooks.point_entry import EntryResult, pending_cleanup
from topsailai.hooks.points.context.summary_contracts import SUMMARY_POINTS, active_summary_point
from topsailai.hooks.points.context.summary_payloads import invoke_summary_hook_point

ACTIVE = tuple(point for point in SUMMARY_POINTS if point.phase_one_eligible)
INACTIVE = tuple(point for point in SUMMARY_POINTS if not point.phase_one_eligible)


def entry(point):
    """Resolve the named public function from its point package."""
    _, domain, phase, action = point.name.split("__")
    package = importlib.import_module(f"topsailai.hooks.points.{domain}.{phase}_{action}")
    return package, getattr(package, point.name)


def arguments(point):
    """Build only approved metadata for each checkpoint."""
    result = {"operation_id": "direct-operation-1"}
    if point.outcome == "error":
        result.update(error_category="unknown", failed_stage=(
            "application_unknown" if point.is_apply_error else "generation_unknown"))
    if point.is_apply_error:
        result["partial_apply_possible"] = True
    return result


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    """Restore package configuration without discarding cleanup ownership."""
    monkeypatch.setattr(hooks, "_point_configuration", ())
    yield
    assert pending_cleanup() == ()


@pytest.mark.parametrize("point", ACTIVE, ids=lambda point: point.name)
def test_exact_detached_envelope(point, monkeypatch):
    """All eight functions preserve the generic result and pass exact JSON metadata."""
    calls = []
    expected = (EntryResult("module", "observer.py", "success"),)

    def invoke(name, **payload):
        """Capture the generic boundary without legacy executor plumbing."""
        calls.append((name, payload))
        return expected

    monkeypatch.setattr(hooks, "invoke_hook_point", invoke)
    package, call = entry(point)
    assert point.name in package.__all__
    assert call(**arguments(point)) is expected
    name, wire = calls.pop()
    assert name == point.name
    assert set(wire) == {"hook_context"}
    context = wire["hook_context"]
    assert type(context) is dict and type(context["payload"]) is dict
    assert json.loads(json.dumps(context)) == context
    expected_layer = "user2agent" if point.name.endswith("_user2agent") else "agent2llm"
    assert active_summary_point(context["event_name"]).layer == expected_layer
    assert "layer" not in context and "layer" not in context["payload"]
    assert context == {"event_name": name, "event_version": 1,
                       "operation_id": "direct-operation-1",
                       "payload": package.build_payload(**arguments(point))}
    context["payload"]["operation_id"] = "mutated"
    assert call(**arguments(point)) is expected
    assert calls[0][1]["hook_context"]["payload"]["operation_id"] == "direct-operation-1"


@pytest.mark.parametrize("point", ACTIVE, ids=lambda point: point.name)
@pytest.mark.parametrize("bad", ["identity", "extra", "stage"])
def test_reject_before_dispatch(point, bad, monkeypatch):
    """Reject invalid identity, sensitive fields and cross-layer stages before I/O."""
    calls = []
    monkeypatch.setattr(hooks, "invoke_hook_point", lambda *a, **k: calls.append((a, k)))
    _, call = entry(point)
    kwargs = arguments(point)
    if bad == "identity":
        kwargs["operation_id"] = "invalid operation"
    elif bad == "extra":
        kwargs["messages"] = ["private"]
    elif point.outcome == "error":
        kwargs["failed_stage"] = ("runtime_rebuild" if point.layer == "user2agent"
                                  else "session_write")
    else:
        kwargs["error_category"] = "unknown"
    with pytest.raises((TypeError, ValidationError)):
        call(**kwargs)
    assert calls == []


@pytest.mark.parametrize("point", INACTIVE, ids=lambda point: point.name)
def test_phase_two_has_no_direct_entry(point, monkeypatch):
    """Neither phase-two package nor shared bridge activates generation-success points."""
    _, domain, phase, action = point.name.split("__")
    package = importlib.import_module(f"topsailai.hooks.points.{domain}.{phase}_{action}")
    assert not hasattr(package, point.name)
    calls = []
    monkeypatch.setattr(hooks, "invoke_hook_point", lambda *a, **k: calls.append((a, k)))
    with pytest.raises(ValidationError):
        invoke_summary_hook_point(point.name, package.build_payload(operation_id="op-1"))
    assert calls == []


@pytest.mark.skipif(os.name != "posix", reason="Generic worker cleanup requires POSIX")
@pytest.mark.parametrize("point", ACTIVE, ids=lambda point: point.name)
def test_real_bundled_observer(point):
    """Empty explicit configuration executes each actual bundled observer in a child."""
    hooks.initialize_hook_points({})
    _, call = entry(point)
    result = call(**arguments(point))
    assert result.status == "success"
    assert result.handlers[0].handler.name == "observer.py"
    assert result.handlers[-1].handler.kind == "default_script_hook"


@pytest.mark.skipif(os.name != "posix", reason="Generic worker cleanup requires POSIX")
@pytest.mark.parametrize("point", ACTIVE, ids=lambda point: point.name)
def test_external_metadata_and_direct_script(point, tmp_path):
    """Real external Modules receive metadata; executable Scripts receive no payload."""
    trace = tmp_path / "trace"
    module = tmp_path / "a_external.py"
    module.write_text(
        "import json\nfrom pathlib import Path\n"
        "def main(*, hook_context):\n"
        f"    Path({str(trace)!r}).write_text(json.dumps(hook_context) + '\\n')\n")
    script = tmp_path / "z_script"
    script.write_text(f"#!/bin/sh\n[ \"$#\" -eq 0 ] || exit 8\n"
                      f"[ -z \"$(cat)\" ] || exit 9\nprintf 'script' >> '{trace}'\n")
    script.chmod(0o755)
    hooks.initialize_hook_points({point.name: {"modules": str(module), "scripts": str(script)}})
    package, call = entry(point)
    result = call(**arguments(point))
    assert result.status == "success"
    assert [item.handler.name for item in result.handlers] == [
        "a_external.py", "observer.py", "hook_script"]
    assert result.handlers[-1].children[0].handler.name == "z_script"
    data, marker = trace.read_text().splitlines()
    context = json.loads(data)
    assert set(context) == {"event_name", "event_version", "operation_id", "payload"}
    assert context["event_name"] == point.name
    expected_layer = "user2agent" if point.name.endswith("_user2agent") else "agent2llm"
    assert active_summary_point(context["event_name"]).layer == expected_layer
    assert context["event_version"] == 1
    assert context["operation_id"] == "direct-operation-1"
    assert "layer" not in context["payload"]
    assert context["payload"] == package.build_payload(**arguments(point))
    assert marker == "script"
