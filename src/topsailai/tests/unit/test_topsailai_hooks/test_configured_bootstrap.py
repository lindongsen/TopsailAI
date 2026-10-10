"""Tests for configured Hook bootstrap and trust-manifest loading."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from topsailai.hooks.configured_bootstrap import (
    ConfiguredHookBootstrap,
    load_configured_hook_bootstrap,
)


def _write_json(path: Path, value: object) -> str:
    """Write deterministic JSON and return its SHA-256 digest."""
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _manifest(root: Path) -> dict[str, object]:
    """Return one valid empty deployment trust manifest."""
    return {
        "schema_version": 1,
        "source_roots": [str(root)],
        "allowed_interpreters": [],
        "allow_native_scripts": False,
        "closure_assertions": [],
        "python_runtime": None,
    }


def test_disabled_bootstrap_performs_no_file_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disabled configuration must not inspect configured files."""
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("unexpected I/O"))
    bootstrap = load_configured_hook_bootstrap({})
    assert bootstrap == ConfiguredHookBootstrap.disabled()


def test_bootstrap_loads_versioned_config_and_pinned_manifest(tmp_path: Path) -> None:
    """Enabled environment values must produce one immutable typed snapshot."""
    config_path = tmp_path / "hooks.json"
    manifest_path = tmp_path / "trust.json"
    _write_json(config_path, {"schema_version": 1, "hooks": {}})
    digest = _write_json(manifest_path, _manifest(tmp_path))
    environment = {
        "TOPSAILAI_CONFIGURED_HOOKS_ENABLED": "1",
        "TOPSAILAI_CONFIGURED_HOOKS_CONFIG": str(config_path),
        "TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST": str(manifest_path),
        "TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST_SHA256": digest,
        "TOPSAILAI_CONFIGURED_HOOKS_REGISTRATION_MODE": "lazy",
        "TOPSAILAI_CONFIGURED_HOOKS_STARTUP_POLICY": "disable",
    }
    bootstrap = load_configured_hook_bootstrap(environment)
    environment["TOPSAILAI_CONFIGURED_HOOKS_REGISTRATION_MODE"] = "startup"
    assert bootstrap.enabled is True
    assert bootstrap.registration_mode == "lazy"
    assert bootstrap.startup_policy == "disable"
    assert bootstrap.configuration_generation == 1
    assert bootstrap.trust.source_roots == (tmp_path,)
    assert bootstrap.hooks == ()


def test_bootstrap_rejects_digest_mismatch_and_unknown_fields(tmp_path: Path) -> None:
    """Manifest authority and both versioned boundaries must fail closed."""
    config_path = tmp_path / "hooks.json"
    manifest_path = tmp_path / "trust.json"
    _write_json(config_path, {"schema_version": 1, "hooks": {}})
    digest = _write_json(manifest_path, _manifest(tmp_path))
    base = {
        "TOPSAILAI_CONFIGURED_HOOKS_ENABLED": "1",
        "TOPSAILAI_CONFIGURED_HOOKS_CONFIG": str(config_path),
        "TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST": str(manifest_path),
        "TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST_SHA256": "0" * 64,
    }
    with pytest.raises(ValueError, match="trust manifest digest mismatch"):
        load_configured_hook_bootstrap(base)
    manifest = _manifest(tmp_path)
    manifest["unknown"] = True
    digest = _write_json(manifest_path, manifest)
    base["TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST_SHA256"] = digest
    with pytest.raises(ValueError, match="invalid configured trust manifest"):
        load_configured_hook_bootstrap(base)


def test_manifest_decodes_exact_closure_authority(tmp_path: Path) -> None:
    """Manifest assertions must become validated detached trust records."""
    source = tmp_path / "hook.py"
    manifest_path = tmp_path / "trust.json"
    config_path = tmp_path / "hooks.json"
    _write_json(config_path, {"schema_version": 1, "hooks": {}})
    manifest = _manifest(tmp_path)
    manifest["closure_assertions"] = [{
        "source_path": str(source),
        "kind": "python_source",
        "logical_name": "hook",
        "content_sha256": "1" * 64,
        "runtime_sha256": "2" * 64,
        "deployment_sha256": "3" * 64,
        "closure": "single-file-trusted-runtime-v1",
    }]
    digest = _write_json(manifest_path, manifest)
    bootstrap = load_configured_hook_bootstrap({
        "TOPSAILAI_CONFIGURED_HOOKS_ENABLED": "1",
        "TOPSAILAI_CONFIGURED_HOOKS_CONFIG": str(config_path),
        "TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST": str(manifest_path),
        "TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST_SHA256": digest,
    })
    assertion = bootstrap.trust.closure_assertions[0]
    assert assertion.source_path == source
    assert assertion.content_sha256 == "1" * 64


