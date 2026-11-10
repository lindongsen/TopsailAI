---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# The batch2 help fixture hardcodes the start help body and drifted from it

## Trigger

Found while resolving a `git pull` merge conflict on branch `staging`. After the four conflicted
files were resolved, `make test-unit` failed with six failures, all in `internal/tui`:

```text
--- FAIL: TestUnitCBatch2CommandInterrupt
--- FAIL: TestUnitCBatch2WatcherBarrier
--- FAIL: TestUnitCBatch2Priority
--- FAIL: TestUnitCBatch2QueuedTermination
--- FAIL: TestUnitCBatch2CancelAllowsQueuedStart
--- FAIL: TestUnitCBatch2PrefetchedHelpQuit
```

The failures are **not** caused by the merge. The same six tests fail on a pristine `HEAD` tree
exported with `git archive HEAD` into a throwaway directory, so the defect predates the merge.

## Observed behaviour

`TestUnitCBatch2PrefetchedHelpQuit` compares the rendered `help` output against
`d.ready + unitCBatch2HelpText() + "workspace> " + unitC19MainHelp() + "workspace> "`. The rendered
output contains two extra parameter lines that the fixture does not:

```text
+  after a completed start: force one collection for the selected endpoint, then start the same live tail as logs -f for the session that appeared, so the new session is watched without typing logf; the tail is armed after the collection because the launched session generation is minted by it, and any key stops it
+  no tail is armed when no session appeared yet, when more than one appeared, when the generation is unverified, or when the client cannot stream; the reason is reported as a diagnostic, and a client that cannot stop a tail renders one bounded snapshot instead
```

The other five failures report the same mismatch through their own `C19` assertions, because they
all render the same `help` body.

## Root cause

Commit `8e92ee7e` ("feat: follow the launched session after an interactive start") added those two
parameter lines to the `start` entry of `commandHelpCatalog` in `internal/tui/help.go`, and added
`internal/tui/start_auto_follow_test.go` to cover the new behaviour. It did not update
`unitCBatch2HelpText()` in `internal/tui/unit_c_batch2_driver_test.go:431-439`, which reproduces the
same parameter list as a literal string:

```go
return first + "Parameters:\n" +
    "  endpoint: endpoint ID\n  resource: compatibility resource identifier\n ... " +
    "  an empty multi-line task is rejected instead of submitting nothing\n  --json: rejected in interactive mode\nExamples:\n" + ...
```

The fixture is a second copy of the help body, so the help body and the fixture can disagree. The
help body is the source of truth and the fixture is the copy, so the fixture is what is wrong.

## Why it was not caught

The new test in `8e92ee7e` asserts the auto-follow behaviour, not the help text, so it passed. The
only tests that assert the full `start` help body are the batch2 tests, and they were not part of
that change's verification scope. A green run of the new test therefore said nothing about the
fixture it invalidated.

## Impact

`make test-unit` fails, so the component-level unit suite cannot be used as a green gate. The
product behaviour is correct: the rendered help really does describe the auto-follow, which is what
`docs/cli-command-surface-rules.md` and `docs/agent-cluster-adapters.md` now document. Only the
fixture is stale.

## Suggested fix

Update `unitCBatch2HelpText()` to include the two new parameter lines, in the same position the
catalog emits them, so the fixture matches the help body again. Prefer deriving the expected text
from `commandHelpCatalog` where the test only needs the parameter block, so a future help edit cannot
silently invalidate the fixture a second time. Do not weaken the assertion to a substring match: the
whole point of these tests is to pin the exact rendered body.

## Verification

```text
cd /TopsailAI/src/topsailai_agent_cluster
go test ./internal/tui/ -run 'TestUnitCBatch2' -count=1
make test-unit
```

## Resolution

Resolved on 2026-11-10. The fixture no longer holds a second copy of the help body.

`unitCBatch2HelpText()` now derives the parameter block and the examples from
`commandHelpCatalog["start"]` and renders them with the same `Parameters:` / `Examples:`
layout `printCommandDetail` uses, so a future catalog edit cannot invalidate it again. The
`Project launch:` paragraph stays literal, because it is not catalog data: it is appended by
`printInteractiveStartHelp` and has no other representation to derive from.

Deriving the fixture alone would have removed the only assertion on what the operator reads,
because no other test pinned the `start` help wording. That would have replaced a stale test
with a tautological one: the fixture would agree with the catalog by construction, so a
catalog edit that deleted the auto-follow documentation would keep every derived assertion
green. The fix therefore pairs the derivation with a new literal content test,
`internal/tui/start_help_pins_auto_follow_test.go`, which asserts the two auto-follow
parameter lines as exact whole lines, asserts that they sit inside the parameter block
between the empty-task rejection and the `--json` rejection, asserts their order, and
asserts that they really are catalog parameters rather than text the renderer emitted from
somewhere else.

The division of responsibility is now explicit: the batch2 tests police concurrency and
transcript shape, and the content test polices the documented behaviour. Neither covers for
the other.

### Verification

```text
gofmt -l internal/tui/                      -> clean
go vet ./internal/tui                       -> clean
go test ./internal/tui -run 'TestUnitCBatch2' -count=1   -> ok
go test ./internal/tui -run 'TestStartHelp' -count=1     -> ok
make test-unit                              -> ok (every component)
```

The new tests were observed to fail before being trusted. Deleting the first auto-follow
parameter from `commandHelpCatalog` produced:

```text
--- FAIL: TestStartHelpPinsAutoFollowParameters
    start help is missing the auto-follow parameter line "  after a completed start: ..."
--- FAIL: TestStartHelpAutoFollowParametersAreCatalogParameters
    catalog start parameters do not contain "after a completed start: ..."
```

`TestUnitCBatch2PrefetchedHelpQuit` stayed green under that same break, which confirms the
intended decoupling: the concurrency tests no longer fail because of help wording. The
catalog was restored immediately and `git diff --stat internal/tui/help.go` was empty
afterwards, so the broken build was never mistaken for the real one.
