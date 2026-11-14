---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: fixed
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

Implemented in `workspace/input_tool.py::input_multi_line`. The prompt print and
its `sys.stdout.flush()` moved from before the retry loop to the start of every
retry attempt. The retry itself stays a bounded `for _attempt in
range(MAX_INPUT_RETRY_COUNT)` loop, so the reprint is bounded by the same count
that `68e5e80a` introduced.

`input_one_line` needed no change: it passes `tips` into `_input(tips)`, so
`input()` already prints the prompt on every retry.

## Verification

Verified at `efadf5c4` with the fix applied.

- The failing BDD scenario passes without weakening its assertions or adding a
  skip: `tests/bdd/test_two_layer_message_verification.py` reports
  `3 passed` on three consecutive runs (55.36s, 54.26s, 56.76s).
- The bounded retry behavior from `68e5e80a` still holds. A hook that consumes
  every message still ends with
  `EOFError: no usable multi-line input after 999 attempts`, and the prompt is
  printed exactly `MAX_INPUT_RETRY_COUNT` times instead of without bound.
- Two focused unit tests were added to
  `tests/unit/test_topsailai_workspace_input_tool.py`:
  `test_prompt_is_reprinted_after_a_hook_consumes_a_message` and
  `test_prompt_reprint_stays_bounded_when_every_message_is_consumed`.
- Negative control: reverting only the prompt move makes both new tests fail
  with `AssertionError: 1 != 2` and `AssertionError: 1 != 999`, which reproduces
  the original symptom as a counted difference. Restoring the fix returns the
  file to `76 passed`.
- CLI BDD full suite: `141 passed` in 31.60s.