def test_enabled_bootstrap_requires_absolute_paths_and_valid_modes(tmp_path: Path) -> None:
    """The application boundary must reject ambiguous location and policy values."""
    base = {
        "TOPSAILAI_CONFIGURED_HOOKS_ENABLED": "1",
        "TOPSAILAI_CONFIGURED_HOOKS_CONFIG": "relative.json",
        "TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST": str(tmp_path / "trust.json"),
        "TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST_SHA256": "0" * 64,
    }
    with pytest.raises(ValueError, match="invalid configured Hook bootstrap"):
        load_configured_hook_bootstrap(base)
    base["TOPSAILAI_CONFIGURED_HOOKS_CONFIG"] = str(tmp_path / "hooks.json")
    base["TOPSAILAI_CONFIGURED_HOOKS_REGISTRATION_MODE"] = "sometimes"
    with pytest.raises(ValueError, match="invalid configured Hook bootstrap"):
        load_configured_hook_bootstrap(base)


def _environment(config_path: Path, manifest_path: Path, digest: str) -> dict[str, str]:
    """Return one enabled application-boundary environment snapshot."""
    return {
        "TOPSAILAI_CONFIGURED_HOOKS_ENABLED": "1",
        "TOPSAILAI_CONFIGURED_HOOKS_CONFIG": str(config_path),
        "TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST": str(manifest_path),
        "TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST_SHA256": digest,
    }


def test_public_manifest_loader_returns_policy_and_verified_identity(tmp_path: Path) -> None:
    """The public loader must return only authority pinned by the caller digest."""
    from topsailai.hooks.configured_bootstrap import load_configured_trust_manifest

    manifest_path = tmp_path / "trust.json"
    digest = _write_json(manifest_path, _manifest(tmp_path))

    trust, identity = load_configured_trust_manifest(manifest_path, digest)

    assert identity == digest
    assert trust.source_roots == (tmp_path,)
    with pytest.raises(ValueError, match="invalid configured trust manifest"):
        load_configured_trust_manifest(Path("relative.json"), digest)


def test_bootstrap_loads_script_and_folder_bindings(tmp_path: Path) -> None:
    """Configuration must preserve explicit order and exact source selection."""
    config_path = tmp_path / "hooks.json"
    manifest_path = tmp_path / "trust.json"
    _write_json(config_path, {
        "schema_version": 1,
        "hooks": {
            "hook_folder": {"folder": "folder"},
            "hook_scripts": {
                "enabled": False,
                "scripts": ["02.py", "01.py"],
            },
        },
    })
    digest = _write_json(manifest_path, _manifest(tmp_path))

    bootstrap = load_configured_hook_bootstrap(
        _environment(config_path, manifest_path, digest)
    )

    assert [binding.hook_name for binding in bootstrap.hooks] == [
        "hook_folder", "hook_scripts",
    ]
    assert bootstrap.hooks[0].folder == tmp_path / "folder"
    assert bootstrap.hooks[1].scripts == (
        tmp_path / "02.py", tmp_path / "01.py",
    )
    assert bootstrap.hooks[1].enabled is False


def test_configuration_rejects_ambiguous_or_unsafe_sources(tmp_path: Path) -> None:
    """Relative configured paths must have one unambiguous trusted root."""
    config_path = tmp_path / "hooks.json"
    manifest_path = tmp_path / "trust.json"
    digest = _write_json(manifest_path, _manifest(tmp_path))
    invalid_hooks = [
        {"hook_a": {"scripts": [], "folder": "folder"}},
        {"hook_a": {"scripts": []}},
        {"hook_a": {"scripts": ["../escape.py"]}},
        {"hook_a": {"folder": "/absolute"}},
        {"hook_a": {"folder": "folder", "unknown": True}},
        {"invalid": {"folder": "folder"}},
    ]
    for hooks in invalid_hooks:
        _write_json(config_path, {"schema_version": 1, "hooks": hooks})
        with pytest.raises(ValueError, match="invalid configured Hook configuration"):
            load_configured_hook_bootstrap(
                _environment(config_path, manifest_path, digest)
            )

    manifest = _manifest(tmp_path)
    manifest["source_roots"] = [str(tmp_path), str(tmp_path / "other")]
    digest = _write_json(manifest_path, manifest)
    _write_json(config_path, {
        "schema_version": 1,
        "hooks": {"hook_a": {"folder": "folder"}},
    })
    with pytest.raises(ValueError, match="invalid configured Hook configuration"):
        load_configured_hook_bootstrap(
            _environment(config_path, manifest_path, digest)
        )


