---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: open
---

# Issue: A slash command no longer reprints the prompt after it is consumed

## Trigger

Regression testing of the project-workspace work found one BDD scenario failing
deterministically at `6fec8642`:

```
tests/bdd/test_two_layer_message_verification.py::test_agent_chats_retains_three_multiline_direct_exchanges
```

Reproduce with:

```
PYTHONPATH=/TopsailAI/src python -m pytest \
  "tests/bdd/test_two_layer_message_verification.py::test_agent_chats_retains_three_multiline_direct_exchanges" \
  -q --no-header -p no:cacheprovider
```

Observed: `1 failed in 135.64s`, `AssertionError: timed out waiting for new 'Your Turn'`
raised at `tests/bdd/two_layer_message_harness.py:85`.

## Impact

After a slash command such as `/ctx.history` or `/agent.messages` is consumed, the
interactive CLI stops displaying the end-of-turn prompt. The user sees the command
output and then nothing, so the waiting state is invisible and the session looks
hung. Any automation that waits for a fresh prompt occurrence also stalls.

The captured pane shows exactly three prompt occurrences and no second business
turn:

```
>>> Your Turn: (pid=751629)  Press 'CTRL D' or Enter 'EOF' for end
DIRECT_TASK_1
...
>>> Your Turn: (pid=751629)  Press 'CTRL D' or Enter 'EOF' for end
/agent.messages
...
>>> Your Turn: (pid=751629)  Press 'CTRL D' or Enter 'EOF' for end
/ctx.history
...
```

`DIRECT_TASK_2` never appears, so the scenario cannot reach its second exchange.

## Confirmed root cause

Commit `68e5e80a` ("fix: bound the interactive prompt loops on a closed input
channel") replaced the recursive retry in `workspace/input_tool.py::input_multi_line`
with a bounded `for _attempt in range(MAX_INPUT_RETRY_COUNT)` loop.

The prompt is printed once, before that loop:

```
print(tips + " Press 'CTRL D' or Enter 'EOF' for end")
sys.stdout.flush()
for _attempt in range(MAX_INPUT_RETRY_COUNT):
```

The previous implementation ended with `return input_multi_line(tips, hook)`, so every
retry was a new call and reprinted the prompt. The bounded loop keeps the retry inside
one call, so a message consumed by `hook_message` now continues without reprinting.

A probe confirms the behavior change directly. With `hook_message` forced to return
`True` and `_input` returning a fixed line, the prompt print count is:

| Tree | Prompt prints | Outcome |
|---|---|---|
| `68e5e80a^` (before the change) | 998 | `RecursionError` |
| `6fec8642` (current HEAD) | 1 | `EOFError: no usable multi-line input after 999 attempts` |

The old tree reprinted the prompt on every retry because each retry was a new call.
The bounded loop keeps the retry inside one call, so a message consumed by
`hook_message` now continues without reprinting.

## Attribution

This is **not** caused by the project-workspace work in session `wa-bbe51ff8246b`.

Bisect evidence, each run repeated three times:

| Commit | Result |
|---|---|
| `8b557720` | passed 3/3 (15.28s) |
| `68e5e80a` | failed (75.69s) |
| `8088a60c` (session's final commit) | passed 3/3 (18.26s, 17.95s, 15.95s) |
| `6fec8642` (current HEAD) | failed (135.64s, 191.21s) |

`68e5e80a` is an ancestor of `6fec8642`, so the regression is still live.

## Required behavior

A message consumed by a hook must leave the CLI in a state where the end-of-turn
prompt is displayed again. The prompt belongs to the retry path, not only to the
first attempt of one call.

## Resolution

Not implemented. The fix must decide whether the prompt is reprinted per retry
attempt inside `input_multi_line`, or whether the retry is moved back to a caller
that re-enters the function. Either way the bounded retry count introduced by
`68e5e80a` must be preserved, because it is what stops the unbounded prompt growth
that produced the original disk-growth incident.

## Verification

Pending. Acceptance requires:

- The failing BDD scenario passes without weakening its assertions or adding a skip.
- The bounded retry behavior from `68e5e80a` still holds: a closed input channel
  must not reprint the prompt without bound.
- A focused unit test asserts that a hook-consumed message reprints the prompt,
  and a negative control proves the assertion fails when the reprint is removed.
