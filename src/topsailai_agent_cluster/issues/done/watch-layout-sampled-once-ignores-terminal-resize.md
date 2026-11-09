---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# Auto-refresh keeps the layout it sampled at startup, so a terminal resize is ignored

## Trigger

Found while implementing column growth into spare terminal width
(`.task/plan_20261109T165155_table-grow-into-spare-width.md`). The growth feature makes the defect
visible: an operator who widens the terminal during `watch` expects the workspace column to expand,
and it does not.

## Observed behavior

`watch` re-renders the list on a timer. The table it prints keeps the width and growth policy that
were in force when the watch controller was created. Widening the terminal during a watch run does
not grow the `PROJECT_WORKSPACE` column, and narrowing it does not re-clip the column, until the
operator leaves and re-enters the command.

## Root cause

`internal/tui/watch.go:407` samples the layout once:

```go
layout := OutputLayout(out)
```

The resulting `TableLayout` is stored in the watch controller and returned by its `TableLayout()`
method on every later tick. `OutputLayout` is never consulted again, so the terminal width and the
growth switch are frozen at construction time.

This is a stale-sample defect rather than a rendering defect. The renderer applies whatever policy it
is given, and the policy it is given is the one from the first tick.

## Why it was not caught

Every watch test drives a fixed-width writer, so the sampled value and the current value are always
equal. A test that resizes the writer between ticks would be the only way to observe the difference,
and no such test exists.

## Impact

Cosmetic, and bounded to the `watch` command. No data is lost and no command is misrouted. The
practical effect is that the growth feature appears not to work in the one surface that redraws
repeatedly, which is also the surface where an operator is most likely to resize the window.

## Suggested fix

Re-sample the layout on each tick instead of caching it, so the controller reports the current
boundary policy. The controller already re-reads the inventory on every tick, so one extra
`OutputLayout` call per tick is not a meaningful cost. A regression test should resize the writer
between two ticks and assert that the second render uses the new width.

## Resolution

Fixed. The controller no longer stores a sampled `TableLayout`. It stores a
`layoutSource func() TableLayout` and calls it inside `render`, so every render reads the current
output boundary policy. `startWatch` passes `func() TableLayout { return OutputLayout(out) }`, which
is a live read rather than a snapshot.

A function-typed field was chosen over storing the `io.Writer` and calling `OutputLayout` inside
`render`, because the controller never writes to that writer. Holding it would imply an ownership the
controller does not have, while a layout source states exactly what the controller does: it asks for
the current policy and does not own the boundary.

The same change also made `watch` collect once immediately on start, before the first tick, so the
operator sees the current inventory at once instead of waiting a whole interval. Both behaviours are
documented in `docs/cli-command-surface-rules.md`.

Guarding test: `TestWatchControllerResamplesLayoutOnEveryRender` renders at width 40, widens the
boundary between ticks, and asserts the second render exceeds 40. It fails when the layout source is
frozen at construction, with `second render widest line=40 never exceeded 40, so the resize was
ignored`.

The four tests that encoded the old timing were replaced rather than supplemented, because a test
that still delivers a tick to start the first collection would keep asserting the behaviour this
change removes.