def test_manifest_rejects_malformed_authority_records(tmp_path: Path) -> None:
    """Every trust record must pass its exact versioned schema and budget."""
    config_path = tmp_path / "hooks.json"
    manifest_path = tmp_path / "trust.json"
    _write_json(config_path, {"schema_version": 1, "hooks": {}})
    malformed = []
    wrong_version = _manifest(tmp_path)
    wrong_version["schema_version"] = 2
    malformed.append(wrong_version)
    duplicate_roots = _manifest(tmp_path)
    duplicate_roots["source_roots"] = [str(tmp_path), str(tmp_path)]
    malformed.append(duplicate_roots)
    invalid_native = _manifest(tmp_path)
    invalid_native["allow_native_scripts"] = "yes"
    malformed.append(invalid_native)
    invalid_assertion = _manifest(tmp_path)
    invalid_assertion["closure_assertions"] = [{"source_path": str(tmp_path / "x.py")}]
    malformed.append(invalid_assertion)
    invalid_runtime = _manifest(tmp_path)
    invalid_runtime["python_runtime"] = {"executable": str(tmp_path / "python")}
    malformed.append(invalid_runtime)

    for manifest in malformed:
        digest = _write_json(manifest_path, manifest)
        with pytest.raises(ValueError, match="invalid configured trust manifest"):
            load_configured_hook_bootstrap(
                _environment(config_path, manifest_path, digest)
            )


def test_manifest_decodes_python_runtime_and_rejects_oversized_files(tmp_path: Path) -> None:
    """Runtime authority is detached and bounded document reads detect overflow."""
    config_path = tmp_path / "hooks.json"
    manifest_path = tmp_path / "trust.json"
    _write_json(config_path, {"schema_version": 1, "hooks": {}})
    manifest = _manifest(tmp_path)
    manifest["python_runtime"] = {
        "executable": str(tmp_path / "python"),
        "content_sha256": "4" * 64,
        "bootstrap": "cpython-executable-v1",
    }
    digest = _write_json(manifest_path, manifest)

    bootstrap = load_configured_hook_bootstrap(
        _environment(config_path, manifest_path, digest)
    )
    assert bootstrap.trust.python_runtime.executable == tmp_path / "python"

    config_path.write_bytes(b"{" + b" " * 1_048_576)
    with pytest.raises(ValueError, match="invalid configured Hook configuration"):
        load_configured_hook_bootstrap(
            _environment(config_path, manifest_path, digest)
        )


def test_bootstrap_constructors_reject_inconsistent_snapshots(tmp_path: Path) -> None:
    """Typed boundary records must not admit contradictory caller-created state."""
    from topsailai.hooks.configured_bootstrap import ConfiguredHookBinding

    with pytest.raises(ValueError, match="invalid configured Hook configuration"):
        ConfiguredHookBinding("hook_a")
    with pytest.raises(ValueError, match="invalid configured Hook configuration"):
        ConfiguredHookBinding(
            "hook_a", scripts=(tmp_path / "a.py",), folder=tmp_path,
        )
    with pytest.raises(ValueError, match="invalid configured Hook bootstrap"):
        ConfiguredHookBootstrap(True)
    with pytest.raises(ValueError, match="invalid configured Hook bootstrap"):
        ConfiguredHookBootstrap(False, hooks=(
            ConfiguredHookBinding("hook_a", folder=tmp_path),
        ))
    with pytest.raises(ValueError, match="invalid configured Hook bootstrap"):
        load_configured_hook_bootstrap({"TOPSAILAI_CONFIGURED_HOOKS_ENABLED": "yes"})
    with pytest.raises(ValueError, match="invalid configured Hook bootstrap"):
        load_configured_hook_bootstrap({1: "value"})


