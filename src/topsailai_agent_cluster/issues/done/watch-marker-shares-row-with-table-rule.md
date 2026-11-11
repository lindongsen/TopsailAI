---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# The interactive `watch` marker shares its row with the table rule

## Trigger

Human report, wording normalized, meaning preserved:

> cli 里面的 `workspace.watching>` 这个显示信息和横线在一起了，不好看，它应该要换行。

## Observed behavior

Inside `agent-cluster-cli -i`, every `watch` refresh printed the scope marker and the table's leading
full-width rule on one terminal row:

```text
workspace.watching> ────────────────────────────────────────────────────────────
```

The marker is a status line and the rule is table framing, so the two read as one line and the marker
no longer looks like a label of its own.

## Root cause

`replWatch.Idle` (`internal/tui/watch.go:467-471`) rendered the marker into a buffer and appended the
rendered table bytes directly:

```go
var marker bytes.Buffer
if err := RenderWatchingPrompt(&marker, w.state.Scope, w.state.Invalidated, w.controller.color); err != nil {
    return nil, err
}
payload := append(marker.Bytes(), result.output...)
```

`RenderWatchingPrompt` ends with a single space and no newline (`internal/tui/style.go:343-348`),
because it is a prompt and the editor owns the row after it. `writeFramedTable` always starts with a
full-width rule (`internal/tui/table.go:390-392`), because the table is self-framing. Neither side
terminates the marker row, so the rule was appended to it.

The two components are each correct in isolation. The defect lives only in the composition, which is
why no renderer test could see it.

## Detection failure

`TestReplWatchPrefixesEveryRenderedRefresh` (`internal/tui/watch_test.go:471`) asserted
`strings.HasPrefix(payload, "endpoint[node/ep-1].watching> "+table)`, which is exactly the collision:
the expected value was the marker and the table concatenated with no separator. The test was green, so
the single-row form looked intentional and verified.

The BDD step (`tests/bdd/steps_watch.go:55`) asserted only that `workspace.watching> ` appears somewhere
in the captured output, which stays true whether or not the row is terminated.

## Impact

Cosmetic only. No state, routing or command behaviour changes, and the marker text itself is unchanged.

## Resolution

Fixed on 2026-11-11 with a minimal change:

1. `internal/tui/watch.go`: the marker row is terminated with one newline before the table bytes are
   appended, so the marker owns its row and the table keeps its existing framing. The prompt renderer,
   the table renderer, the stop message and the suppression comparison are unchanged.
2. `internal/tui/watch_test.go`: the existing prefix test now expects the marker followed by a newline,
   and a new `TestReplWatchMarkerRowCarriesNoTableRule` asserts the marker row contains no rule
   character.
3. `tests/bdd/steps_watch.go`: the armed step now also asserts every rendered marker is followed by a
   line terminator, so the shipped binary is checked through a real PTY rather than only in-process.

Verification: both unit tests fail against the pre-fix source with the reported symptom
(`marker row="workspace.watching> ────────────"`), and the BDD step fails through the real binary with
`watch marker shares its row with the table`. All three pass after the fix. The targeted BDD scenario
`interactive_auto_refresh_stops_on_the_first_keypress` passes.

The eight `internal/tui` failures present in the full package run (`TestAvailableCommandsUseStableOrder`,
`TestCompletableCommandsAddOnlyMultiCharacterAliases`, `TestHelpOverviewKeepsScopeRestrictions`,
`TestLogsIsUnavailableInWorkspaceScope`, `TestSendIsUnavailableOutsideSessionScope`,
`TestSendPrefixIsRejectedOutsideSessionScope`, `TestUnitCBatch2PrefetchedHelpQuit`,
`TestUnitCStartStandaloneHelpMatchesCurrentPreCContract`) belong to a concurrent `clean` command change
in the same package. They reproduce identically with this change reverted, so they are not caused by it.
