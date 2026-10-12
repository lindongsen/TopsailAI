"""Real awaited target cancellation and deadline acceptance. Author: DawsonLin."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from topsailai.hooks import ConfiguredTrustPolicy, HookLimits, HookRuntime, HookSettings
from topsailai.hooks.configured_bootstrap import ConfiguredHookBinding, ConfiguredHookBootstrap
from topsailai.hooks.configured_executor import ConfiguredHookExecutor
from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration
from topsailai.hooks.hook_script_contracts import HookScriptExecutionPolicy
from tests.bdd.simplified_hook_configuration_harness import _assertion


class TargetLifecycleScenario:
    """Own real configured execution, readiness evidence and exact cleanup."""

    def __init__(self, root: Path, mode: str):
        """Create ordered trusted Scripts without replacing any runtime function."""
        self.root, self.mode = root, mode
        self.sources = root / "sources"
        self.sources.mkdir()
        self.ledger = root / "processes.jsonl"
        scripts = []
        for name in ("a_block", "z_successor"):
            path = self.sources / name
            body = (f"#!{Path(sys.executable).resolve()}\n"
                "import json, os, time\nfrom pathlib import Path\n"
                f"with Path({str(self.ledger)!r}).open('a') as stream:\n"
                f"    stream.write(json.dumps({{'name': {name!r}, 'pid': os.getpid(), 'file': __file__}}) + '\\n')\n")
            if mode == "deadline":
                body = body.replace("'file': __file__", "'file': __file__, 'started_at': time.monotonic()")
            if name == "a_block":
                body += "while True:\n    time.sleep(0.02)\n"
            path.write_text(body)
            path.chmod(0o700)
            scripts.append(path)
        trust = ConfiguredTrustPolicy(source_roots=(self.sources,),
            allowed_interpreters=(Path(sys.executable).resolve(),),
            closure_assertions=tuple(_assertion(path) for path in scripts))
        self.runtime = HookRuntime(HookSettings(limits=HookLimits(workers=1,
            dispatch_timeout_ms=20_000, shutdown_timeout_ms=3_000)),
            temp_root=str(root / "runtime"), configured_trust=trust)
        self.scope = self.runtime.open_scope(metadata={"owner_id": "u11c-bdd"})
        self.point = HookPointDeclaration("hook_u11c", EventDefinition("bdd.lifecycle", 1,
            {"type": "object"}), "before", "async", "u11c")
        catalog = HookPointCatalog((self.point,))
        bootstrap = ConfiguredHookBootstrap(True, registration_mode="lazy",
            hooks=(ConfiguredHookBinding(self.point.name, scripts=tuple(reversed(scripts))),),
            trust=trust, trust_identity="a" * 64)
        self.registrar = ConfiguredHookRegistrar(self.runtime, self.scope, bootstrap, catalog)
        self.executor = ConfiguredHookExecutor(self.runtime, self.scope, self.registrar, catalog)
        self.report = None
        self.cancelled = False
        self.closed = False

    def rows(self):
        """Read flushed process-side evidence, never host-side invocation guesses."""
        return [json.loads(line) for line in self.ledger.read_text().splitlines()] if self.ledger.exists() else []

    async def wait_started(self, task):
        """Wait for actual child readiness while exposing early execution failures."""
        limit = time.monotonic() + 10
        while not self.rows():
            assert not task.done(), "execution completed before child readiness"
            assert time.monotonic() < limit, "child readiness was not observed"
            await asyncio.sleep(0.01)
        assert [row["name"] for row in self.rows()] == ["a_block"]

    async def exercise(self):
        """Propagate real host cancellation or enforce one caller-supplied deadline."""
        ensured = await asyncio.to_thread(self.registrar.ensure_registered, self.point.name)
        assert ensured.ready, ensured
        task = None
        try:
            if self.mode == "cancel":
                task = asyncio.create_task(self.executor.adispatch(self.point, payload={}))
                await self.wait_started(task)
                task.cancel()
                try:
                    self.report = await task
                except asyncio.CancelledError:
                    self.cancelled = True
                assert self.cancelled and self.report is None
                assert task.cancelled()
                return
            event = self.runtime.make_event(self.scope, "bdd.lifecycle", 1, {},
                operation_id="u11c-operation", layer="bdd", purpose="deadline")
            shared_budget = 0.3
            if self.mode == "deadline":
                local_policy = HookScriptExecutionPolicy()
                assert 0 < shared_budget < min(
                    local_policy.entry_timeout_ms, local_policy.hook_timeout_ms) / 1000
            deadline = time.monotonic() + (-1 if self.mode == "expired" else shared_budget)
            task = asyncio.create_task(self.runtime.adispatch_configured(
                self.point.name, event, deadline=deadline))
            if self.mode == "deadline":
                await self.wait_started(task)
                assert self.rows()[0]["started_at"] < deadline
            self.report = await task
            if self.mode == "deadline":
                assert time.monotonic() >= deadline
                print(json.dumps({"shared_budget_seconds": shared_budget,
                    "entry_budget_ms": local_policy.entry_timeout_ms,
                    "group_budget_ms": local_policy.hook_timeout_ms,
                    "child_started_at": self.rows()[0]["started_at"],
                    "absolute_deadline": deadline, "settled_at": time.monotonic()}))
            if self.report.rejection_reason is not None:
                assert self.report.rejection_reason == "deadline", self.report
                assert self.report.deadline_exhausted
                assert self.mode == "expired" and self.rows() == []
                return
            result = self.report.unified_result
            assert result.status == "timeout", result
            assert result.cleanup.state == "safe", result
            if self.mode == "expired":
                assert self.rows() == []
                assert result.handlers[-1].status == "not_run"
                assert result.handlers[-1].not_run_reason == "deadline"
            else:
                children = result.handlers[-1].children
                assert children[0].status == "timeout" and not children[0].returned.present
                assert children[1].status == "not_run" and not children[1].returned.present
            assert all(row["name"] != "z_successor" for row in self.rows())
        finally:
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    def run(self):
        """Use a real event loop without stubbing scheduler or worker boundaries."""
        asyncio.run(self.exercise())

    def close(self):
        """Close exact owners and reconcile publicly retained cleanup custody."""
        if self.closed:
            return
        try:
            self.registrar.close()
        finally:
            self.runtime.close()
            self.closed = True
            for debt in self.runtime.cleanup_debts():
                assert self.runtime.retry_cleanup(debt.debt_id), debt

    def assert_settled(self):
        """Prove barrier, isolated child absence and strict artifact/debt convergence."""
        self.close()
        assert self.scope.closed and self.runtime.cleanup_debts() == ()
        rows = self.rows()
        assert [row["name"] for row in rows] == ([] if self.mode == "expired" else ["a_block"])
        for row in rows:
            assert row["pid"] != os.getpid()
            assert not Path(row["file"]).is_relative_to(self.sources)
            try:
                os.kill(row["pid"], 0)
            except ProcessLookupError:
                continue
            raise AssertionError(f"owned child remains alive: {row}")
        artifacts = self.root / "runtime" / "configured-artifacts"
        if artifacts.exists():
            for parent in artifacts.iterdir():
                assert not parent.is_symlink() and parent.is_dir(), parent
                assert list(parent.iterdir()) == [], parent
