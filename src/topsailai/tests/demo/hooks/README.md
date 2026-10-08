# Unified Hooks demos

Run these demos from `/TopsailAI/src/topsailai`:

```text
python tests/demo/hooks/demo_basic_dispatch.py
python tests/demo/hooks/demo_failure_isolation.py
python tests/demo/hooks/demo_runtime_reload.py
```

The demos use the public `HookRuntime` API and real isolated worker processes.
The first shows deterministic priority/dependency order and worker isolation.
The second shows that one failed handler is reported as an error while an
independent handler succeeds and the host flow continues. The third shows a
settings reload, replacement of an old binding, a newer registry generation,
and rejection after runtime close.

PIDs, elapsed values, delivery IDs, and generation numbers can vary between
runs. Each demo owns a temporary directory below `.tmp`, closes its runtime in
`finally`, reports cleanup debt, and prints whether its temporary directory was
removed. The demos do not access the network, an LLM, credentials, or project
configuration, and they do not terminate unrelated processes.
