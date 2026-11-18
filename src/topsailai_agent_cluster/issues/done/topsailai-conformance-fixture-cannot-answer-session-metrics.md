---
maintainer: AI
author: DawsonLin
status: done
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

## Resolution

Fixed in `a1bf2582 test: answer session metrics from the conformance fixture`.

### The fixture gap

`providers/topsailai/tests/fixtures/topsailai_provider_conformance/main.go` now parses
`--include-runtime` from `args[1:]` and attaches the `runtime` envelope only when the flag is present.
The envelope carries `state: "ok"`, `pid`, and `data: {ok: true, user2agent: {messages: 5},
agent2llm: {messages: 11}}`. The counts are unequal and non-zero on purpose: a Provider that read the
wrong field name would report a measured zero, and a zero is a legal count.

Emitting the envelope only under the flag is deliberate. A fixture that always emitted it would let a
Provider that dropped the flag pass conformance while the MESSAGES column went blank in production.

### Two corrections to this issue's own text

1. **The file path moved.** The issue cites `tests/fixtures/topsailai_provider_conformance/main.go:58-77`.
   The provider workspace refactor (`c34ce509`) moved it to
   `providers/topsailai/tests/fixtures/topsailai_provider_conformance/main.go`. The old path is absent
   at HEAD.
2. **The Provider sends no `-s` selector.** The issue states the read is
   `workspace list --json --local -s SESSION --include-runtime`. The actual call is
   `providers/topsailai/src/read.go:134`:
   `[]string{"workspace", "list", "--json", "--local", "--include-runtime"}`. There is no `-s`. The
   fixture therefore applies no selector, and a comment in the fixture records why.

### The assertion was vacuous, and the fixture fix alone did not close the trap

This issue's own Fix direction warns that "a fixture that emits an empty envelope would let a wrong
field name pass conformance while silently zeroing the value". That warning was correct, and it applied
to the existing test as well.

`TestProviderTypedQueryConformance` called `providercli.DecodeQueryResult` and discarded the result. It
only checked that decoding succeeded and that no Cluster-owned field name appeared.
`SessionMetricsResult.validate()` rejects negative counts and counts above `protocol.MaxMessageCount`,
so **a zero passes**. The fixture's non-zero values were never compared against anything.

Proven by deliberate breakage: renaming `"user2agent"` to `"user_to_agent"` in the fixture envelope left
the suite **green** (`ok ... 12.691s`). The trap this issue describes was still open after the fixture
was repaired.

The sweep now asserts the counts. `assertMeasuredMessageCounts` decodes the typed result and
`assertNonZeroCounts` requires both positions to be non-zero, for `session.metrics` and for every member
of `session.metrics.batch`. Both positions are checked separately, because a Provider that swapped the
two fields would still report two non-zero numbers.

The exact numbers are not asserted because the sweep runs against more than one target: the mock answers
`inbound=7 outbound=3` (`providers/mock/src/main.go:414`) and the TopsailAI fixture answers
`inbound=5 outbound=11`. A hardcoded pair would break one of them.

### Verification

| Check | Result |
|---|---|
| `make test-conformance` (mock target, 7/3) | `ok ... 3.526s` |
| `make test-provider-topsailai-conformance` (fixture target, 5/11) | `ok ... 12.655s` |
| `gofmt -l` on both changed files | clean |
| `go vet ./internal/providerconformance/` | clean |

Deliberate breakages, all restored:

| Breakage | Result |
|---|---|
| `if false && includeRuntime` (drop the flag handling) | `decode typed query result: query_result must not be null` — this issue's exact symptom |
| `"user2agent"` → `"user_to_agent"` | `message counts inbound=0 outbound=11, want both non-zero: a zero count means the Provider never read the value` — the trap this issue warned about, now caught |

The second breakage is the one that matters: before the assertion was added it passed silently.

### Limitation

The non-zero assertion cannot distinguish "the Provider read the right field" from "the Provider read a
different non-zero field". It closes the silent-zeroing trap, which is what this issue named. Proving
field-level fidelity would require asserting the exact counts, which the multi-target sweep cannot do
without a per-target expectation table.
