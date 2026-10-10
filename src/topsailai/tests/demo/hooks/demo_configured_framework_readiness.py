"""Demonstrate manifest-pinned startup registration through the public facade."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from topsailai.hooks import (
    ConfiguredHookExecutor,
    ConfiguredHookRegistrar,
    EventDefinition,
    HookLimits,
    HookPointCatalog,
    HookPointDeclaration,
    HookRuntime,
    HookSettings,
    load_configured_hook_bootstrap,
)
from topsailai.hooks.artifact_identity import shebang_runtime_fingerprint


def _write_json(path: Path, value: object) -> str:
    """Write deterministic deployment data and return its SHA-256 identity."""
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _write_protocol_script(path: Path) -> None:
    """Write one self-contained configured script implementing the worker protocol."""
    path.write_text(
        f'''#!{Path(sys.executable).resolve()}
import json
import os
import pathlib
import struct
import sys
message = json.loads(sys.stdin.buffer.read().decode("utf-8"))
pathlib.Path(message["context"]["event"]["payload"]["evidence_file"]).write_text(str(os.getpid()), encoding="utf-8")
result = {{
    "protocol_version": 1,
    "delivery_id": message["delivery_id"],
    "invocation_id": message["invocation_id"],
    "entry_index": message["entry_index"],
    "value": {{"message": message["context"]["event"]["payload"]["message"], "worker_pid": os.getpid()}},
}}
encoded = json.dumps(result, separators=(",", ":")).encode("utf-8")
os.write(int(os.environ["TOPSAILAI_HOOK_RESULT_FD"]), struct.pack("!I", len(encoded)) + encoded)
''',
        encoding="utf-8",
    )
    path.chmod(0o700)


def prepare_deployment_files(root: Path) -> dict[str, str]:
    """Simulate deployment generation of a fixed config and trust manifest."""
    source_root = root / "sources"
    source_root.mkdir(mode=0o700)
    script = source_root / "observe.py"
    _write_protocol_script(script)
    interpreter = Path(sys.executable).resolve()
    interpreter_digest = hashlib.sha256(interpreter.read_bytes()).hexdigest()
    status = interpreter.stat()
    runtime_digest = shebang_runtime_fingerprint(
        interpreter,
        interpreter_digest,
        device=status.st_dev,
        inode=status.st_ino,
    )
    manifest = {
        "schema_version": 1,
        "source_roots": [str(source_root)],
        "allowed_interpreters": [str(interpreter)],
        "allow_native_scripts": False,
        "closure_assertions": [{
            "source_path": str(script),
            "kind": "script",
            "logical_name": script.name,
            "content_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            "runtime_sha256": runtime_digest,
            "deployment_sha256": "d" * 64,
            "closure": "single-file-trusted-runtime-v1",
        }],
        "python_runtime": None,
    }
    config = {
        "schema_version": 1,
        "hooks": {
            "hook_demo_configured_before": {"scripts": [script.name]},
        },
    }
    manifest_path = root / "trust-manifest.json"
    config_path = root / "hooks.json"
    digest = _write_json(manifest_path, manifest)
    _write_json(config_path, config)
    return {
        "TOPSAILAI_CONFIGURED_HOOKS_ENABLED": "1",
        "TOPSAILAI_CONFIGURED_HOOKS_CONFIG": str(config_path),
        "TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST": str(manifest_path),
        "TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST_SHA256": digest,
        "TOPSAILAI_CONFIGURED_HOOKS_REGISTRATION_MODE": "startup",
        "TOPSAILAI_CONFIGURED_HOOKS_STARTUP_POLICY": "fail",
    }


def run_application(environment: dict[str, str], root: Path) -> None:
    """Load deployment authority once and execute through Registrar and Executor."""
    bootstrap = load_configured_hook_bootstrap(environment)
    point = HookPointDeclaration(
        "hook_demo_configured_before",
        EventDefinition(
            "demo.configured.before",
            1,
            {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "evidence_file": {"type": "string"},
                },
                "required": ["message", "evidence_file"],
            },
        ),
        "before",
        "sync",
        "tests.demo.hooks",
    )
    catalog = HookPointCatalog((point,))
    runtime_root = root / "runtime"
    runtime_root.mkdir(mode=0o700)
    runtime = HookRuntime(
        HookSettings(
            limits=HookLimits(
                workers=1,
                queue_items=8,
                dispatch_timeout_ms=3_000,
                shutdown_timeout_ms=3_000,
            )
        ),
        temp_root=str(runtime_root),
        configured_trust=bootstrap.trust,
    )
    scope = runtime.open_scope(metadata={"owner_id": "configured-framework-demo"})
    registrar = ConfiguredHookRegistrar(runtime, scope, bootstrap, catalog)
    executor = ConfiguredHookExecutor(runtime, scope, registrar, catalog)
    try:
        startup = registrar.start()
        if not startup.ready:
            raise RuntimeError(f"startup registration failed: {startup}")
        evidence_file = root / "worker.pid"
        report = executor.dispatch(
            point,
            payload={
                "message": "hello configured Hook",
                "evidence_file": str(evidence_file),
            },
        )
        if report.rejection_reason is not None or len(report.outcomes) != 1:
            raise RuntimeError(f"configured dispatch failed: {report}")
        outcome = report.outcomes[0]
        if outcome.status.value != "success":
            raise RuntimeError(f"unexpected configured outcome: {outcome}")
        worker_pid = int(evidence_file.read_text(encoding="utf-8"))
        if worker_pid == os.getpid():
            raise RuntimeError("configured script did not run in an isolated worker")
        print(f"Registration mode: {bootstrap.registration_mode}")
        print(f"Trust identity: {bootstrap.trust_identity}")
        print(f"Worker PID: {worker_pid}")
        print(f"Outcome: {outcome.status.value}")
    finally:
        registrar.close()
        close_report = runtime.close()
        print(f"Cleanup debts: {len(close_report.cleanup_debts)}")
        if close_report.cleanup_debts:
            raise RuntimeError("runtime cleanup debt remains")


def main() -> int:
    """Run the complete configured framework demonstration."""
    temp_parent = PROJECT_ROOT / ".tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="configured-framework-demo-", dir=temp_parent))
    root.chmod(0o700)
    try:
        environment = prepare_deployment_files(root)
        run_application(environment, root)
        return 0
    finally:
        shutil.rmtree(root)
        print(f"Deleted demo temporary directory: {root}")


if __name__ == "__main__":
    raise SystemExit(main())
