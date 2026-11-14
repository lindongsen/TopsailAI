---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-14
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

## Proposed fix

Distinguish the two causes inside the callback. The identity signal is the only
thing that should produce the message, so the callback must check whether the
parent context is still live:

- If `ctx.Err() != nil`, the session is ending for another reason: close the
  socket and log at debug level, or say nothing.
- Otherwise the change context was cancelled by the identity signal: log the
  message and close the socket.

The close must happen in both branches, because the socket has to be closed for
the read to return either way.

## Prevention

- A log line that names a cause must be emitted only when that cause is known.
  A callback registered on a derived context sees every cancellation of the
  parent, so it must check which one happened before it names a reason.
- A test that passes a nil channel does not exercise the goroutine that the real
  path starts. The shutdown path needs a live run, or a test that supplies a real
  channel and cancels the parent.
