"""Real summary owner Script membership and isolation. Author: DawsonLin."""

import hashlib
import logging
import sys
from pathlib import Path

import pytest

from topsailai.hooks.artifact_contracts import ArtifactPythonRuntimeAuthority
from topsailai.hooks.configured_bootstrap import load_configured_trust_manifest
from topsailai.hooks.deployment_script_authorization import write_mixed_trust_manifest
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.points.context import SummaryHookAdapter
from topsailai.tests.unit.test_topsailai_hooks.test_summary_events_observer_lifecycle import (
    ACTIVE, FUNCTIONAL_SETTINGS, emit, report_evidence,
)
from tests.legacy_prepared_support import prepared_graph, build_summary_preparation_request


@pytest.fixture
def deployment(tmp_path):
    """Create explicitly reviewed fixture sources and interpreter authority offline."""
    points = tmp_path / "points"
    points.mkdir(mode=0o700)
    executable = Path(sys.executable).resolve(strict=True)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    policy = ExecutablePlatformPolicy("posix", (str(executable),))
    trace = tmp_path / "trace"
    request = build_summary_preparation_request(points_root=points, settings=FUNCTIONAL_SETTINGS,
        script_platform_policy=policy)
    for point in request.configuration.hook_points:
        point.module_folder.mkdir(parents=True, mode=0o700)
        (point.module_folder / "observer.py").write_text(
            f"def main(*, hook_context):\n    with open({str(trace)!r}, 'a') as stream:\n"
            "        stream.write(hook_context['event_name'] + ':module\\n')\n    return None\n")
    return points, policy, trace, executable, digest, tmp_path


def request_for(tree):
    """Rebuild with identical arguments for a new application lifetime."""
    return build_summary_preparation_request(points_root=tree[0], settings=FUNCTIONAL_SETTINGS,
        script_platform_policy=tree[1])


def folder_for(tree, point=ACTIVE[0]):
    """Select the fixed sibling Scripts location."""
    request = request_for(tree)
    return next(p.module_folder.parent / "scripts" for p in request.configuration.hook_points
        if p.hook_name == point.name)


def add_script(tree, name, point=ACTIVE[0]):
    """Write a real allowlisted shebang program using the result-FD protocol."""
    folder = folder_for(tree, point)
    folder.mkdir(mode=0o700, exist_ok=True)
    source = folder / name
    source.write_text(f"#!{tree[3]}\nimport json, os, struct, sys\n"
        "request = json.loads(sys.stdin.buffer.read())\n"
        "result = {key: request[key] for key in ('protocol_version', 'delivery_id', 'invocation_id', 'entry_index')}\n"
        f"with open({str(tree[2])!r}, 'a') as stream:\n    stream.write({point.name + ':' + name!r} + '\\n')\n"
        "result['value'] = None\nbody = json.dumps(result).encode()\n"
        "os.write(int(os.environ['TOPSAILAI_HOOK_RESULT_FD']), struct.pack('!I', len(body)) + body)\n")
    source.chmod(0o700)
    return source


def authorize(tree):
    """Generate a new exclusive manifest and load its deployment-pinned authority."""
    request = request_for(tree)
    output = tree[5] / ("manifest-" + str(len(tuple(tree[5].glob("manifest-*")))))
    pin = write_mixed_trust_manifest(output,
        module_folders=tuple(p.module_folder for p in request.configuration.hook_points),
        scripts=tuple(p.script for p in request.configuration.hook_points if p.script is not None),
        source_roots=(tree[0],), reviewed_deployment_sha256="a" * 64,
        python_runtime=ArtifactPythonRuntimeAuthority(tree[3], tree[4]),
        interpreter_digests=((tree[3], tree[4]),) if any(
            p.script is not None for p in request.configuration.hook_points) else ())
    trust, _ = load_configured_trust_manifest(output, pin)
    return trust


def start(tree, trust=None, request=None):
    """Compose a real owner without resetting shared production globals."""
    root = tree[5] / ("runtime-" + str(len(tuple(tree[5].glob("runtime-*")))))
    root.mkdir(mode=0o700)
    return prepared_graph(request=request_for(tree) if request is None else request,
        trust_policy=authorize(tree) if trust is None else trust, temp_root=str(root))


def deliver(tree, owner, point, identity, expected):
    """Check actual side effects, ordered terminal children, and safe cleanup."""
    before = [] if not tree[2].exists() else tree[2].read_text().splitlines()
    result = emit(SummaryHookAdapter(owner.executor), point, identity)
    report = result.report
    assert report.rejection_reason is None, report_evidence(report)
    handlers = report.unified_result.handlers
    assert [h.handler.kind for h in handlers] == ["module", "default_script_hook"]
    assert sum(h.handler.name == "hook_script" for h in handlers) == 1
    assert all(h.status == "success" and h.cleanup.state == "safe" for h in handlers)
    assert [h.handler.name for h in handlers[-1].children] == list(expected)
    assert all(h.status == "success" and h.cleanup.state == "safe" for h in handlers[-1].children)
    after = tree[2].read_text().splitlines()
    assert after[len(before):] == [point.name + ":" + name for name in ("module", *expected)]