def test_bootstrap_strict_boundary_rejects_malformed_documents_and_paths(tmp_path: Path) -> None:
    """Malformed JSON, missing files, unsafe records, and invalid snapshots fail closed."""
    from topsailai.hooks.configured_bootstrap import (
        ConfiguredHookBinding,
        load_configured_trust_manifest,
    )

    with pytest.raises(ValueError, match="invalid configured Hook configuration"):
        ConfiguredHookBinding("hook_a", scripts=(Path("relative.py"),))
    with pytest.raises(ValueError, match="invalid configured Hook bootstrap"):
        ConfiguredHookBootstrap(False, registration_mode="other")
    with pytest.raises(ValueError, match="invalid configured Hook bootstrap"):
        ConfiguredHookBootstrap(False, startup_policy="other")
    with pytest.raises(ValueError, match="invalid configured Hook bootstrap"):
        ConfiguredHookBootstrap(False, configuration_generation=0)
    with pytest.raises(ValueError, match="invalid configured Hook bootstrap"):
        ConfiguredHookBootstrap(False, hooks=[])

    missing = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="invalid configured trust manifest"):
        load_configured_trust_manifest(missing, "a" * 64)

    malformed = tmp_path / "malformed.json"
    malformed.write_bytes(b"\xff")
    digest = hashlib.sha256(malformed.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="invalid configured trust manifest"):
        load_configured_trust_manifest(malformed, digest)

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    digest = hashlib.sha256(array.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="invalid configured trust manifest"):
        load_configured_trust_manifest(array, digest)


def test_configured_source_rejects_real_nul_character(tmp_path: Path) -> None:
    """A real NUL in a configured relative source must fail at the config boundary."""
    config_path = tmp_path / "hooks.json"
    manifest_path = tmp_path / "trust.json"
    _write_json(
        config_path,
        {"schema_version": 1, "hooks": {"hook_a": {"folder": "bad\u0000path"}}},
    )
    digest = _write_json(manifest_path, _manifest(tmp_path))

    with pytest.raises(ValueError, match="invalid configured Hook configuration"):
        load_configured_hook_bootstrap(
            _environment(config_path, manifest_path, digest)
        )


def test_bootstrap_rejects_additional_strict_shape_variants(tmp_path: Path) -> None:
    """All nested config and trust record types must match the versioned schema."""
    from topsailai.hooks.configured_bootstrap import ConfiguredHookBinding

    with pytest.raises(ValueError, match="invalid configured Hook configuration"):
        ConfiguredHookBinding(
            "hook_a", scripts=(tmp_path / "a.py", tmp_path / "a.py")
        )
    with pytest.raises(ValueError, match="invalid configured Hook bootstrap"):
        ConfiguredHookBootstrap(enabled=1)
    duplicate = ConfiguredHookBinding("hook_a", folder=tmp_path)
    with pytest.raises(ValueError, match="invalid configured Hook bootstrap"):
        ConfiguredHookBootstrap(False, hooks=(duplicate, duplicate))

    config_path = tmp_path / "hooks.json"
    manifest_path = tmp_path / "trust.json"
    digest = _write_json(manifest_path, _manifest(tmp_path))
    invalid_configs = (
        {"schema_version": 2, "hooks": {}},
        {"schema_version": 1, "hooks": {"hook_a": []}},
        {"schema_version": 1, "hooks": {"hook_a": {"folder": 1}}},
        {"schema_version": 1, "hooks": {"hook_a": {"folder": ""}}},
    )
    for value in invalid_configs:
        _write_json(config_path, value)
        with pytest.raises(ValueError, match="invalid configured Hook configuration"):
            load_configured_hook_bootstrap(
                _environment(config_path, manifest_path, digest)
            )

    invalid_manifests = (
        {**_manifest(tmp_path), "closure_assertions": ["invalid"]},
        {**_manifest(tmp_path), "python_runtime": "invalid"},
        {**_manifest(tmp_path), "source_roots": [1]},
        {**_manifest(tmp_path), "source_roots": [str(tmp_path)] * 33},
    )
    _write_json(config_path, {"schema_version": 1, "hooks": {}})
    for value in invalid_manifests:
        digest = _write_json(manifest_path, value)
        with pytest.raises(ValueError, match="invalid configured trust manifest"):
            load_configured_hook_bootstrap(
                _environment(config_path, manifest_path, digest)
            )
