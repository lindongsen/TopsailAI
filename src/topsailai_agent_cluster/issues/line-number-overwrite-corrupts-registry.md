---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# Chained line-number edits corrupted the BDD feature registry

## Trigger

A file is edited by replacing a line range, then edited again using a line number
remembered from before the first edit. The second edit lands on the wrong line
because the first edit changed the line count.

## Observed behavior

While registering the output follow feature, `tests/bdd/suite_test.go` was edited
by replacing one feature path with two lines. A follow-up edit used a line number
taken from the pre-edit file. The result was:

- `bidirectional_channel.feature` appeared twice in the path list.
- `unknown_input_offer.feature` disappeared entirely.

The corruption was silent: the file still parsed, the suite still compiled, and
only a later read of the file revealed the duplicate and the missing entry. It
was repaired by reading the file and rewriting the affected slice with boundary
assertions.

The same failure mode occurred four times during this task in different files:
a struct lost a field, a brace landed in the wrong place, a block was duplicated,
and a `case` header was duplicated while a closing brace was deleted.

## Impact

- A dropped feature path means those scenarios silently stop running. The suite
  still reports success, so the loss is invisible in CI.
- A duplicated path means the same scenarios run twice, inflating the scenario
  count and hiding the fact that coverage did not actually grow.
- Both defects are in test infrastructure, so they weaken every later
  verification rather than one feature.

## Root cause

Line-number replacement is positional, not semantic. The tool has no knowledge of
what the lines mean, and it does not re-read the file between calls. Any edit that
changes the number of lines invalidates every line number obtained before it, so
chaining edits from a remembered number is unsafe by construction.

The deeper cause is that the edit was applied as a range replacement to a list
whose entries are semantically independent, when the intent was "add one entry".
A whole-file write, or an edit anchored on the entry text rather than its line
number, cannot produce a duplicate or a deletion.

## Proposed resolution

- Write new files whole rather than by line range.
- When editing an existing file, re-read it immediately before each edit and
  derive the line number from that read, never from an earlier one.
- Prefer edits anchored on unique surrounding text over bare line numbers, so the
  edit fails loudly when the anchor is missing instead of landing on a neighbour.
- After any edit to a registry or list, read the file back and assert the expected
  entry count and the presence of every expected entry.
- For a list of independent entries, add or remove one entry rather than
  replacing a range.

## Verification

- A read-back check after the edit asserts the exact set of feature paths, so a
  duplicate or a missing entry fails immediately.
- The BDD suite reports the expected scenario count; a drop in count is treated as
  a failure rather than a smaller run.
- Review of the diff confirms the change is an addition, with no unrelated line
  removed.
