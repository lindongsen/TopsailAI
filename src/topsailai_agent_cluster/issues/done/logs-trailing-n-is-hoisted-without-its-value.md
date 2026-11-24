---
maintainer: AI
author: DawsonLin
status: done
---

# A trailing `-n` is hoisted without its value, so the bound becomes a positional

## Symptom

`agent-cluster-cli logs endpoint-1 res_abc -n 3` reported
`usage: logs <endpoint-id> <session-id>` instead of bounding the output. The same
command with `--lines 3` worked.

## Root cause

Two independent defects produced one symptom, and fixing only the first left the
second in place.

1. `-n` was never registered on the standalone surface (`main.go` registered only
   `flags.Int("lines", ...)`), so the flag did not exist at all.
2. `hoistTrailingFlags` moves a trailing global option in front of the command so
   `logs ep res --lines 3` parses. It decides what counts as a global option from
   `globalOptionNames`, and `"n"` was absent from that map. Once `-n` was
   registered, a trailing `-n` was therefore hoisted **without its value**: `3`
   stayed behind as a positional, so `logs` received three arguments and reported
   its usage line.

## Detection gap

The first test written for the fix built its own `flag.FlagSet` and called
`reconcileLines` directly. That test passes whether or not `main.go` registers
`-n`, and whether or not `globalOptionNames` contains it, because it never
exercises the real parser or the hoisting step. It was a test double that omitted
the behaviour under test.

The defect was found only after the tests were rewritten to drive `runWithIO`, the
real entry point. Removing `"n"` from `globalOptionNames` then reproduced the
reported usage error exactly.

## Fix

- `linesShort := flags.Int("n", 0, "short form of --lines")` registered beside
  `--lines`.
- `"n": true` added to `globalOptionNames`, so a trailing `-n` is hoisted together
  with its value.
- `reconcileLines` folds the two spellings into one value after parsing, using the
  parser's explicit-set record because `--lines` carries a default of 100 and a
  value comparison cannot distinguish "not supplied" from "supplied the default".
- `resolveInteractiveLines` treats `-n` as explicit, so a REPL started with
  `-n 50` is rejected for the same reason `--lines 50` is.

## Verification

- `TestRealParserAcceptsTheShortLinesForm`,
  `TestRealParserRejectsDisagreeingLinesSpellings` and
  `TestRealParserAcceptsATrailingShortLinesForm` drive `runWithIO`.
- Renaming the registration to `n-unused` failed all three.
- Removing `"n"` from `globalOptionNames` reproduced
  `usage: logs <endpoint-id> <session-id>`.
- Live: `logs ac.ai-dev res_50da... -n 3` exits 0 with real output;
  `-n 3 --lines 5` exits 2 with `--lines 5 and -n 3 disagree; state the bound once`.

## Lesson

A flag is reachable only when three separate declarations agree: the registration,
the hoisting registry, and the reconciliation. A test that builds its own flag set
proves none of them.
