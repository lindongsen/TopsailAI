---
maintainer: AI
author: DawsonLin
status: fixed
created: 2026-11-19
---

# An `-o` refusal exits 1 while its message says `usage:`

## Symptom

A destination that already exists is refused with a message that begins
`usage:`, but the process exits `1`:

```
$ connector-server cli ... -o dest.txt file.read
connector-server cli: usage: dest.txt already exists; pass --force to replace it
$ echo $?
1
```

Every other message that begins `usage:` exits `2`. Measured on the same binary
with the same credentials:

| Invocation | Message | Exit |
|---|---|---|
| `-o ""` | `usage: -o needs a destination; ...` | `2` |
| `--json -o x` | `usage: --json and -o cannot be combined; ...` | `2` |
| `--force` without `-o` | `usage: --force requires -o` | `2` |
| `-o dest.txt` where `dest.txt` exists | `usage: dest.txt already exists; ...` | **`1`** |

## Cause

`openDestination` in `internal/server/cli/output.go` wraps the refusal in
`ErrUsage`:

```go
return nil, fmt.Errorf("%w: %s already exists; pass --force to replace it", ErrUsage, final)
```

But `Run` in `internal/server/cli/command.go` returns `1` for every error from
`writeToDestination`, without checking whether the error wraps `ErrUsage`:

```go
if err := writeToDestination(client, options, stdout, stderr); err != nil {
    fmt.Fprintf(stderr, "connector-server cli: %v\n", err)
    return 1
}
```

The `ErrUsage` wrapper is therefore decorative on this path: it changes the
message prefix and nothing else.

## Why it matters

A script that branches on the exit status cannot tell the two classes apart:

- `2` means the command line was rejected, so nothing was sent to the Server.
- `1` means the request ran and failed.

Here the command line was accepted, the request was sent, and the result was
refused at the moment of writing. That is a `1` in substance, which is what the
code returns. The defect is the message, not the status: a reader who sees
`usage:` reasonably concludes the invocation was malformed and goes looking for a
typo that does not exist.

## Two possible fixes

1. **Drop the `ErrUsage` wrapper** and let the message read
   `dest.txt already exists; pass --force to replace it`, so the text matches the
   status. Smallest change, no behaviour change for any caller.
2. **Return `2` for an `ErrUsage` from `writeToDestination`**, so the status
   matches the message. This changes the contract for an existing script that
   treats `1` as "the request failed", and it would be wrong in substance: the
   request did run.

The first is preferred. The status is already correct; only the prefix is
misleading.

## Detection gap

The unit test asserts the message text and the status separately, so neither
assertion notices that the pair is inconsistent:

- `TestOutputRefusesAnExistingDestination` checks the message contains
  `already exists`.
- The status is checked as non-zero, not as a specific value.

## Current documentation

`skills/connector-client/SKILL.md` documented the measured behaviour: exit status
`1`, with a note that the message began `usage:` and the status was still `1`.

## Resolution

Fixed by dropping the `ErrUsage` wrapper from the refusal, so the message reads
`<path> already exists; pass --force to replace it` and the status stays `1`. The
status was already correct in substance: the command line was accepted, the request
ran, and only the write was refused.

Changes:

- `internal/server/cli/output.go` — the refusal no longer wraps `ErrUsage`, and the
  function comment states why the prefix would be wrong here.
- `internal/server/cli/output_test.go` — `TestOutputRefusesAnExistingDestination`
  strengthened. It previously asserted the message and the status separately, which is
  the gap this issue describes; it now asserts the pair: status `1`, no `usage:`
  prefix, the refusal named, the `--force` hint present, and the destination
  untouched. The test was strengthened rather than duplicated, because a second test
  in another file asserting the same behaviour would be noise and the weak assertion
  would remain.
- `internal/server/cli/command_test.go` — `TestParseRefusalsExitTwo` added. It asserts
  the invariant over every parse-time refusal, so a future refusal that claims
  `usage:` and exits anything but `2` fails.
- `skills/connector-client/SKILL.md` — the caveat now says the message carries no
  `usage:` prefix, and it names the remaining case where the prefix and the status
  disagree.

Verification:

| Check | Result |
|---|---|
| `go build ./...` | rc=0 |
| `go vet ./...` | rc=0 |
| `go test ./...` | all packages pass |
| `gofmt -l internal/server/cli/` | empty |
| Live binary, existing destination | `dest.txt already exists; pass --force to replace it`, rc=1, file untouched |
| Live binary, `--force` without `-o` | `usage: --force requires -o`, rc=2 |
| Live binary against the deployed Node, existing destination | rc=1, file untouched |
| Live binary against the deployed Node, `--force` | rc=0, `wrote 48 bytes`, content replaced |

Mutation evidence, so the new assertions are not vacuous:

- Restoring the `ErrUsage` wrapper makes `TestOutputRefusesAnExistingDestination` fail
  with `want no usage: prefix because the command line was accepted`. The file was
  restored and its md5 compared with the backup (`12acf116532d27f50028852b271c4065`).
- Changing the parser's `return 2` to `return 1` makes `TestParseRefusalsExitTwo` fail
  on every case. The file was restored and its md5 compared with the backup
  (`6aa3bdcd91aedec8f187471ded8c4c8c`).

## Out of scope

`Client.Send` wraps ten of its own local checks in `ErrUsage` and `Run` returns `1`
for them, so the same inconsistency exists in the opposite direction: the prefix is
right and the status is wrong. That is a separate defect with a separate fix, recorded
in `issues/issue-send-time-validation-exits-one-with-a-usage-message.md`.
`TestParseRefusalsExitTwo` is scoped to the parser for that reason, and its comment
says so.
