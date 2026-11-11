---
maintainer: AI
author: DawsonLin
status: done
severity: high
created: 2026-11-11
updated: 2026-11-11
---

# Regeneration does not invalidate the token of a running Node

## Symptom

`connector-node regenerate` rewrites the identity file on disk, but a Node that
is already running keeps accepting the **old** `node-token` and rejects the
**new** one. The documented revocation mechanism therefore does nothing until the
Node is restarted.

Measured on Windows Server 2022 with `connector-node.exe` built from `staging`:

```
1. Node running, token A accepted
2. connector-node regenerate --keep-id
   -> node_7jyj7hzelnxk3b36qpyo4tftfe.<token B>
3. CLI with token A  -> hello-from-windows-scope        (accepted, WRONG)
4. CLI with token B  -> unauthenticated                 (rejected, WRONG)
5. taskkill /F /IM connector-node.exe, start again
6. CLI with token B  -> hello-from-windows-scope        (accepted)
7. CLI with token A  -> unauthenticated                 (rejected)
```

The Node log at step 4 states the reason plainly:

```
level=WARN msg="connector-node refused a request" node_id=node_7jyj7hzelnxk3b36qpyo4tftfe
  operation=file.read scope=project code=unauthenticated reason="node token does not match"
```

### Second independent reproduction

The defect was reproduced a second time in the same session, without restarting
the Node, to rule out a one-off. The Node was running at `generation=3`; a
`regenerate --keep-id` run in a separate process wrote a newer token to disk:

```
token in RUNNING memory  -> hello-from-windows-scope        (accepted)
token on DISK (newer)    -> unauthenticated                 (rejected)
```

The identity file on disk held the newer token while the running process still
accepted the older one, which is the exact inversion of the documented contract.

## Root cause

`regenerate` is a **separate process** from `run`. It calls
`node.RegenerateIdentity` and writes the new pair to the identity file, then
exits. The running `run` process never re-reads that file.

The running process holds the identity in two places, both captured at startup:

- `internal/node/dialer.go:51` — `identity security.NodeIdentity` field, set by
  `NewDialer` at line 62 and used for `hello` at line 189.
- `internal/node/dispatch.go:38` — `identity security.NodeIdentity` field, set by
  `NewDispatcher` at line 49 and compared at line 76:
  `if !d.identity.Token.Equal(request.NodeToken)`.

`cmd/connector-node/main.go:224` writes the file; nothing signals the running
process. There is no file watch, no `SIGHUP` handler for the identity, and no
shared state between the two processes.

## Why this is a defect and not a limitation

`docs/permission-design.md` states the behaviour as a rule in three places:

- Line 311: the Node "compares against the value it currently holds and keeps no
  history of previous values. A Node that accepted an old token after
  regeneration would defeat the purpose of regenerating."
- Line 317: "**Regeneration disconnects the Node.** The live channel was
  authenticated with the old pair, so it is dropped and the Node reconnects with
  the new one."
- Line 766: "`connector-node regenerate` issues a new pair and invalidates the old
  one immediately."

The enforcement checklist repeats it twice (lines 823 and 825).

The actual behaviour is the exact opposite of all five statements. The
consequence is a security one, not a cosmetic one: `regenerate` is documented as
**the only way to revoke a leaked `node-token`** (residual risks table, line 743).
If it does not affect a running Node, then a leaked token stays valid for as long
as the Node keeps running, and the operator has no way to revoke it short of
restarting the Node — which the documentation never mentions as a required step.

## Detection failure

The unit tests cover `RegenerateIdentity` as a pure function on the file, and they
cover `Dispatcher` with an identity passed in at construction. No test starts a
`run` process, regenerates the identity in a second process, and then asserts that
the first process refuses the old token. The gap is the **process boundary**: both
halves are tested, the interaction is not.

The live deployment test found it only because the regeneration step was performed
while the Node was running, which is the realistic operator sequence.

## Options

1. **Watch the identity file.** The running Node watches its identity file and
   reloads on change, dropping the live channel when the token changes. This
   matches the documented behaviour exactly, including the disconnect.
2. **Refuse to regenerate while a Node is running.** `regenerate` detects a live
   Node (lock file, pid file) and refuses, telling the operator to stop the Node
   first. This makes the documented behaviour true by preventing the situation,
   but it contradicts "the operator can regenerate without involving the Server"
   only in the sense that it now requires stopping the Node.
