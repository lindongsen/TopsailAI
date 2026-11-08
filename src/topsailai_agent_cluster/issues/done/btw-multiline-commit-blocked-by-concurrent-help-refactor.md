---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# The btw multi-line commit is blocked by a concurrent help refactor

## Trigger

Human instruction (verbatim):

> commit

The commit was requested for the `btw` multi-line input change. It could not be
completed safely, because another agent is editing the same files in the same
workspace at the same time.

## Observed behavior

The `btw` multi-line change itself is complete and verified. The commit is
blocked by unrelated in-flight work in `internal/tui/help.go`.

`git diff -U0 -- internal/tui/help.go` reports 18 hunks. Only two belong to this
change:

| Hunk | Owner | Content |
|---|---|---|
| `@@ -42 +42 @@` | this change | the `inject` catalogue entry becomes `inject [text]` with the multi-line parameter |
| `@@ -214 +311,4 @@` | this change | `case "btw"` is split from `case "control"` so only `btw` advertises the stdin block |

The other 16 hunks belong to a concurrent help-formatting refactor: a new
`helpLineIndent`/`helpSyntaxColumn` constant block, `commandAliasNames`,
`standaloneAliasNames`, `helpCell`, `helpColumnWidth`, `formatHelpLine` and
`formatHelpBlock`, plus the call sites that adopt them. That is roughly 150 lines
of work that is not part of this change and is not finished.

## Root cause

Two independent changes are being made to the same file in the same working tree
at the same time. A pathspec commit stages the whole working-tree content of a
file, so committing `help.go` would sweep the concurrent refactor into this
change's commit. That would make the commit unreviewable and would attribute
someone else's unfinished work to this change.

## Second, harder consequence

The concurrent refactor changes the rendered help bytes, so the pinned digest
test in `internal/tui/unit_c_start_parse_test.go` now fails:

```text
--- FAIL: TestUnitCStartStandaloneHelpMatchesCurrentPreCContract
    standalone "" digest=44ed24064622e499a6b3c121a438db8026331c3f94130ab823eb9da41a27cda2 size=4118
    want=71b97fc7d3a32d8336e1100114d52473aca0697337acb9f9d5cfb46b97c74091/3214
```

The pinned value `71b97fc7…/3214` was correct for this change alone. The observed
`44ed2406…/4118` is produced by the concurrent refactor. Committing the observed
value would bind this change to another agent's unfinished work, and committing
the pinned value would leave the tree red. Neither is acceptable without a human
decision.

## Why this was not resolved autonomously

The choice changes what lands in the repository history and mixes two agents'
work. It is an irreversible, cross-owner decision, so it was escalated instead of
being decided unilaterally. The escalation timed out, and the configured fallback
was to record the state and wait for human coordination.

## Current state of the working tree

Clean and ready to commit, containing only this change:

- `internal/tui/multiline_input.go`
- `internal/tui/interactive_ops.go`
- `internal/tui/interactive_test.go`
- `internal/tui/unit_a_test.go`
- `src/main/agent-cluster-cli/main.go`
- `src/main/agent-cluster-cli/main_test.go`

Mixed with the concurrent refactor, so not committable as-is:

- `internal/tui/help.go` (2 hunks of this change, 16 hunks of the refactor)
- `internal/tui/unit_c_start_parse_test.go` (2 digest lines that depend on the
  refactor's output)

Unrelated files that must not be touched by this change:

- `docs/cli-command-surface-rules.md`
- `internal/tui/interactive_unknown_input.go`
- `internal/tui/interactive_unknown_input_test.go`
- `internal/tui/prompt_input.go`
- `internal/tui/style.go`
- `internal/tui/terminal_editor.go`
- `issues/cli-table-color-missing.md`
- `tests/bdd/steps_unknown_input_offer.go`
- `tests/manual/live-tmux/unknown-input-send-offer.md`

A concurrent agent already committed `e919d417 feat: return to workspace scope
on q outside workspace scope` while this change was in progress, so the tree is
moving underneath this work.

## Resolution options

1. Wait for the concurrent refactor to be committed, then recompute the digest
   against the settled output and commit. Safest, but blocking.
2. Commit the six clean files now, and commit `help.go` plus the digest test once
   the refactor lands. The tree is briefly inconsistent between the two commits.
3. Stage only the two `help.go` hunks of this change, and compute the digest in a
   temporary copy that contains only this change. This commit is green on its
   own, but the shared working tree stays red until the refactor lands.
4. Record and wait, which is the current state.

## Prevention

- Before committing, compare `git diff -U0 -- <file> | grep '^@@'` against the
  hunks this change actually produced. A hunk count larger than expected means
  another writer is active in that file.
- Treat a pinned-output digest test as a shared resource. When it fails with a
  size change rather than a small byte change, suspect a concurrent renderer
  change instead of assuming this change broke it.
- Prefer committing a logical unit as soon as it is verified, so the window in
  which a concurrent writer can collide with it stays small.

## Resolution

The human authorized the combined commit (verbatim):

> 可以提交，一起提交也没事

The blocking condition was therefore resolved by explicit human decision rather
than by waiting for the concurrent refactor. The commit includes both this change
and the concurrent help-formatting refactor.

Verification evidence for this change alone was produced before committing, in a
detached worktree at the current HEAD with only this change applied:

```text
gofmt -l internal/tui src/main/agent-cluster-cli   -> (no output)
go build ./...                                     -> BUILD_OK
go test -count=1 ./internal/tui/                   -> ok 88.071s
go test -count=1 ./src/main/agent-cluster-cli/     -> ok 0.124s
```

That proves this change is green on its own. The failures observed in the shared
working tree belong to the concurrent refactor, which was still incomplete when
the commit was made. The human accepted that state explicitly.

## Prevention (confirmed by this incident)

- Verify a change in an isolated worktree before committing a shared tree that
  another writer is modifying. This separated this change's failures from the
  concurrent writer's failures and prevented a false root-cause conclusion.
- A pinned-output digest test is a shared resource. A size change rather than a
  small byte change indicates a concurrent renderer change, not a defect in the
  change under review.
