---
maintainer: AI
author: DawsonLin
status: done
severity: medium
created: 2026-11-14
platform: all
---

# A policy cannot expose a whole volume, and the only workaround is a hand-written list of top-level directories

## Symptom

An operator who wants one scope covering an entire drive has no way to write it.
A policy naming a volume root is refused at startup:

```yaml
version: 1
scopes:
  cdrive:
    path: C:\
grants:
  - scope: cdrive
    permissions: [read, list, stat]
```

```
connector-node: load authority: scope "cdrive": path "C:\\" is a filesystem root;
its blast radius is the whole machine
EXIT=1
```

The process exits with status 1. This is not a per-request refusal; the Node never
starts, so it never connects.

## Impact

The refusal itself is correct and deliberate: a scope rooted at a volume exposes
every file on that volume, and the design requires that blast radius to be a
decision rather than an accident.

The problem is that there is no way to make that decision. The only workaround is
to enumerate every top-level directory as its own scope, which is what the Windows
deployment does today: fourteen scopes named `users`, `windows`, `programfiles`,
`programfilesx86`, `programdata`, `drivers`, `perflogs`, `recovery`,
`systemvolume`, `recycle`, `configmsi`, `qrewtoolchain`, `qrew2` and `acltest`.

That workaround is equivalent to "the whole volume" but expresses something else,
and the two drift apart:

- A file directly under the volume root, such as `C:\pubkey.txt` or
  `C:\pagefile.sys`, belongs to no top-level directory and is therefore in no
  scope. It is unreachable, and nothing reports that.
- A top-level directory created later is not in the policy. Access silently does
  not cover it, and the only signal is a `denied` that looks like a policy
  decision rather than a missing entry.

So the operator's intent ("this Node serves this drive") cannot be written down,
and the configuration that stands in for it is incomplete in a way that produces no
error.

## Root cause

`validateScopeMapping` in `internal/node/fence.go` refuses a filesystem root
unconditionally:

```go
if isFilesystemRoot(path) {
    return fmt.Errorf("scope %q: path %q is a filesystem root; its blast radius is the whole machine", name, path)
}
```

There is no opt-in anywhere in the codebase. A search for `allowroot`, `allow-root`,
`allowfilesystem`, `unsafe`, `relax` and `insecure` across `internal/` and `cmd/`
finds nothing relevant. The policy schema has exactly three keys (`version`,
`scopes`, `grants`) and decoding is strict (`KnownFields(true)`), so an operator who
invents a key is refused rather than silently ignored:

```
allow_root: true          -> refused, unknown key
allow_filesystem_root: true -> refused, unknown key (before this change)
```

## Detection failure

The design document argues at length for refusing a filesystem root, and the
enforcement checklist repeats the rule. Neither states what an operator should do
when the whole volume is genuinely the intended blast radius, so the gap was
invisible: the documentation described a refusal without describing the case the
refusal makes impossible.

## Fix direction

Add one explicit, default-off key that states the blast radius on purpose, and make
the deny list carry the protection that the startup refusal used to provide.

## Resolution

`allow_filesystem_root` is a new top-level policy key, absent by default. Its
absence is the refusal, so no existing policy changes behaviour.

It relaxes exactly two startup rules, because the second follows from the first:

1. A scope rooted at a filesystem root.
2. A scope that contains the Node's config directory. A scope rooted at `C:\`
   necessarily contains the config directory, so refusing the overlap would make
   the opt-in unusable.

Every other rule still applies: the path must be absolute, real, a directory and
not a symlink, and the home directory and mount points are still refused.

Relaxing the overlap is safe only because the config directory is now on the deny
list. Two gaps had to be closed for that to hold:

- `run.go` listed only `identityPath` and `config.PolicyPath`. The config directory
  itself was not denied, so a volume-root scope would have exposed
  `config/tunnel_token`, a Server-wide secret. `config.ConfigDir` is now a deny
  entry.
- `List` never consulted the deny list, so it reported the name and size of every
  denied entry. A volume-root scope would therefore have listed `identity`,
  `policy.yaml` and `tunnel_token` even though reading them was refused. Denied
  entries are now omitted from a listing.

A denied directory also denies everything beneath it, which the identity comparison
could not do: a file created inside a denied directory is a different inode, so it
would not match. `deniedPrefixes` holds each denied directory as a path relative to
the scope root, and `isDeniedPath` compares with a separator boundary so a sibling
named `config-backup` is not refused.

`OpenScope` keeps its four-parameter signature and always refuses a filesystem root,
so a caller that has not read a policy cannot widen the fence. The opt-in is read
from the policy inside `LoadAuthority` and passed to a new internal `openScope`.

Tests: `internal/node/fence_root_optin_test.go` covers the default refusal, the
refusal without the key, the opted-in success, the config directory refused for
read, stat and list and omitted from the parent listing, an escape still refused, a
relative root still refused, the separator boundary, a deny path outside the scope,
a denied scope root refused at startup, and — the load-bearing one —
`TestOptedInScopeWithoutTheDenyEntryReadsTheIdentityFile`, which reads the identity
file successfully when the deny entry is absent. That test proves the refusal comes
from the deny list rather than from somewhere else, so a future change that drops
the deny entry fails a test instead of silently exposing the credential.

## Verified on

Build host, Go 1.25.12, `make check` RC=0, 18 packages ok, total coverage 89.6%
(`internal/node` 91.7%, `internal/node/policy` 95.4%). Windows cross-compile for
amd64, arm64 and 386, and the Windows test binaries, all compiled.

`os.OpenRoot` was probed at a volume root on Windows Server 2022 before the change:
it opens `C:\`, lists 22 entries, and still refuses `..\Windows\win.ini` with
`path escapes from parent`. The fence therefore remains effective at a volume root,
which is what makes the opt-in safe rather than merely convenient.
