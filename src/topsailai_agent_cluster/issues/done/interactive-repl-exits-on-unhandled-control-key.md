---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# Interactive REPL exits when the operator presses an unhandled control key

## Trigger

Discovered while driving the interactive REPL from a tmux harness during WAT-M03 verification of the
`watch` command. The harness sent Ctrl-U (`0x15`) to clear the input line. The REPL exited instead of
clearing the line, and the following `watch --force` was executed by the parent shell as bash
`watch(1)`, which produced `watch(1)` help text in the pane.

## Observed behavior

Any control character that `readLineKey` does not recognize terminates the whole interactive session.
The operator loses the session, the pinned scope and any armed auto-refresh loop, and the terminal
returns to the shell without an explanation of why.

Reproduction: run `agent-cluster-cli interactive`, then press Ctrl-U, Ctrl-G, Ctrl-O, Ctrl-Y or any
other unhandled control key. The REPL exits with a non-zero status.

## Root cause

`internal/tui/line_keys.go:75-77` rejects every remaining control rune:

```go
if unicode.IsControl(r) {
    return lineKey{}, errLineKey
}
```

`internal/tui/terminal_editor.go:105-110` propagates that error out of the editor:

```go
key, keyErr := readLineKey(reader)
if keyErr != nil {
    ...
    return "", false, keyErr
}
```

`internal/tui/interactive.go:279-281` treats any non-EOF error as fatal:

```go
if err != nil && err != io.EOF {
    return err
}
```

So an unrecognized key is classified as a fatal read failure rather than as an ignorable keystroke. The
same path also fires for a malformed escape sequence (`line_keys.go:88`, `:101`, `:104`, `:112`, `:141`)
and for an incomplete escape timeout (`terminal_editor.go:222`), so a stray escape byte or a slow
terminal can also kill the session.

## Impact

- Operator-visible: an accidental control key destroys the interactive session.
- Automation-visible: any harness or script that sends a control key to clear or edit the line silently
  loses the REPL, and subsequent commands run in the parent shell. This is exactly how the first
  WAT-M03 run was invalidated.
- The failure is silent about its cause: the operator sees the shell prompt return with no message
  naming the offending key.

## Why it was not caught

Unit tests exercise the editor through injected readers that return well-formed keys, and the REPL tests
inject `ReadLine` function values. No test sends an unhandled control byte through the real
`readLineKey` path and asserts that the REPL survives. The tmux manual cases did not send control keys
before this phase.

## Proposed fix

Distinguish an ignorable keystroke from a fatal read failure:

1. Introduce a sentinel such as `errIgnoredKey` for a decoded-but-unsupported control rune, and keep
   `errLineKey` for genuinely malformed input that invalidates the current line.
2. In `terminal_editor.go`, on `errIgnoredKey`, redraw the prompt and continue the loop instead of
   returning an error.
3. Keep the current fatal behaviour for a malformed escape sequence only if the line is genuinely
   unrecoverable; otherwise treat it as ignorable too, because a stray escape byte is not a reason to
   destroy the session.
4. Add a unit test that feeds `0x15`, `0x07` and a truncated escape sequence through the real editor and
   asserts the REPL continues with the buffer unchanged.

## Resolution

Fixed in this change. An unhandled control rune is now classified as an ignorable keystroke instead of
a read failure:

- `internal/tui/line_keys.go` adds `errIgnoredKey` and returns it from the `unicode.IsControl` branch,
  so an ignorable key is distinguishable from a malformed sequence.
- `internal/tui/terminal_editor.go` continues the read loop on `errIgnoredKey`, keeping the current
  line, instead of returning the error to the REPL.

Malformed escape sequences still return `errLineKey` and remain fatal, because a truncated or oversized
escape sequence leaves the input stream in an unknown position. Only a decoded control rune is
ignorable.

## Verification

- `TestLineKeysIgnoreUnhandledControlRunes` asserts `0x15`, `0x07`, `0x0f`, `0x19` and `0x1a` yield
  `errIgnoredKey` and are not classified as malformed.
- `TestTerminalEditorIgnoresUnhandledControlKeys` feeds `ab\x15\x07\x0f\x19cd\r` through the real editor
  and asserts the line resolves to `abcd`.
- Both tests were confirmed to FAIL with the fix reverted (`err=unsupported or malformed terminal key`),
  so they guard the behaviour rather than passing trivially.
- `go test ./internal/tui/ -count=1` passes (109.7 s); `go test -race ./internal/tui/ -run
  'Editor|LineKey|Watch|watch'` passes; `go test ./src/main/agent-cluster-cli/ -count=1` passes.
- Live PTY probe against the rebuilt binary: typing `lis`, then Ctrl-U, then `t` and Enter leaves the
  REPL alive (`alive_after_ctrl_u=1`), the prompt intact and the `list` table rendered, proving the
  session survived the control byte and kept reading.
