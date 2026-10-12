# Unified Hooks demos

Run these demos from the ProjectFolder:

```text
python tests/demo/hooks/demo_basic_dispatch.py
python tests/demo/hooks/demo_failure_isolation.py
python tests/demo/hooks/demo_runtime_reload.py
python tests/demo/hooks/demo_configured_framework_readiness.py
```

The demos use the public `HookRuntime` API and real isolated worker processes. They provide focused behavior evidence; final framework acceptance also requires the full regression and completion review recorded in the authoritative design.
The first shows deterministic priority/dependency order and worker isolation.
The second shows that one failed handler is reported as an error while an
independent handler succeeds and the host flow continues. The third shows a
settings reload, replacement of an old binding, a newer registry generation,
and rejection after runtime close. The configured-framework demo uses the public versioned trust-manifest loader, startup Registrar, Catalog, Executor, a non-empty configured script, and a real isolated worker.

PIDs, elapsed values, delivery IDs, and generation numbers can vary between
runs. Each demo owns a temporary directory below `.tmp`, closes its runtime in
`finally`, reports cleanup debt, and prints whether its temporary directory was
removed. The demos do not access the network, an LLM, credentials, or project
configuration, and they do not terminate unrelated processes.

The configured startup demo simulates deployment-owned manifest generation only
for its isolated source and interpreter. Real deployments must supply their own
versioned manifest and pinned digest before loading the public bootstrap; the
demo is not a trust-authority generator for arbitrary plugins. It verifies the
unified default Hook and Script child process facts, closes the scope, reconciles
cleanup debt through the public API, and checks exact worker exit and captured
artifact convergence. Its integration test also checks the demo process exits
and its owned directory under `.tmp/u11/final` is removed. Async and lazy demos
are separate future increments, not evidence claimed by this startup demo.
