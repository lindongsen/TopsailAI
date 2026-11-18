---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-18
---

# The TopsailAI conformance fixture cannot answer `session.metrics`

## Symptom

`make test-provider-topsailai-conformance` fails at HEAD:

```text
--- FAIL: TestProviderTypedQueryConformance (0.16s)
    --- FAIL: TestProviderTypedQueryConformance/session.metrics (0.00s)
        executable_test.go:134: decode typed query result: query_result must not be null
FAIL
```

Every other query in the sweep passes. Only `session.metrics` returns a null result document.

## Reproduction

```bash
make test-provider-topsailai-conformance
```

Reproduced in a detached worktree at HEAD `3f83f829` before any change of the provider workspace
refactor existed, so this is not a consequence of that refactor.

## Cause

The fixture business CLI does not emit the runtime envelope the Provider reads for this query.

`session.metrics` is answered by the Provider from
`workspace list --json --local -s SESSION --include-runtime`, reading `items[row].runtime`
(`providers/topsailai/src/query.go`, `runtimeMessageCounts`). The fixture's `workspace list` handler
(`tests/fixtures/topsailai_provider_conformance/main.go:58-77`) emits one row with `session_id`,
`filename`, `session_name`, `process_generation`, `state`, `agent_id`, `pid` and `project_workspace`,
and no `runtime` member. It also never inspects `--include-runtime`; the flag is not mentioned anywhere
in the fixture.

The Provider therefore finds no runtime envelope, reports no metrics, and the typed decoder rejects the
null `query_result`. The Provider is behaving correctly: an absent observation is not a measurement.

## Why it was not caught earlier

The conformance sweep iterates the closed query registry, so a newly registered query is exercised
automatically. That is the intended design and it worked: the sweep found the gap. What did not happen
is the matching fixture update, because the fixture is a separate program from the registry and nothing
requires the two to change together.

## Scope

Test infrastructure only. No production Provider behaviour is wrong, and no cluster contract is
affected. The failure is a fixture gap that makes one registered query unverifiable.

## Fix direction

Add the `runtime` envelope to the fixture's `workspace list` row, and honour `--include-runtime` so the
fixture answers the same question the real business CLI answers. The envelope must carry the message
counts the Provider reads, because a fixture that emits an empty envelope would let a wrong field name
pass conformance while silently zeroing the value — the same trap the fixture's own `list_sessions`
comment already records for `create_time`.

Do not weaken the assertion. A null `query_result` for a registered query is a real defect signal, and
the sweep is the only thing that proves the registry and the fixture agree.

## Status

Recorded, not fixed. It is outside the provider workspace refactor, which changed file locations and
build paths only.
