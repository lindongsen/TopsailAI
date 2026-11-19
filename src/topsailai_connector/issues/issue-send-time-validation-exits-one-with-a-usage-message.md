---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-19
---

# A `Client.Send` validation refusal exits 1 while its message says `usage:`

## Symptom

`Client.Send` validates its own inputs before building a request, and it wraps every
refusal in `ErrUsage`. `Run` returns `1` for any error from `Send`, so the message
claims a usage error while the status says the request failed.

Measured on the built binary with valid credentials:

| Invocation | Message | Exit |
|---|---|---|
| `--node-id abc` | `usage: --node-id node id "abc" does not start with "node_"` | **`1`** |
| `--scope 'bad scope'` | `usage: scope name "bad scope" contains ' ', ...` | **`1`** |
| `--server ftp://x` | `usage: server URL "ftp://x" must start with http:// or https://` | **`1`** |
| `--force` without `-o` | `usage: --force requires -o` | `2` |

The last row is the contrast: a refusal from `parseArguments` exits `2`, a refusal
from `Send` exits `1`, and both messages begin `usage:`.

## Cause

`internal/server/cli/client.go` wraps ten local checks in `ErrUsage`:

```go
if err := security.ValidateNodeID(options.NodeID); err != nil {
    return Envelope{}, fmt.Errorf("%w: --node-id %v", ErrUsage, err)
}
```

`internal/server/cli/command.go` does not inspect the error:

```go
envelope, err := client.Send(options)
if err != nil {
    fmt.Fprintf(stderr, "connector-server cli: %v\n", err)
    return 1
}
```

So `ErrUsage` on this path changes the message prefix and nothing else, exactly as it
did for the `-o` refusal recorded in
`issues/done/issue-output-refusal-exits-one-with-a-usage-message.md`.

## Why it matters

The same reason as the `-o` case: a script that branches on the status cannot tell
"the command line was rejected, nothing was sent" from "the request ran and failed".
Here nothing was sent, so `2` is the substantively correct status and `1` is wrong.

This is the opposite direction from the `-o` defect. There the status was right and
the prefix was wrong; here the prefix is right and the status is wrong. The two
cannot be fixed by the same edit, which is why they are separate issues.

## Two possible fixes

1. **Return `2` when the error from `Send` wraps `ErrUsage`.** The prefix is already
   correct, so this makes the pair consistent without touching any message. It also
   makes the documented rule true: `usage:` means nothing was sent.
2. **Drop the `ErrUsage` wrapper from `Send`.** Then the message reads
   `--node-id node id "abc" does not start with "node_"` with status `1`. This is
   wrong in substance, because nothing was sent and the caller should be told the
   command line was rejected.

The first is preferred. It is also the smaller change: one `errors.Is` check in
`Run`, no message changes, no documentation changes beyond removing the caveat.

## Detection gap

`TestRunRefusesMissingConfiguration` asserts `status != 0` for these cases, so a
status of `1` passes. `TestParseRefusalsExitTwo` deliberately scopes itself to the
parser and documents this defect as out of its scope, so neither test can see it.

A test that asserts the pair over the `Send` path would catch it. That test cannot be
written until the fix is chosen, because it would fail today.

## Current documentation

`skills/connector-client/SKILL.md` states the caveat explicitly: a few values are
checked after the command line is parsed but before the request is sent, and those
exit `1` with a `usage:` prefix. That is accurate today and must be updated when
either fix lands.

## Related

- `issues/done/issue-output-refusal-exits-one-with-a-usage-message.md` — the same
  family, opposite direction, fixed by removing the prefix.
