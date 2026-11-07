---
maintainer: AI
author: DawsonLin
---

# A lone Escape key still ends the interactive session

## Trigger

Found while verifying the fix for `interactive-repl-exits-on-unhandled-control-key.md`. That fix made
unhandled control runes ignorable, but the same class of failure remains for a bare Escape keystroke.

## Observed behavior

Pressing Escape once, with no following byte, terminates the interactive REPL. The terminal returns to
the shell with:

```text
unsupported or malformed terminal key: unsupported or malformed terminal key: incomplete escape timeout
```

## Reproduction

Run `agent-cluster-cli -i`, type any partial command, press Escape, then continue typing. The session is
already gone, so the remaining keystrokes are interpreted by the parent shell.

## Root cause

`internal/tui/terminal_editor.go:227-229` converts the escape timeout into the fatal sentinel:

```go
if !r.escapeDeadline.IsZero() && time.Now().After(r.escapeDeadline) {
    return 0, fmt.Errorf("%w: incomplete escape timeout", errLineKey)
}
```

`internal/tui/terminal_editor.go:106-117` treats every error that is not `errIgnoredKey` as fatal, so this
path returns out of the editor and ends the REPL.

The archived issue proposed exactly this case in its step 3: "otherwise treat it as ignorable too,
because a stray escape byte is not a reason to destroy the session." The implemented fix covered only
decoded control runes, so step 3 remains open.

## Why the current fatal behaviour is not justified here

The archived resolution argues that malformed escape sequences stay fatal because "a truncated or
oversized escape sequence leaves the input stream in an unknown position". That reasoning does not hold
for the timeout branch: when the 300 ms escape deadline expires with no further byte, the reader knows
the sequence is complete and that nothing is pending. The stream position is known, so the keystroke can
be discarded safely. The genuinely unknown-position cases are the mid-sequence read failures
(`line_keys.go:91`, `:100`) and the oversized sequence (`line_keys.go:110`), which should stay fatal.

## Impact

- Operator-visible: Escape is a natural "cancel this line" keystroke, so an accidental press destroys the
  session, the pinned scope and any armed auto-refresh loop.
- Automation-visible: a harness that sends Escape to dismiss a prompt silently loses the REPL and the
  following commands run in the parent shell.

## Proposed fix

1. Return `errIgnoredKey` (wrapped with the timeout detail) from the escape-deadline branch in
   `terminalByteReader.Read`, and clear `escapeDeadline` so the next read starts clean.
2. Keep `errLineKey` for mid-sequence read failures and oversized sequences, where the stream position is
   genuinely unknown.
3. Add a test that drives the real editor with a lone `0x1b` followed by text and asserts the line keeps
   the text typed before and after the Escape, and that the editor does not return an error.
4. Verify with a PTY probe that a lone Escape leaves the process alive.

## Status

Open. Not implemented: `internal/tui/terminal_editor.go` and `internal/tui/line_keys.go` are currently
staged inside another agent's in-progress merge, so editing them now would sweep this change into that
commit. Fix after that merge completes.
