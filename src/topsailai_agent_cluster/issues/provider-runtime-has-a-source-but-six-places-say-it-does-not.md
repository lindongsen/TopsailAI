---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# `provider_runtime` works, but six places still say it has no source

## Trigger

Asked by the human on 2026-11-19, wording normalized, meaning preserved:

> So where does `provider_runtime` come from?

The question was asked right after the `metafile` investigation, where `provider_runtime` was
described as a reserved seam with no source. That description is wrong.

## Answer: it comes from the provider's runtime observation

Two provider paths fill it, and which one runs depends on whether the caller supplied an exact row.

| Path | Provider entry | Site |
|---|---|---|
| exact row with a PID | `topsailai runtime info -s SESSION -p PID`, the `runtime` member | `providers/topsailai/src/query.go:743-762` |
| no exact row, or PID zero | `topsailai workspace list --json --local -s <sid> --include-runtime`, `items[row].runtime` | `providers/topsailai/src/query.go:898` |

The exact-target path is the one most reads take, because the CLI passes the inventory row's
`provider_target` (`internal/tui/commands_info.go:57`, `internal/tui/detail.go:84`), and that slot
carries the PID (`providers/topsailai/src/read.go:307-309`).

The fallback path selects its row with `runtimeRow` (`query.go:669`), which prefers a non-task row
because only the session row owns the control channel; a task row's runtime is reported as
unsupported. This is the same selector the `MESSAGES` column uses, so the two surfaces cannot
disagree about which row they read.

Both paths forward the bytes unchanged. The bound is `maxMetricsBytes = 1 << 20`
(`providers/topsailai/src/query.go:29`).

## Verified live

```text
$ topsailai workspace list --json --local -s wa-74a99df8715a --include-runtime
items[0].runtime = {"state":"ok","error_code":null,"pid":114567,
  "data":{"agent2llm":{"messages":59},"model":{"max_tokens":30000,
  "name":"DeepSeek-V4-Flash-Preview"},"ok":true,"session":{"ephemeral":false,
  "id":"wa-74a99df8715a"},"tool_calls":{"total":27},"tools":{"available":24},
  "user2agent":{"messages":2}}}

$ agent-cluster-cli info wa-74a99df8715a
provider_runtime:
  data:
    agent2llm:
      messages: 59
    ...

$ agent-cluster-cli info wa-74a99df8715a --json
top-level keys: ['endpoint_id', 'provider_metadata', 'provider_runtime', 'session']
```

Both surfaces carry real data. `provider_runtime` is populated, not reserved.

## The defect: six stale claims, two of them locked by tests

| # | Site | Claim | Reality |
|---|---|---|---|
| 1 | `internal/tui/help.go:78` | "provider_runtime is a reserved section with no source yet, so it prints not reported" | it has a source and prints the envelope |
| 2 | `internal/adapter/genericcli/adapter.go:690` | "The runtime document is left as the provider reported it, which today is empty" | it is not empty |
| 3 | `providers/topsailai/src/query.go:192` | "ProviderRuntime is the reserved seam: this provider reports nothing for it today" | it reports the envelope |
| 4 | `providers/mock/src/main.go:493-495` | "provider_runtime is deliberately absent, because it is a seam with no source yet" | the mock omits a field the real provider fills |
| 5 | `tests/bdd/steps_endpoint_query_permission.go:410-415` | asserts `outcome.providerRuntime == ""` | the assertion requires the seam to stay empty |
| 6 | `providers/topsailai/src/query.go:190-195` | "ProviderMetadata is this provider's own `session info --json` record" | on the exact branch it is the `runtime info` document minus its `runtime` member |

Site 1 is the worst of the first three, because it is what the operator reads. It tells them the
section is empty by design, so an operator who sees real data there has to decide whether the help or
the output is wrong.

Sites 4 and 5 are worse than site 1, and they were missed by the first version of this record. Site 5
is an executable assertion, not prose: it fails the suite for any correct implementation, and its
failure message says the Cluster "invented a runtime observation nobody decided on", which points the
investigation at the Cluster rather than at the stale assertion. Site 4 is the fixture that makes site
5 pass, so the two must be corrected together.

Two tests currently lock the wrong claim:

- `internal/tui/info_help_test.go:63-79` (`TestInfoHelpStatesRuntimeHasNoSource`) asserts the help
  contains `no source yet`. Any correction of site 1 fails this test.
- `tests/bdd/steps_endpoint_query_permission.go:410-415` asserts the runtime seam is empty. Any
  correction of the provider or the mock fails this scenario.

This is the same class as the recorded lesson about a test locking a defect in place: the test
converts the wrong claim into a verified requirement, so the defect survives review and the fix
appears to be the regression.

## How it happened

`git log -S` ordering:

| Commit | Date | Effect |
|---|---|---|
| `3a6bf586` | 2026-11-16 | help advertises the sections; `provider_runtime` had no source yet, so the sentence was true |
| `985fcd13` | 2026-11-16 | provider answers `session.detail` |
| `d3651b37` | 2026-11-18 | **adds `runtimeEnvelope`**, so the sentence becomes false |
| `4f4a3db6` | 2026-11-18 | renames the seams, keeps the stale comment |
| `ecb58c1d` | 2026-11-18 | moves the provider into its own workspace, keeps the stale comment |
| `078879a2` | 2026-11-20 | adds the exact-target `runtime info` path, keeps all six stale claims |

`d3651b37` touched only `query.go`, `read.go` and `read_test.go`. It added the source and did not
revisit the help text, the adapter comment or the `detailResult` comment, so the sentence that was
true on 2026-11-16 stayed in place after it became false. `078879a2` repeated the same omission on a
larger scale: it changed the provider's read path and left every consumer-side description untouched.

## Why the empty case still exists

The empty case is real, but its reason is different from what the help says. The fallback path passes
`--local`, so a session recorded on another host has no row in this host's read and the seam stays
empty. That is an unobservable row, not a missing feature, and
`TestSessionDetailReportsNoRuntimeForAnUnobservableRow`
(`providers/topsailai/src/read_test.go:924`) covers it. The help should describe that case, not a
seam with no source.

## Scope of the correction

Six sites, two tests, and one fixture. They must land as one logical unit, because correcting the
prose alone leaves the suite asserting the opposite of the prose:

| Site | Change |
|---|---|
| `internal/tui/help.go:78` | describe the unobservable-row case instead of "no source yet" |
| `internal/tui/info_help_test.go:63-79` | assert the new sentence, and rename the test to match what it proves |
| `internal/adapter/genericcli/adapter.go:690` | state that the document is forwarded verbatim, without claiming it is empty |
| `providers/topsailai/src/query.go:192` | state that the provider reports the runtime member |
| `providers/topsailai/src/query.go:190-195` | describe both branches, so the metadata seam is not called the `session info` record unconditionally |
| `providers/mock/src/main.go:493-495` | emit a `provider_runtime` fixture so the seam is exercised |
| `tests/bdd/steps_endpoint_query_permission.go:410-415` | assert the fixture value arrives verbatim instead of asserting emptiness |

The mock change is what makes the BDD assertion meaningful. Today the scenario cannot distinguish "the
Cluster dropped the runtime document" from "the provider never sent one", because the fixture sends
none.

## Status

Root cause confirmed. No code changed. Awaiting execution of the correction above.
