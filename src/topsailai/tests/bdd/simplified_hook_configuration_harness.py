"""Public-runtime harness for simplified configured Hook behavior."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from topsailai.hooks import (
    ArtifactClosureAssertion,
    ConfiguredTrustPolicy,
    HookLimits,
    HookRuntime,
    HookSettings,
)
from topsailai.hooks.artifact_identity import shebang_runtime_fingerprint

_HOOK_NAME = "hook_bdd_configured"


def _write_script(path: Path, marker: str) -> Path:
    """Create one self-contained executable Hook protocol script."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''#!{Path(sys.executable).resolve()}
import json
import os
import pathlib
import struct
import sys
message = json.loads(sys.stdin.buffer.read().decode("utf-8"))
payload = message["context"]["event"]["payload"]
with pathlib.Path(payload["log"]).open("a", encoding="utf-8") as stream:
    stream.write({marker!r} + "\\n")
result = {{
    "protocol_version": 1,
    "delivery_id": message["delivery_id"],
    "invocation_id": message["invocation_id"],
    "entry_index": message["entry_index"],
    "value": {{"marker": {marker!r}}},
}}
encoded = json.dumps(result, separators=(",", ":")).encode("utf-8")
os.write(int(os.environ["TOPSAILAI_HOOK_RESULT_FD"]), struct.pack("!I", len(encoded)) + encoded)
''',
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _assertion(path: Path) -> ArtifactClosureAssertion:
    """Authorize one exact script and its resolved interpreter closure."""
    interpreter = Path(sys.executable).resolve()
    status = interpreter.stat()
    interpreter_digest = hashlib.sha256(interpreter.read_bytes()).hexdigest()
    runtime_digest = shebang_runtime_fingerprint(
        interpreter,
        interpreter_digest,
        device=status.st_dev,
        inode=status.st_ino,
    )
    return ArtifactClosureAssertion(
        path.resolve(),
        "script",
        path.name,
        hashlib.sha256(path.read_bytes()).hexdigest(),
        runtime_digest,
        "a" * 64,
    )


class SimplifiedHookScenario:
    """Own one configured Runtime scenario and its observable resources."""

    def __init__(self, root: Path, mode: str) -> None:
        """Create scripts, Runtime, Scope, and the requested public registration."""
        self.root = root
        self.source_root = root / "sources"
        self.log = root / "execution.log"
        self.scripts = {
            "z": _write_script(self.source_root / "z.py", "z"),
            "a": _write_script(self.source_root / "nested" / "a.py", "a"),
            "new": _write_script(self.source_root / "replacement" / "new.py", "new"),
        }
        trust = ConfiguredTrustPolicy(
            source_roots=(self.source_root.resolve(),),
            allowed_interpreters=(Path(sys.executable).resolve(),),
            closure_assertions=tuple(_assertion(path) for path in self.scripts.values()),
        )
        runtime_root = root / "runtime"
        runtime_root.mkdir()
        self.runtime = HookRuntime(
            HookSettings(
                limits=HookLimits(
                    workers=1,
                    queue_items=8,
                    dispatch_timeout_ms=3_000,
                    shutdown_timeout_ms=3_000,
                )
            ),
            temp_root=str(runtime_root),
            configured_trust=trust,
        )
        self.scope = self.runtime.open_scope(metadata={"owner_id": "bdd-configured"})
        self.report = None
        self.failed_replacement = None
        self.artifacts: list[Path] = []
        self.closed = False
        if mode in {"scripts", "exact"}:
            result = self.runtime.register_configured(
                _HOOK_NAME, self.scope, scripts=(self.scripts["z"], self.scripts["a"])
            )
        elif mode == "folder":
            result = self.runtime.register_configured(
                _HOOK_NAME, self.scope, folder=self.source_root
            )
        elif mode == "replacement":
            initial = self.runtime.register_configured(
                _HOOK_NAME, self.scope, scripts=(self.scripts["z"],)
            )
            assert initial.accepted
            result = self.runtime.register_configured(
                _HOOK_NAME, self.scope, scripts=(self.scripts["new"],)
            )
        else:
            raise ValueError(f"unsupported scenario mode: {mode}")
        assert result.accepted
        _, plan = self.runtime._registry.configured_plan(self.scope.scope_id, _HOOK_NAME)
        self.artifacts.extend(entry.source_path.parents[1] for entry in plan.entries)

    def event(self):
        """Create one business event whose name is independent of the Hook name."""
        return self.runtime.make_event(
            self.scope,
            "bdd.configured.business-event",
            1,
            {"log": str(self.log)},
            operation_id="bdd-configured-operation",
            layer="bdd",
            purpose="configured-hook",
        )

    def execute(self, hook_name: str = _HOOK_NAME) -> None:
        """Dispatch through the public configured Runtime method."""
        self.report = self.runtime.dispatch_configured(hook_name, self.event())

    def reject_invalid_replacement(self) -> None:
        """Attempt one invalid replacement through the public registration method."""
        self.failed_replacement = self.runtime.register_configured(
            _HOOK_NAME,
            self.scope,
            scripts=(self.source_root / "missing.py",),
        )
        assert not self.failed_replacement.accepted

    def close(self) -> None:
        """Close the public Runtime ownership boundary exactly once."""
        if not self.closed:
            self.runtime.close()
            self.closed = True

    def lines(self) -> list[str]:
        """Return execution markers written by real isolated processes."""
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def assert_success(self, expected: list[str]) -> None:
        """Assert successful public reporting and exact process order."""
        assert self.report is not None
        assert self.report.rejection_reason is None
        assert [outcome.status.value for outcome in self.report.outcomes] == ["success"]
        assert self.lines() == expected

    def assert_cleanup(self) -> None:
        """Assert Runtime closure removed every captured artifact root."""
        assert self.closed
        assert self.scope.closed
        assert self.runtime.cleanup_debts() == ()
        assert all(not artifact.exists() for artifact in self.artifacts)
