---
maintainer: AI
author: DawsonLin
status: fixed
created: 2026-11-14
resolved: 2026-11-14
---

# A normal shutdown logs that the identity changed

## Symptom

A Node that is stopped normally logs:

```
level=INFO msg="identity changed; closing the channel authenticated with the retired pair" node_id=node_nbiv7btoo4lth7quomhn4oybr4
```

The identity file was never rewritten. Its checksum was identical before and
after the run, and no `identity file changed; adopting the new pair` line was
ever emitted, which is the line the watcher writes before it signals a change.

The message is therefore false. An operator reading it would look for a
regeneration that never happened, and would suspect a credential problem on a
Node that was simply shut down.

## Reproduction

1. Build a default artifact with a valid Server URL, one scope and a tunnel token
   of at least 16 bytes.
2. Start a Server, then start the artifact with `env -i HOME=... PATH=...`.
3. Wait for `channel established`.
4. Record the checksum of `<HOME>/.config/topsailai-connector/identity`.
5. Wait three seconds, then stop the Node with `kill <pid>`.
6. The checksum is unchanged, and the false line is the last line in the log.

Measured: `md5 155434aa223c2cab469f65c7f8d95f8b` before and after; zero
`identity changed` lines while running; one after a normal stop.

## Root cause

`internal/node/dialer.go:198` derives the change context from the session
context:

```go
changeCtx, stopChangeWatcher := identityChangeContext(ctx, d.identityChanges)
```

`identityChangeContext` at `internal/node/identity_watch.go:132-136` builds that
context with `context.WithCancel(ctx)`, so it is cancelled when **either** the
identity changes **or** the parent context ends. The callback registered at
`dialer.go:206` cannot tell the two apart, so it logs the identity-change message
on every shutdown.

The callback's job is to close the socket, and closing it on shutdown is correct
and necessary: a blocked read only ends when the socket does. The defect is the
log line, not the close.

## Why it was not caught

The existing tests drive `connectOnce` with a nil `identityChanges` channel, and
`identityChangeContext` returns early for a nil channel without starting the
goroutine. The shutdown path therefore never runs the callback in a test. The
behaviour is only visible in a live run that stops the process.

## Resolution

The callback now checks whether the parent context is still live before it names
a cause:

```go
if ctx.Err() != nil {
    return
}
```

`ctx.Err() != nil` means the session is ending for a reason other than the
identity. `ctx.Err() == nil` while the change context is cancelled means the
identity signal fired, because that is the only other cancellation source. No
extra state is needed.

The shutdown branch closes nothing. The watcher registered on `ctx` at
`dialer.go:187` already closes the connection when the context ends, so closing
it again in the identity callback would be a second close of the same socket.
This was proven by mutation: removing the shutdown branch's close did not fail
any test, which showed the line was dead code rather than a safeguard.

### Tests

| Test | Setup | Assertion |
|---|---|---|
| `TestDialerShutdownDoesNotReportAnIdentityChange` | Real `identityChanges` channel, wait for `channel established`, cancel | The log contains no `identity changed` |
| `TestDialerReportsAGenuineIdentityChange` | Real channel, wait for `channel established`, send one signal | The log contains `identity changed` |

The second test is required, because a fix that deleted the message would satisfy
the first one alone.

Both tests wait for `channel established` rather than for the hello. Waiting on
the hello cancels before `Session.Serve` starts, so the loop returns from its
`ctx.Err()` check at the top and never reaches the blocked read that the socket
close exists to interrupt. The first version of the shutdown test waited on the
hello and passed against a broken implementation.

### Mutation evidence

| Mutation | Result | Caught by |
|---|---|---|
| Revert the fix | FAIL | Shutdown test |
| Delete the message | FAIL | Genuine-change test |
| Shutdown branch does not close | not caught | Redundant close removed |
| `ctx` watcher does not close | FAIL, 5.01s | Shutdown test |

### Live evidence

Server on `127.0.0.1:18993`, Node connected, identity md5
`796a3df7cf14b12a55d80068545ccf32`. After `kill <pid>` the process exited, the
md5 was unchanged, and the log held zero `identity changed` lines.

A genuine `regenerate` still produced both lines and changed the md5 to
`91f69d52eb02c57b95d4975b731bbef3`:

```
msg="identity file changed; adopting the new pair and dropping the channel"
msg="identity changed; closing the channel authenticated with the retired pair"
```

`make check` passed with RC=0 and zero failures.

## Prevention

- A log line that names a cause must be emitted only when that cause is known.
  A callback registered on a derived context sees every cancellation of the
  parent, so it must check which one happened before it names a reason.
- A test that passes a nil channel does not exercise the goroutine that the real
  path starts. The shutdown path needs a live run, or a test that supplies a real
  channel and cancels the parent.
- A test that waits for the handshake rather than for the session to be serving
  can pass without reaching the code under test. Mutation testing is what
  distinguishes a passing test from an effective one.
