---
maintainer: AI
author: DawsonLin
---

# Duplicated "without text" parameter in standalone send and btw help

## Symptom

`agent-cluster-cli help send` and `agent-cluster-cli help btw` printed the
`without text:` parameter twice.

## Cause

`commandHelpCatalog` already carries a `without text:` entry for `send` and
`btw`. `nonInteractiveHelpEntry` then appended a second, stdin-specific
`without text:` entry for the `send` and `btw` cases, so the standalone surface
rendered both.

The interactive surface was unaffected because `scopedHelpEntry` does not append
that second entry.

## Impact

Cosmetic only. The duplicated line stated the same rule twice with slightly
different wording, which read like two different behaviours.

## Resolution

Both cases now replace the interactive parameter list instead of appending to
it, so the standalone surface renders exactly one `without text:` entry.

- `btw` was fixed in `0c4da135` (the `inject` removal unit), because that unit
  already rewrote the standalone `btw` entry.
- `send` was fixed in `4cf44289`, which applies the same replacement to the
  `send` case and states the standalone-only parameters (`endpoint`,
  `resource`, `generation`, `--json`) explicitly.

## Verification

```text
$ agent-cluster-cli help send | grep -n 'without text'
4:Description: send a message to one session; without text it reads a multi-line message from stdin
9:  without text: read a multi-line message from stdin and finish it with a standalone EOF line or Ctrl+D; the terminator is never part of the message

$ agent-cluster-cli help btw | grep -c 'without text'
1
```

Line 4 is the description's natural wording, not a parameter entry. The
parameter list contains exactly one `without text:` line.

`go test ./internal/tui/ ./src/main/agent-cluster-cli/` passes after the change.