def close(owner):
    """Require an honest settled close report for each fixture-owned lifetime."""
    result = owner.close()
    assert result.fully_closed and not result.unresolved_debts and not result.failed_stages
    assert result.scope_report is not None and result.runtime_report is not None
    assert not owner.runtime.cleanup_debts()


def remove(path):
    """Log removal of only explicitly owned fixture files/directories."""
    print(f"Deleted test-owned resource: {path}")
    if path.is_dir():
        path.rmdir()
    else:
        path.unlink()


def test_membership_restart_immutable_plan_and_stale_authority(deployment):
    """Creation/addition/removal require regenerated authority and a new owner lifetime."""
    tree = deployment
    point, sibling = ACTIVE[:2]
    owner = start(tree)
    try:
        deliver(tree, owner, point, "absent", ())
    finally:
        close(owner)
    folder = folder_for(tree)
    folder.mkdir(mode=0o700)
    owner = start(tree)
    try:
        deliver(tree, owner, point, "empty", ())
    finally:
        close(owner)
    z = add_script(tree, "z")
    old_trust = authorize(tree)
    owner = start(tree, old_trust)
    try:
        deliver(tree, owner, point, "one", ("z",))
        a = add_script(tree, "A")
        deliver(tree, owner, point, "captured-before-add", ("z",))
    finally:
        close(owner)
    stale = start(tree, old_trust)
    try:
        assert next(d for d in stale.startup_report.dispositions if d.hook_name == point.name).kind == "unavailable_preparation_failure"
        before = tree[2].read_text()
        assert emit(SummaryHookAdapter(stale.executor), point, "stale").report.rejection_reason is not None
        assert tree[2].read_text() == before
        deliver(tree, stale, sibling, "stale-sibling", ())
    finally:
        close(stale)
    owner = start(tree)
    try:
        deliver(tree, owner, point, "two", ("A", "z"))
        remove(a)
        deliver(tree, owner, point, "captured-before-remove", ("A", "z"))
    finally:
        close(owner)
    owner = start(tree)
    try:
        deliver(tree, owner, point, "removed-one", ("z",))
        deliver(tree, owner, sibling, "unchanged", ())
    finally:
        close(owner)
    remove(z)
    owner = start(tree)
    try:
        deliver(tree, owner, point, "removed-last", ())
    finally:
        close(owner)
    remove(folder)
    owner = start(tree)
    try:
        deliver(tree, owner, point, "removed-directory", ())
    finally:
        close(owner)


@pytest.mark.parametrize("fault", ["nonexecutable", "malformed", "symlink", "unauthorized", "disappeared", "explicit_missing"])
def test_complete_point_failure_and_sibling_visibility(deployment, caplog, fault):
    """Bad selected sources never publish a partial point or run business handlers."""
    tree = deployment
    point, sibling = ACTIVE[:2]
    source = add_script(tree, "z")
    trust = authorize(tree)
    request = request_for(tree)
    if fault == "nonexecutable":
        source.chmod(0o600)
    elif fault == "malformed":
        source.write_text("bad shebang\n")
    elif fault == "symlink":
        remove(source)
        source.symlink_to(tree[5] / "missing")
    elif fault == "unauthorized":
        add_script(tree, "A")
    else:
        remove(source)
        remove(source.parent)
        if fault == "explicit_missing":
            from dataclasses import replace
            from topsailai.hooks.configured_contracts import ConfiguredScript
            base = request_for(tree)
            points = tuple(replace(p, script=ConfiguredScript(source.parent, tree[1]))
                if p.hook_name == point.name else p for p in base.configuration.hook_points)
            request = replace(base, configuration=replace(base.configuration, hook_points=points))
    with caplog.at_level(logging.WARNING):
        owner = start(tree, trust, request)
    try:
        disposition = next(d for d in owner.startup_report.dispositions if d.hook_name == point.name)
        assert disposition.kind == "unavailable_preparation_failure"
        assert (point.name, disposition.kind, disposition.reason, 1) in owner.startup_report.metrics
        assert point.name in caplog.text and disposition.kind in caplog.text
        assert not tree[2].exists()
        report = emit(SummaryHookAdapter(owner.executor), point, "failed-point").report
        assert report.rejection_reason is not None and not report.outcomes
        assert not tree[2].exists()
        deliver(tree, owner, sibling, "valid-sibling", ())
    finally:
        close(owner)