3. **Correct the documentation.** State that regeneration takes effect on the next
   Node start, and that revoking a leaked token requires a restart. This is the
   smallest change and it is honest, but it weakens the revocation story: the
   residual risk table currently promises immediate invalidation.

Option 1 is the only one that preserves the documented security property. Option 3
is acceptable only if the human decides the restart requirement is fine, in which
case the residual risk table must be corrected too.

## Fix

Option 1 was chosen by the human. The running Node now watches its identity file,
adopts a regenerated pair, and drops the channel that was authenticated with the
retired pair.

### Design

| Component | Responsibility |
|---|---|
| `IdentityHolder` | Single source of truth for the current pair; atomic swap; nil-safe |
| `watchIdentity` | Reads the file every second; adopts a valid new pair; signals one change |
| `describeIdentityProblem` | Reduces a load failure to a stable string so a repeated warning is logged once |
| `discardPendingIdentityChange` | Removes a stale signal before each dial so a reconnect is not immediately dropped |
| `identityChangeContext` | Per-connection context cancelled by a change signal, so one channel drops without ending the reconnect loop |
| `Dispatcher.Dispatch` | Reads `holder.Current()` once per request, so the ID check and the token check cannot straddle a regeneration |
| `Dialer.connectOnce` | Captures the authenticated pair before the handshake; one change callback closes the socket |

The holder is shared by the dispatcher and the dialer, so the pair announced in
`hello` and the pair a request is checked against are always the same value. Two
separate copies would let the Node advertise one identity and validate another.

Polling was chosen over a filesystem notification library because the standard
library has no portable notification API and the design forbids a third-party
dependency. One read of an 85 byte file per second is negligible.

### Two defects found while implementing

1. **`IdentityPath("")` returns the relative name `"identity"`.** A dialer built
   with an empty `ConfigDir` therefore polled the process working directory. The
   watcher is now only started when the path is absolute.
2. **The stamp comparison was unreliable.** A regenerated pair has the same byte
   length (85) and can land in the same `mtime` tick, so `mtime` plus `size`
   reported "unchanged" for a file holding a different credential. The original
   comment claiming "a rewrite always changes both fields" was false. The watcher
   now compares the file content.

| Signal | Detects a regeneration? | Reason |
|---|---|---|
| `mtime` only | No | A rewrite can land in the same filesystem timestamp tick |
| `size` only | No | A regenerated pair is exactly the same length |
| `mtime` + `size` | No | Both unchanged in the measured case |
| File content | Yes | The pair itself differs |

### Behaviour

| Event | Holder | Live channel | Old token | New token |
|---|---|---|---|---|
| `regenerate --keep-id` | new token, same ID | dropped, reconnects | `unauthenticated` | accepted |
| `regenerate` (full) | new ID and token | dropped, reconnects | `node_offline` | accepted |
| File rewritten with the same pair | unchanged | kept | accepted | accepted |
| File malformed | unchanged | kept, one warning | accepted | not applicable |
| File deleted | unchanged | kept, one warning | accepted | not applicable |
| Change during the reconnect delay | adopted | not dropped | `unauthenticated` | accepted |

### Tests

| Test | File | Result |
|---|---|---|
| 6 `TestIdentityHolder*` | `internal/node/identity_holder_test.go` | pass |
| `TestWatchIdentityAdoptsARegeneratedPair` | `internal/node/identity_watch_test.go` | pass |
| `TestWatchIdentityAdoptsAFullyRegeneratedPair` | `internal/node/identity_watch_test.go` | pass |
| `TestWatchIdentityIgnoresAnUnchangedFile` | `internal/node/identity_watch_test.go` | pass |
| `TestWatchIdentityKeepsTheOldPairWhenTheFileIsMalformed` | `internal/node/identity_watch_test.go` | pass |
| `TestWatchIdentityKeepsTheOldPairWhenTheFileDisappears` | `internal/node/identity_watch_test.go` | pass |
| `TestWatchIdentityStopsWithTheContext` | `internal/node/identity_watch_test.go` | pass |
| `TestWatchIdentityWithoutAPathReturnsImmediately` | `internal/node/identity_watch_test.go` | pass |
| `TestWatchIdentityDetectsASameLengthRewrite` | `internal/node/identity_watch_test.go` | pass; pins the stamp defect |
| `TestDiscardPendingIdentityChangeDrainsOneSignal` | `internal/node/identity_watch_test.go` | pass |
| `TestDiscardPendingIdentityChangeToleratesAnEmptyChannel` | `internal/node/identity_watch_test.go` | pass |
| `TestRegenerateInvalidatesTheTokenOfARunningNode` | `tests/integration/regenerate_live_test.go` | pass; fails on unfixed code |
| `TestRegenerateKeepIDKeepsTheRunningNodeAddressable` | `tests/integration/regenerate_live_test.go` | pass |
| `TestRegenerateWithANewIdentifierMovesTheRunningNode` | `tests/integration/regenerate_live_test.go` | pass |

