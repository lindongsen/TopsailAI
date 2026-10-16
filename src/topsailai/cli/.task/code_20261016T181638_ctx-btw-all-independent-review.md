---
maintainer: AI
author: DawsonLin
---

# Independent ctx btw all unit review

## Verdict

REJECT. Reviewed the complete tracked diff for all eight modified files and all three untracked source/test files, plus design, checklist, supplied LEARN.md and relevant shared writer/probe code. Reviewer gpt-sol made no implementation or test changes. ds-dev remains implementation/test author; gpt-luna supplied execution evidence; independent acceptance remains withheld.

## Blocking findings

- High: runtime_broadcast.py:117-120,155 calls the real probe outside a per-target ordinary-error boundary. runtime_target.py:107 wraps process PermissionError in RuntimeTargetError, not PermissionError. A denied PID therefore aborts the broadcast, suppresses later eligible targets and loses the aggregate. Evidence lstat failures at runtime_broadcast.py:108-111 similarly escape per-target aggregation. Tests inject bare PermissionError and miss the production representation.
- High: streaming.py:1747-1751 and runtime_broadcast.py:137-149 lack the approved UTF-8 validity and 1 MiB byte-size preflight. Nonempty invalid/oversized input reaches discovery and the writer. Existing MESSAGE_LIMIT/validation in runtime_operations.py is not invoked by write_injection.
- Medium: streaming.py:1751-1761 renders all outcomes only after broadcast_message returns. If a later writer raises KeyboardInterrupt/SystemExit, earlier successful appends have no visible outcomes. There is no pre-delivery session/candidate announcement, categorized summary or explicit incomplete result handling. Host interrupts propagate correctly, but interrupted progress acceptance D07/D08 fails.
- Medium: streaming.py:509,514,1185,1313 still omit /ctx.btw-all from fallback/startup command lists; legacy broadcast collection uses the /ctx.btw prompt at 1658,1742. Violates command-discovery requirement and LEARN.md.
- Medium: test_runtime_broadcast.py:34-305 uses injected/mock writers throughout; test_streaming_broadcast.py:22-105 mocks broadcast_message throughout. No real public writer/JSONL integration I01-I03, no size/encoding boundaries, no multi-target interruption-progress test, and no new actual curses/raw/continuation routing coverage. The test at test_runtime_broadcast.py:101-102 explicitly accepts (temp) as an empty discovery instead of testing rejection, contrary to design.

## Additional gaps

_valid_session at runtime_broadcast.py:53-60 accepts literal (temp). docs/usage/topsailai.md:118 is only a table row, not the planned canonical contract covering snapshot timing, deduplication, uncertainty, cancellation and discovery/receiver limitations. Overview docs omit canonical links. Tests hardcode the checkout path at test_runtime_broadcast.py:22, reducing portability.

## Positive checks and evidence

- Existing /ctx.btw handler body is unchanged; dispatch still forwards default_pid. No YAML/core receiver/bin/noninteractive modifications are in this change set.
- Snapshot PID deduplication, exact session matching, session-evidence preference, live-only writing and per-writer ordinary-error continuation/no retry are implemented. Literal topsailai is rejected. Writer host interrupts propagate via except Exception.
- All tracked deletions reviewed: dispatch formatting/docstring/comment removals are intentional-looking and do not delete functional behavior, though unrelated formatting adds noise.
- Tester reports: A 12 passed, B 363 passed, C 1996 passed; final focused run 18 passed. Those counts are reported evidence, not independently rerun here. Execution ledger in checklist still says NOT RUN.
- Independently read existing Coverage.py data with COVERAGE_FILE=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/.coverage PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/bytecode python -m coverage report --include='*/cli_topsailai/runtime_broadcast.py' -m. Result: 119 statements, 2 missing, 32 branches, 0 partial, 99% combined coverage; missing 78-79. Numeric gate met; behavioral gates remain unmet. JSON report coverage-alt.json predates final data and should not be used as final evidence.
- git diff --check passed. No test execution, commit, reset or checkout performed in this review.

## Required next step

Assigned Developer repairs this same unit and adds missing behavioral tests, assigned Tester reruns focused/related/full checks and final scoped coverage, then independent Reviewer rereviews. Update the checklist evidence ledger. Do not accept based on coverage alone.

## Residual limits

Queue success does not establish receiver consumption, exactly-once semantics or coordinated action. PIDs lacking stdout evidence are undiscoverable; trusted-storage PID reuse/check-open races and no hard writer deadline remain as approved limitations. No live multi-agent consumption or cross-platform environment was verified.
