---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-19
---

# The help omitted `overloaded` while the protocol returned it

## Symptom

`connector-cli --help` listed nine error codes and named three retryable ones. The
protocol defines ten failure codes and marks four retryable:

```
internal/protocol/codes.go
  CodeOverloaded Code = 1010        -> Name() == "overloaded"
  Retryable() includes CodeOverloaded
```

`overloaded` was absent from both the code list and the retryable sentence.

## Why it matters

The help is the only documentation a CLI user reads. A caller who receives
`overloaded` finds no entry for it and cannot tell whether it is a refusal to fix or
a condition to wait out. The retry sentence is worse: it named three of four
retryable codes, so a reader who trusted it would give up on the one condition that
is guaranteed to clear on its own.

The code was not new. `internal/server/handler.go` returns `ErrOverloaded` and
`ErrChannelBusy`, and `docs/API.md` line 324 documents `overloaded`. So the help
contradicted the API document, and the API document was right.

## Root cause

The help's code list was written by hand from the codes that existed when the help
was written. `overloaded` was added later, in commit `91c41411 feat: add a retryable
overload code`, and nothing connected the protocol's code set to the help text.

## Detection gap

No test read the help and compared it with the protocol. The help tests asserted
that specific strings appeared, which is satisfied by a list that is missing an
entry. A test that asserts "these nine strings are present" cannot fail when a tenth
code is added.

## Resolution

`help.go` now lists `overloaded` with its meaning and names it in the retryable
sentence.

Two guard tests were added, and both read the protocol source rather than repeating
a list:

- `TestHelpListsEveryErrorCode` parses every `return "name"` in `codes.go` and
  asserts the help names each one. `success` and `unknown` are excluded: the first
  is documented as status 0, the second is the default branch for an unrecognised
  code rather than a code the protocol returns.
- `TestHelpNamesEveryRetryableCode` asserts the retry sentence names all four
  retryable codes and that the sentence exists.

A hardcoded list in the test would have drifted exactly as the help did: whoever
added the code would have updated the test, and the test would then have agreed with
the help while both disagreed with the protocol.

Mutation evidence: removing the `overloaded` entry and the word from the retry
sentence fails both tests with `help does not name the error code "overloaded"` and
`help does not name the retryable code "overloaded"`.

## The same gap in the skill

`skills/connector-client/SKILL.md` had the identical omission: no `overloaded` row
in its error-code table and three codes in its retry advice. Both were fixed in the
same change. This is the second time a capability reached the code and the API
document but not the skill, so the skill is part of the change rather than a
follow-up.
