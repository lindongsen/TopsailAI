"""Real target Hook Point acceptance harness. Author: DawsonLin."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from topsailai.hooks import ConfiguredTrustPolicy, HookLimits, HookRuntime, HookSettings
from topsailai.hooks.artifact_contracts import ArtifactClosureAssertion, ArtifactPythonRuntimeAuthority
from topsailai.hooks.artifact_identity import python_runtime_fingerprint, shebang_runtime_fingerprint
from topsailai.hooks.hook_point_plan_contracts import ModuleSource


class TargetHookPointScenario:
    """Own trusted sources, the public runtime and process-side evidence."""

    def __init__(self, root: Path, mode: str):
        """Create only scenario-owned fixture sources and explicit deployment trust."""
        self.root, self.mode = root, mode
        self.ledger = root / "processes.jsonl"
        self.sources = root / "sources"
        self.sources.mkdir(mode=0o700)
        executable = Path(sys.executable).resolve()
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        stat = executable.stat()
        python_fingerprint = python_runtime_fingerprint(
            executable, digest, device=stat.st_dev, inode=stat.st_ino)
        script_fingerprint = shebang_runtime_fingerprint(
            executable, digest, device=stat.st_dev, inode=stat.st_ino)
        self.modules, self.scripts, assertions = [], [], []
        names = ("中", "a2", "a10", "Z") if mode == "ordered" else (() if mode == "empty" else ("value",))
        expressions = {"none": "None", "false": "False", "error-dict": "{'error': 'normal data'}", "opaque": "object()"}
        for index, name in enumerate(names):
            logical = f"u11a_plugin_{index}"
            path = self.sources / f"{logical}.py"
            expression = expressions.get(mode, "None")
            body = self._recorder(name, "module")
            body += "record('import')\ndef main(*args, **kwargs):\n    record('main')\n"
            body += f"    return {expression}\n"
            path.write_text(body, encoding="utf-8")
            path.chmod(0o400)
            self.modules.append(ModuleSource(name, path, logical, "python_source", logical + ":main"))
            assertions.append(self._assertion(path, "python_source", logical, python_fingerprint))
        if mode == "ordered":
            for name in ("中", "a2", "a10", "Z"):
                path = self.sources / name
                body = f"#!{executable}\n" + self._recorder(name, "script")
                body += "record('start')\nimport struct\nmessage = json.loads(sys.stdin.buffer.read())\n"
                body += "reply = {key: message[key] for key in ('delivery_id', 'invocation_id', 'entry_index')}\n"
                body += "reply.update(protocol_version=1, value=None)\nencoded = json.dumps(reply).encode()\n"
                body += "os.write(int(os.environ['TOPSAILAI_HOOK_RESULT_FD']), struct.pack('!I', len(encoded)) + encoded)\n"
                path.write_text(body, encoding="utf-8")
                path.chmod(0o700)
                self.scripts.append(path)
                assertions.append(self._assertion(path, "script", path.name, script_fingerprint))
        trust = ConfiguredTrustPolicy(source_roots=(self.sources,), allowed_interpreters=(executable,),
            closure_assertions=tuple(assertions), python_runtime=ArtifactPythonRuntimeAuthority(executable, digest))
        self.runtime = HookRuntime(HookSettings(limits=HookLimits(workers=1,
            dispatch_timeout_ms=20_000, shutdown_timeout_ms=3_000)),
            temp_root=str(root / "runtime"), configured_trust=trust)
        self.scope = self.runtime.open_scope(metadata={"owner_id": "u11a-bdd"})
        self.report = None
        self.closed = False

    def _recorder(self, name: str, kind: str) -> str:
        """Generate process evidence without importing plugin code in the host."""
        return ("import json, os, sys\nfrom pathlib import Path\n"
            "def record(phase):\n    row = {'pid': os.getpid(), 'phase': phase, "
            f"'kind': {kind!r}, 'name': {name!r}, 'file': __file__}}\n"
            f"    with Path({str(self.ledger)!r}).open('a', encoding='utf-8') as stream:\n"
            "        stream.write(json.dumps(row, ensure_ascii=False) + '\\n')\n")

    @staticmethod
    def _assertion(path: Path, kind: str, logical: str, fingerprint: str):
        """Authorize exact test-owned bytes using the established public contract."""
        return ArtifactClosureAssertion(path, kind, logical,
            hashlib.sha256(path.read_bytes()).hexdigest(), fingerprint, "a" * 64)

    def run(self):
        """Drive public target registration and one complete waiting execution."""
        registration = self.runtime.register_hook_point("hook_u11a", self.scope,
            modules=self.modules, scripts=self.scripts)
        assert registration.accepted, registration
        event = self.runtime.make_event(self.scope, "bdd.target", 1, {},
            operation_id="u11a-operation", layer="bdd", purpose="acceptance")
        self.report = self.runtime.dispatch_hook_point("hook_u11a", event)
        assert self.report.rejection_reason is None, self.report
        result = self.report.unified_result
        assert result.status == "success" and result.cleanup.state == "safe", result
        assert result.decision.action == "continue"
        assert self.runtime.cleanup_debts() == ()

    def rows(self):
        """Read only scenario-owned process-side evidence after waiting completion."""
        return [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines()] if self.ledger.exists() else []

    def assert_business_result(self):
        """Assert two-phase identity ordering, empty default or normal return partitions."""
        result = self.report.unified_result
        default = result.handlers[-1]
        assert default.handler.kind == "default_script_hook"
        assert sum(item.handler.kind == "default_script_hook" for item in result.handlers) == 1
        assert all(item.status == "success" and item.cleanup.state == "safe" for item in result.handlers)
        if self.mode == "ordered":
            order = ["Z", "a10", "a2", "中"]
            assert [item.handler.name for item in result.handlers[:-1]] == order
            assert [item.handler.name for item in default.children] == order
            calls = [row for row in self.rows() if row["phase"] in ("main", "start")]
            assert [(row["kind"], row["name"]) for row in calls] == [("module", name) for name in order] + [("script", name) for name in order]
            assert default.returned.present and default.returned.representation == "direct"
            assert len(default.returned.value) == len(default.children) == 4
            assert all(child.status == "success" and child.cleanup.state == "safe" and child.returned.present for child in default.children)
        elif self.mode == "empty":
            assert len(result.handlers) == 1 and default.children == ()
            assert not default.returned.present and default.returned.representation == "unavailable"
            assert self.rows() == []
        else:
            assert len(result.handlers) == 2 and default.children == ()
            returned = result.handlers[0].returned
            assert returned.present
            expected = {"none": None, "false": False, "error-dict": {"error": "normal data"}, "opaque": None}[self.mode]
            assert returned.value == expected
            assert returned.representation == ("unavailable" if self.mode == "opaque" else "transported")
            assert len([row for row in self.rows() if row["phase"] == "main"]) == 1

    def close(self):
        """Settle the owned scope/runtime before checking exact observed child exits."""
        if not self.closed:
            try:
                self.scope.close()
            finally:
                self.runtime.close()
                self.closed = True

    def assert_settled(self):
        """Verify import isolation, exact invocation workers and artifact removal."""
        self.close()
        rows = self.rows()
        mains = [row for row in rows if row["phase"] == "main"]
        imports = [row for row in rows if row["phase"] == "import"]
        # Each module has a discovery probe and a distinct captured execution worker.
        assert len(imports) == 2 * len(self.modules)
        assert len(mains) == len(self.modules)
        assert len([row for row in rows if row["phase"] == "start"]) == len(self.scripts)
        for row in rows:
            assert row["pid"] != os.getpid()
            assert not Path(row["file"]).is_relative_to(self.sources)
            try:
                os.kill(row["pid"], 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError(f"owned child still exists: {row}")
        for row in mains:
            assert len([item for item in imports if item["pid"] == row["pid"] and item["name"] == row["name"]]) == 1
        assert all(module.logical_name not in sys.modules for module in self.modules)
        assert self.runtime.cleanup_debts() == ()
        artifacts = self.root / "runtime" / "ordinary-artifacts"
        # Capture cleanup removes owned artifacts, not empty publication parents.
        if artifacts.exists():
            for parent in artifacts.iterdir():
                assert not parent.is_symlink() and parent.is_dir(), parent
                assert list(parent.iterdir()) == [], parent
