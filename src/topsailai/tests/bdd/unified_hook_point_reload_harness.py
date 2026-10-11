"""Real Registrar reload acceptance across isolated workers. Author: DawsonLin."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from topsailai.hooks import ConfiguredTrustPolicy, HookLimits, HookRuntime, HookSettings
from topsailai.hooks.configured_bootstrap import ConfiguredHookBinding, ConfiguredHookBootstrap
from topsailai.hooks.configured_executor import ConfiguredHookExecutor
from topsailai.hooks.configured_registration import ConfiguredHookRegistrar, RegistrationState
from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration
from tests.bdd.simplified_hook_configuration_harness import _assertion, _write_script


class RegistrarReloadScenario:
    """Own real script captures, Registrar revisions and process evidence."""

    def __init__(self, root: Path, mode: str):
        """Create exact trusted versions and a deliberately unauthorized candidate."""
        self.root, self.mode = root, mode
        self.sources = root / "sources"
        self.ledger = root / "processes.jsonl"
        self.scripts = {}
        for version in ("v1", "rejected", "v3"):
            path = _write_script(self.sources / (version + ".py"), version)
            body = path.read_text(encoding="utf-8")
            body = body.replace('stream.write(' + repr(version) + ' + "\\n")',
                'stream.write(json.dumps({"version": ' + repr(version) +
                ', "pid": os.getpid(), "file": __file__}) + "\\n")')
            path.write_text(body, encoding="utf-8")
            self.scripts[version] = path
        # Pin exact bytes first, then mutate only the rejected fixture source.
        assertions = tuple(_assertion(path) for path in self.scripts.values())
        trust = ConfiguredTrustPolicy(source_roots=(self.sources,),
            allowed_interpreters=(Path(sys.executable).resolve(),), closure_assertions=assertions)
        with self.scripts["rejected"].open("a", encoding="utf-8") as stream:
            stream.write("\n# Unauthorized replacement bytes.\n")
        self.runtime = HookRuntime(HookSettings(limits=HookLimits(workers=1,
            dispatch_timeout_ms=20_000, shutdown_timeout_ms=3_000)),
            temp_root=str(root / "runtime"), configured_trust=trust)
        self.scope = self.runtime.open_scope(metadata={"owner_id": "u11b-bdd"})
        self.point = HookPointDeclaration("hook_u11b", EventDefinition("bdd.reload", 1,
            {"type": "object", "properties": {"log": {"type": "string"}}}),
            "before", "sync", "u11b")
        self.catalog = HookPointCatalog((self.point,))
        self.trust = trust
        initial = "rejected" if mode == "first-failure" else "v1"
        self.registrar = ConfiguredHookRegistrar(self.runtime, self.scope,
            self.bootstrap(101, initial), self.catalog)
        self.executor = ConfiguredHookExecutor(self.runtime, self.scope, self.registrar, self.catalog)
        self.closed = False

    def bootstrap(self, revision: int, version: str):
        """Build a detached desired selection without changing Runtime authority."""
        return ConfiguredHookBootstrap(True, registration_mode="lazy",
            configuration_generation=revision,
            hooks=(ConfiguredHookBinding(self.point.name, scripts=(self.scripts[version],)),),
            trust=self.trust, trust_identity="a" * 64)

    def rows(self):
        """Read process-owned evidence only after waiting dispatch completion."""
        return [json.loads(line) for line in self.ledger.read_text().splitlines()] if self.ledger.exists() else []

    def dispatch(self, version: str, active_revision: int):
        """Verify the actual target default Hook, child return and immutable version."""
        before = len(self.rows())
        report = self.executor.dispatch(self.point, payload={"log": str(self.ledger)})
        assert report.rejection_reason is None, report
        result = report.unified_result
        assert result.status == "success" and result.cleanup.state == "safe"
        assert result.plan_version == active_revision
        assert len(result.handlers) == 1
        default = result.handlers[0]
        assert default.handler.kind == "default_script_hook"
        assert len(default.children) == 1
        child = default.children[0]
        assert child.status == "success" and child.returned.present
        assert child.returned.representation == "direct"
        assert child.returned.value == {
            "exit_code": 0, "stdout": b"", "stderr": b"",
            "stdout_dropped": 0, "stderr_dropped": 0,
        }
        assert [row["version"] for row in self.rows()[before:]] == [version]

    def run(self):
        """Exercise reload mismatch, retained LKG, recovery or first unavailable."""
        first = self.registrar.ensure_registered(self.point.name)
        if self.mode == "first-failure":
            assert not first.ready and first.active_revision is None
            assert first.desired_revision == 101
            assert not first.update_failed_using_last_known_good
            assert first.state is RegistrationState.FAILED_DETERMINISTIC
            report = self.executor.dispatch(self.point, payload={"log": str(self.ledger)})
            assert report.rejection_reason == first.error_category
            assert report.unified_result is None and report.outcomes == ()
            assert self.registrar.ensure_registered(self.point.name) == first
            assert self.rows() == []
            event = self.runtime.make_event(self.scope, "bdd.reload", 1, {},
                operation_id="u11b-unavailable", layer="bdd", purpose="registrar-reload")
            assert self.runtime.dispatch_configured(self.point.name, event).rejection_reason == "unknown_configured_hook"
            return
        assert first.ready and first.desired_revision == 101
        assert first.active_revision is not None
        self.dispatch("v1", first.active_revision)
        self.registrar.reload(self.bootstrap(102, "rejected"))
        assert self.registrar.state(self.point.name) is RegistrationState.UNINITIALIZED
        failed = self.registrar.ensure_registered(self.point.name)
        assert failed.ready and failed.state is RegistrationState.FAILED_DETERMINISTIC
        assert failed.desired_revision == 102 and failed.active_revision == first.active_revision
        assert failed.desired_revision != failed.active_revision
        assert failed.update_failed_using_last_known_good and failed.error_category
        rows = self.rows()
        assert self.registrar.ensure_registered(self.point.name) == failed
        assert failed.attempt == 1 and self.rows() == rows
        self.dispatch("v1", first.active_revision)
        if self.mode == "recovery":
            self.registrar.reload(self.bootstrap(103, "v3"))
            recovered = self.registrar.ensure_registered(self.point.name)
            assert recovered.ready and recovered.desired_revision == 103
            assert recovered.active_revision != first.active_revision
            assert not recovered.update_failed_using_last_known_good
            assert recovered.error_category is None
            self.dispatch("v3", recovered.active_revision)
        assert all(row["version"] != "rejected" for row in self.rows())

    def close(self):
        """Close admission and the Runtime even if Registrar closure raises."""
        if not self.closed:
            try:
                self.registrar.close()
            finally:
                self.runtime.close()
                self.closed = True
                for debt in self.runtime.cleanup_debts():
                    assert self.runtime.retry_cleanup(debt.debt_id), debt

    def assert_settled(self):
        """Reject live observed workers, cleanup debt and residual captured content."""
        self.close()
        assert self.scope.closed and self.runtime.cleanup_debts() == ()
        expected = [] if self.mode == "first-failure" else ["v1", "v1"]
        if self.mode == "recovery":
            expected.append("v3")
        assert [row["version"] for row in self.rows()] == expected
        for row in self.rows():
            assert row["pid"] != os.getpid()
            assert not Path(row["file"]).is_relative_to(self.sources)
            try:
                os.kill(row["pid"], 0)
            except ProcessLookupError:
                continue
            raise AssertionError(f"owned worker still exists: {row}")
        artifacts = self.root / "runtime" / "configured-artifacts"
        if artifacts.exists():
            for parent in artifacts.iterdir():
                assert not parent.is_symlink() and parent.is_dir(), parent
                assert list(parent.iterdir()) == [], parent
