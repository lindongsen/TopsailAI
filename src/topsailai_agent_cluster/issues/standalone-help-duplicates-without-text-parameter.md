---
maintainer: AI
author: DawsonLin
---

# Duplicated "without text" parameter in standalone send and btw help

## Symptom

`agent-cluster-cli help send` and `agent-cluster-cli help btw` print the
`without text:` parameter twice.

```text
Parameters:
  text: message text, or a JSON object with a text field; ...
  without text: read a multi-line message and finish it with a standalone EOF line or Ctrl+D; ...
  a bare send asks Confirm send? before submitting, ...
  after a completed send: render one bounded output snapshot, ...
  without text: read a multi-line message from stdin and finish it with a standalone EOF line or Ctrl+D; ...
```

## Cause

`commandHelpCatalog` already carries a `without text:` entry for `send` and
`inject`. `nonInteractiveHelpEntry` then appends a second, stdin-specific
`without text:` entry for the `send` and `btw` cases, so the standalone surface
renders both.

The interactive surface is unaffected because `scopedHelpEntry` does not append
that second entry.

## Impact

Cosmetic only. The duplicated line states the same rule twice with slightly
different wording, which reads like two different behaviours.

## Reproduction

```text
agent-cluster-cli help send
agent-cluster-cli help btw
```

## Suggested fix

Drop the `append` in the `send` and `btw` cases of `nonInteractiveHelpEntry`, or
replace the catalog entry instead of appending to it. The stdin wording is the
one the standalone surface needs, so replacing is the smaller change.

## Status

Open. Found while adding the interactive `send`/`btw` no-options exception; not
introduced by that change and deliberately left untouched to keep the change
scoped.
