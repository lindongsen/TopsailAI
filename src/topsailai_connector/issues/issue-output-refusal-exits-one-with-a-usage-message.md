---
maintainer: AI
author: DawsonLin
status: open
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

A test that asserts the pair — `ErrUsage` in the message implies status `2` — would
have caught it. That invariant is worth adding whichever fix is chosen.

## Current documentation

`skills/connector-client/SKILL.md` documents the measured behaviour: exit status
`1`, with a note that the message begins `usage:` and the status is still `1`.
That is accurate today and must be updated if either fix lands.