Reverse verification: with the watcher disabled, the integration test failed with
`never answered with code 1002 (unauthenticated); last answer was 0 (success)`,
which is the original defect. The watcher was restored and the test re-verified
green.

### Verification

| Check | Result |
|---|---|
| `gofmt -l ./cmd ./internal ./tests` | clean |
| `go build ./...` | OK |
| `go vet ./...` | clean |
| `go vet -tags integration ./tests/integration/` | clean |
| `go test ./...` | all packages pass |
| `go test -race ./internal/node/` | clean |
| `go test -count=5 -run 'TestWatchIdentity\|TestIdentityHolder\|TestDiscardPending' ./internal/node/` | clean |
| `go test -tags integration -run TestRegenerate ./tests/integration/` | 3 tests pass |
| `make build-windows` (amd64, arm64, 386) | pass |
| `make test-windows-compile` | pass |
| Wine run of `node.test.exe` | 219 pass, 0 fail, 18 skip |
| Wine run of `connector-node.test.exe` | 20 pass, 0 fail, 0 skip |

### Live verification on Windows Server 2022

Binary `connector-node.exe`, 9,247,744 bytes, sha256
`a7868f657fcd2a9b3ac08a83a5328d856aec845d1ed2807703159e8f8a423f2d`, hash confirmed
on the Windows host with `certutil`.

`regenerate --keep-id` while the Node was running:

```
12:02:40 identity file changed; adopting the new pair and dropping the channel
12:02:40 identity changed; closing the channel authenticated with the retired pair
12:02:45 handshake accepted generation=2
12:02:45 channel established
```

| Request | Result |
|---|---|
| old token, no restart | `unauthenticated` |
| new token, no restart | `hello-from-windows-scope` |

`regenerate` (full, new `node-id`) while the Node was running:

```
12:03:15 identity file changed; adopting the new pair and dropping the channel
12:03:20 handshake accepted node_id=node_haal7gte4umsxlvuw7gnn44in4 generation=3
```

| Request | Result |
|---|---|
| old `node-id` | `node_offline` |
| new `node-id` | `hello-from-windows-scope` |

The fence and the three gates were re-checked after the fix and were unchanged:
`../scope-secret/secret.txt`, `C:\Windows\win.ini`, `hello.txt:stream` and `NUL`
returned `invalid_argument`; `escape/secret.txt` and `outlink` returned
`not_found`. The Server log held zero occurrences of any of the three
`node-token` values and zero occurrences of its own two secrets.

## Live verification of the surrounding contract

The same live run confirmed that everything else on this path behaves as
documented, so the defect is isolated to the regeneration step rather than a
symptom of a broken channel.

| Check | Result |
|---|---|
| `file.read`, `file.stat`, `file.list` on a real Windows Node | correct content, type, size |
| `file.read --offset 6 --length 8` | `from-win` |
| Junction escape (`escape/secret.txt`) | `denied` |
| Symlink escape (`outlink`) | `denied` |
| `file.stat` on an escaping symlink | reports `type=symlink`, does not follow |
| `../`, `..\`, `a/../../`, `./` traversal | `invalid_argument` |
| `C:\Windows\win.ini`, `/etc/passwd` | `invalid_argument` |
| `hello.txt:stream` (ADS), `NUL`, `CON` | `invalid_argument` |
| `hello.txt.`, `hello.txt ` (trailing dot/space) | `invalid_argument` |
| `\\?\C:\...`, `\\server\share`, `C:hello.txt` | `invalid_argument` |
| undefined scope | `denied` |
| `file.write`, `command.exec` | refused as not enabled in this version |
| wrong `client_token`, wrong `node-token` | `unauthenticated` |
| unknown `node_id` | `node_offline` |
| `node-token` occurrences in Server log and files | 0 |
| Server's own secrets in log | 0, shown as `<secret:38 bytes>` |
| scope path written `C:/connector/scope` | accepted |
| scope path written `c:\CONNECTOR\Scope\` | accepted |
| scope path `c:\users\administrator` | refused: home directory |
| scope path `c:\` | refused: filesystem root |
