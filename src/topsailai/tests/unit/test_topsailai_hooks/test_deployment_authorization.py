"""Offline generated trust exercised by real restart workers. Author: DawsonLin."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from topsailai.hooks.artifact_contracts import ArtifactPythonRuntimeAuthority
from topsailai.hooks.configured_bootstrap import load_configured_trust_manifest
from topsailai.hooks.deployment_authorization import generate_module_trust_manifest, main
from topsailai.tests.unit.test_topsailai_hooks.test_summary_module_directories import tree, members
from topsailai.tests.unit.test_topsailai_hooks.test_summary_events_observer_lifecycle import ACTIVE, emit
from topsailai.hooks.points.context import SummaryHookAdapter
from tests.legacy_prepared_support import prepared_graph


@pytest.fixture
def authority():
    """Supply explicit test-deployment reviewed runtime authority, not production review."""
    executable = Path(sys.executable).resolve(strict=True)
    return ArtifactPythonRuntimeAuthority(executable, hashlib.sha256(executable.read_bytes()).hexdigest())


def generate(tree, authority, **overrides):
    """Reuse unchanged point directory configuration, never list Module members."""
    options = dict(module_folders=tuple(p.module_folder for p in tree[1].configuration.hook_points),
        source_roots=(tree[0],), reviewed_deployment_sha256="a" * 64, python_runtime=authority)
    options.update(overrides)
    return generate_module_trust_manifest(**options)


def load(tree, manifest, digest):
    """Load through the production pinned manifest loader."""
    path = tree[2] / "manifest.json"
    path.write_bytes(manifest)
    return load_configured_trust_manifest(path, digest)[0]


def start(tree, trust):
    """Create a new application lifetime from externally generated pinned trust."""
    root = tree[2] / "runtime"
    root.mkdir(mode=0o700, exist_ok=True)
    return prepared_graph(request=tree[1], trust_policy=trust, temp_root=str(root))


def test_generated_authority_add_remove_restart(tree, authority):
    """Only files, deployment regeneration and restart change actual point membership."""
    request = tree[1]
    point, sibling = ACTIVE[:2]
    folder = request.configuration.hook_points[0].module_folder
    manifest, digest = generate(tree, authority)
    owner = start(tree, load(tree, manifest, digest))
    added = folder / "alpha.py"
    try:
        assert members(owner, point, "initial") == ("zeta",)
        added.write_text('def main(*, hook_context):\n    return {"point": hook_context["event_name"], "member": "alpha"}\n')
        assert members(owner, point, "captured") == ("zeta",)
    finally:
        assert owner.close().fully_closed
    manifest, digest = generate(tree, authority)
    assert all(item["deployment_sha256"] == "a" * 64 for item in json.loads(manifest)["closure_assertions"])
    owner = start(tree, load(tree, manifest, digest))
    try:
        assert members(owner, point, "added") == ("alpha", "zeta")
        assert members(owner, sibling, "isolated") == ("zeta",)
    finally:
        assert owner.close().fully_closed
    print(f"Deleted test-owned Module: {added}")
    added.unlink()
    manifest, digest = generate(tree, authority)
    assert str(added) not in {item["source_path"] for item in json.loads(manifest)["closure_assertions"]}
    owner = start(tree, load(tree, manifest, digest))
    try:
        assert members(owner, point, "removed") == ("zeta",)
        assert tree[1] is request
    finally:
        assert owner.close().fully_closed


@pytest.mark.parametrize("change", ["new", "stale", "missing"])
def test_stale_or_missing_authority_has_no_partial_execution(tree, authority, change):
    """Pinned but incomplete/stale authority disables the whole point, not its sibling."""
    point, sibling = ACTIVE[:2]
    folder = tree[1].configuration.hook_points[0].module_folder
    marker = tree[2] / "forbidden-handler-execution"
    original = (folder / "zeta.py").read_text()
    (folder / "zeta.py").write_text("from pathlib import Path\n" + original.replace(
        "    return", f"    Path({str(marker)!r}).write_text('executed')\n    return"))
    manifest, digest = generate(tree, authority)
    if change == "new":
        (folder / "extra.py").write_text(f"from pathlib import Path\ndef main(*, hook_context):\n    Path({str(marker)!r}).write_text('unauthorized')\n")
    elif change == "stale":
        (folder / "zeta.py").write_text((folder / "zeta.py").read_text() + "# stale deployment bytes\n")
    else:
        document = json.loads(manifest)
        document["closure_assertions"] = [a for a in document["closure_assertions"]
            if a["source_path"] != str(folder / "zeta.py")]
        manifest = json.dumps(document).encode()
        digest = hashlib.sha256(manifest).hexdigest()
    owner = start(tree, load(tree, manifest, digest))
    try:
        dispositions = {item.hook_name: item.kind for item in owner.startup_report.dispositions}
        assert dispositions[point.name] == "unavailable_preparation_failure"
        result = emit(SummaryHookAdapter(owner.executor), point, "unavailable")
        assert result.report.rejection_reason is not None
        assert not result.report.outcomes
        assert not marker.exists()
        assert members(owner, sibling, "sibling") == ("zeta",)
    finally:
        assert owner.close().fully_closed


def test_manifest_pin_missing_malformed_and_mismatch(tree, authority):
    """Neither missing documents nor altered bytes are accepted as valid trust."""
    manifest, digest = generate(tree, authority)
    with pytest.raises(ValueError):
        load_configured_trust_manifest(tree[2] / "absent.json", digest)
    with pytest.raises(ValueError):
        load(tree, manifest, "b" * 64)
    with pytest.raises(ValueError):
        load(tree, b"{}", hashlib.sha256(b"{}").hexdigest())


@pytest.mark.parametrize("override", [
    {"reviewed_deployment_sha256": ""}, {"python_runtime": None},
    {"module_folders": (Path("relative"),)},
])
def test_explicit_review_inputs_required(tree, authority, override):
    """Generation cannot silently infer review authority or source configuration."""
    with pytest.raises(ValueError):
        generate(tree, authority, **override)


def test_runtime_authority_mismatch(tree, authority):
    """A supplied runtime digest is verified, not rewritten to authorize observed bytes."""
    bad = ArtifactPythonRuntimeAuthority(authority.executable, "b" * 64)
    with pytest.raises(ValueError, match="digest mismatch"):
        generate(tree, authority, python_runtime=bad)


def test_cli_emits_manifest_pin_without_overwrite(tree, authority, capsys):
    """The offline command outputs a public-loadable manifest and refuses replacement."""
    output = tree[2] / "offline.json"
    args = ["--source-root", str(tree[0]), "--reviewed-deployment-sha256", "a" * 64,
        "--python-executable", str(authority.executable), "--python-sha256", authority.content_sha256,
        "--output", str(output)]
    for point in tree[1].configuration.hook_points:
        args.extend(["--module-folder", str(point.module_folder)])
    assert main(args) == 0
    digest = capsys.readouterr().out.strip()
    assert load_configured_trust_manifest(output, digest)[1] == digest
    original = output.read_bytes()
    assert main(args) == 1
    assert output.read_bytes() == original


@pytest.mark.parametrize("case", ["empty", "duplicate", "outside", "missing", "symlink"])
def test_directory_admission(tree, authority, case):
    """Offline generation rejects invalid roots instead of authorizing an empty fallback."""
    folder = tree[1].configuration.hook_points[0].module_folder
    folders = {"empty": (), "duplicate": (folder, folder),
        "outside": (tree[2],), "missing": (tree[0] / "absent",)}
    if case == "symlink":
        alias = tree[0] / "alias"
        alias.symlink_to(folder, target_is_directory=True)
        folders[case] = (alias,)
    with pytest.raises((ValueError, OSError)):
        generate(tree, authority, module_folders=folders[case])


def test_empty_directory_manifest_round_trip(tree, authority):
    """Removing the last file produces valid empty-point authority, not a failed plan."""
    folder = tree[1].configuration.hook_points[0].module_folder
    source = folder / "zeta.py"
    print(f"Deleted test-owned Module: {source}")
    source.unlink()
    manifest, digest = generate(tree, authority)
    owner = start(tree, load(tree, manifest, digest))
    try:
        assert members(owner, ACTIVE[0], "empty") == ()
    finally:
        assert owner.close().fully_closed


def test_generator_never_imports_candidates(tree, authority):
    """Generation hashes bytes without executing a candidate's top-level code."""
    folder = tree[1].configuration.hook_points[0].module_folder
    (folder / "raises.py").write_text('raise RuntimeError("must not import")\n')
    manifest, digest = generate(tree, authority)
    assert len(load(tree, manifest, digest).closure_assertions) == 9


def test_bounded_generation(tree, authority, monkeypatch):
    """Oversized source and output fail before deployment publication."""
    import topsailai.hooks.deployment_authorization as generator
    monkeypatch.setattr(generator, "_MAX_MANIFEST_BYTES", 10)
    with pytest.raises(ValueError, match="size limit"):
        generate(tree, authority)
    monkeypatch.setattr(generator, "_MAX_FILE_BYTES", 1)
    with pytest.raises(ValueError, match="source"):
        generate(tree, authority)


def test_failed_cli_does_not_publish(tree, capsys):
    """Invalid explicit authority cannot create output or print a deployment pin."""
    output = tree[2] / "invalid.json"
    assert main(["--module-folder", str(tree[0]), "--source-root", str(tree[0]),
        "--reviewed-deployment-sha256", "invalid", "--python-executable", str(tree[0]),
        "--python-sha256", "invalid", "--output", str(output)]) == 1
    assert not output.exists()
    assert not capsys.readouterr().out
