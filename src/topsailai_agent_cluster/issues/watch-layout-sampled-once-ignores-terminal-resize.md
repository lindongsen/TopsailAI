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

## Status

Recorded, not fixed. It is outside the scope of the column-growth change, which deliberately keeps
its diff to the growth rule and the output boundary.
