"""Real Catalog wrapper business acceptance. Author: DawsonLin."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from topsailai.hooks import ConfiguredTrustPolicy, HookLimits, HookRuntime, HookSettings
from topsailai.hooks.configured_bootstrap import ConfiguredHookBinding, ConfiguredHookBootstrap
from topsailai.hooks.configured_executor import ConfiguredHookExecutor, HookPointBlockedError
from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration
from topsailai.hooks.hook_point_decorator import hook_point
from tests.bdd.simplified_hook_configuration_harness import _assertion, _write_script


class CatalogWrapperScenario:
    """Own real wrapper execution and its exact process evidence."""

    def __init__(self, root: Path, mode: str, case: str):
        """Build trusted Scripts and one explicitly authorized Catalog point."""
        self.root, self.mode, self.case = root, mode, case
        self.sources = root / "sources"
        self.ledger = root / "processes.jsonl"
        script = _write_script(self.sources / "handler.py", "handler")
        body = script.read_text()
        body = body.replace("stream.write('handler' + \"\\n\")",
            "stream.write(json.dumps({'pid': os.getpid(), 'file': __file__}) + \"\\n\")")
        if case.startswith("normal-"):
            value = {"normal-none": "None", "normal-false": "False",
                     "normal-error-dict": "{'error': 'ordinary data'}"}[case]
            body = body.replace("{'marker': 'handler'}", value)
        else:
            body = body[:body.index("result = {")] + "raise RuntimeError('isolated hook failure')\n"
        script.write_text(body)
        trust = ConfiguredTrustPolicy(source_roots=(self.sources,),
            allowed_interpreters=(Path(sys.executable).resolve(),),
            closure_assertions=(_assertion(script),))
        self.runtime = HookRuntime(HookSettings(limits=HookLimits(workers=1,
            dispatch_timeout_ms=20_000, shutdown_timeout_ms=3_000)),
            temp_root=str(root / "runtime"), configured_trust=trust)
        self.scope = self.runtime.open_scope(metadata={"owner_id": "u11d-bdd"})
        phase = "success" if case == "success-block" else ("error" if case == "error-block" else "before")
        policy = "report" if case == "before-report" else "block"
        self.point = HookPointDeclaration("hook_u11d", EventDefinition("bdd.wrapper", 1,
            {"type": "object", "properties": {"log": {"type": "string"}}}),
            phase, mode, "u11d", failure_policy=policy, security_critical=policy == "block",
            allow_post_success_block=phase == "success")
        catalog = HookPointCatalog((self.point,))
        bootstrap = ConfiguredHookBootstrap(True, registration_mode="lazy",
            hooks=(ConfiguredHookBinding(self.point.name, scripts=(script,)),),
            trust=trust, trust_identity="a" * 64)
        self.registrar = ConfiguredHookRegistrar(self.runtime, self.scope, bootstrap, catalog)
        self.executor = ConfiguredHookExecutor(self.runtime, self.scope, self.registrar, catalog)
        self.mutations = []
        self.original = ValueError("original business failure")
        self.closed = False

    def rows(self):
        """Read process-side evidence after awaited execution."""
        return [json.loads(line) for line in self.ledger.read_text().splitlines()] if self.ledger.exists() else []

    def run(self):
        """Exercise the real wrapper without substituting any framework component."""
        def business():
            """Record irreversible business entry before any success Hook."""
            self.mutations.append("committed")
            if self.case == "error-block":
                raise self.original
            return "business result"

        async def async_business():
            """Use the same business facts through an awaited callable."""
            return business()

        decorated = hook_point(**{self.point.phase: self.point},
            executor_provider=lambda: self.executor,
            payload_builder=lambda view: {"log": str(self.ledger)})(
                async_business if self.mode == "async" else business)
        result, caught = None, None
        try:
            result = asyncio.run(decorated()) if self.mode == "async" else decorated()
        except (HookPointBlockedError, ValueError) as error:
            caught = error
        assert len(self.rows()) == 1, self.rows()
        if self.case == "error-block":
            assert caught is self.original
            frames = []
            trace = caught.__traceback__
            while trace is not None:
                frames.append(trace.tb_frame.f_code.co_name)
                trace = trace.tb_next
            assert "business" in frames
        elif self.case in ("before-block", "success-block"):
            assert isinstance(caught, HookPointBlockedError), caught
            assert caught.point_name == self.point.name
            assert caught.reason == "completed_with_errors", caught.reason
        else:
            assert caught is None and result == "business result", caught
        assert self.mutations == ([] if self.case == "before-block" else ["committed"])
        assert result is None if caught is not None else result == "business result"

    def close(self):
        """Close admission and publicly reconcile scenario-owned cleanup debts."""
        if not self.closed:
            try:
                self.registrar.close()
            finally:
                self.runtime.close()
                self.closed = True
                for debt in self.runtime.cleanup_debts():
                    assert self.runtime.retry_cleanup(debt.debt_id), debt

    def assert_settled(self):
        """Reject live children, retained custody and residual capture contents."""
        self.close()
        assert self.scope.closed and self.runtime.cleanup_debts() == ()
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
