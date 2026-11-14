---
maintainer: AI
author: DawsonLin
status: done
severity: high
created: 2026-11-14
platform: all
---

# A symlink alias inside a scope returns the Node's tunnel token

## Symptom

A relative symlink inside a scope that points at the Node's config directory
returns the real `tunnel_token`, which is the secret that authorizes every
operation on the Node.

Measured on the build host with the real binary, scope = the bundle directory,
config = `<bundle>/config`, alias = `<bundle>/alias -> ../node/config`:

```
file.read  alias/identity      -> denied
file.read  alias/policy.yaml   -> denied
file.read  alias/tunnel_token  -> success, content "tunnel-secret-value"
file.list  alias               -> denied
file.stat  alias               -> success, LinkTarget "../node/config"
```

The first two refusals made the leak look closed. The third line is the defect.

## Impact

A caller who holds a valid `client_token` and a valid `node-token` can read the
Node's `tunnel_token` through the fence. That secret is Server-wide and never
expires, so reading it once is enough to open a channel and impersonate any Node
that shares the Server's `tunnel_token`.

The exposure is worst under the filesystem-root opt-in, because the config
directory is then necessarily inside the scope. It is not limited to that case: a
scope that contains the bundle directory, which is the layout `verify_package.sh`
uses, is enough.

A second, smaller leak was found in the same probe: `file.stat` on an absolute
symlink returned the config directory's absolute path as `LinkTarget`. Reading
through it was refused by `os.Root`, so no credential escaped, but the Node's
filesystem layout was disclosed, which `docs/permission-design.md` forbids.

## Root cause

Two rules each covered half of one case.

`isDeniedPath` compares the path **as the caller wrote it** against the deny
prefixes. An alias is a different written path, so the prefix rule cannot see it.

`isDenied` compares the **opened object's identity** against the deny files. That
works for a file that is named in the deny list. `denyPaths` in
`internal/node/run.go` is:

```go
denyPaths := []string{identityPath, config.PolicyPath, config.ConfigDir}
```

`tunnel_token` lives in the config directory (`packaging/start.sh:33`) but is never
named. Through an alias, the one file not individually listed was readable.

So the alias defeated the prefix rule, and the unlisted file defeated the identity
rule. Neither rule was wrong on its own; together they left a route open.

## Detection failure

The deny list was tested by spelling the denied path directly, which is the case
the prefix rule covers. No test built an alias, so the route the prefix rule cannot
see was never exercised. The existing `verify_package.sh` symlink check used a link
that **escapes** the scope, which `os.Root` refuses before the deny list runs, so it
proved the fence and not the deny list.

## Fix

The deny list now also compares the identity of every ancestor directory. A path is
refused when any directory on the way to it is the same inode as a deny-listed
directory, so a symlink that points at the config directory is refused for every
file inside it, whether or not that file is named.

New in `internal/node/fence.go`:

| Function | Purpose |
|---|---|
| `collectDeniedDirs` | Records the identity of the deny-listed directories at startup |
| `isDeniedDir` | Answers whether an object is one of those directories |
| `isDeniedAncestor` | Walks every ancestor through the scope handle and refuses on a match |
| `resolvesToDeniedDir` | Resolves a link target and asks whether it is a denied directory |

Wired into `openValidated` (read), `statEntry` (listing) and `Stat` (stat).

Adding `tunnel_token` to `denyPaths` was rejected: it would close this one route and
leave the next unlisted file in that directory exposed. Comparing ancestor identity
closes the route itself.

`Stat` refuses a link that resolves to a denied directory, rather than reporting it
with the target withheld. The identity rule applies to the link itself: `config` is
refused, so an alias that resolves to `config` is refused too, whichever name
reaches it.

Reporting the link with the target withheld was the first attempt and it was wrong
twice over. It answered differently depending on the scope shape, because an alias
that escapes the scope root cannot be resolved through the handle, so the same alias
was refused under a whole-volume scope and reported under a subdirectory scope. And
it disclosed the layout anyway, because a symlink's reported size is the length of
its target, so withholding the target while reporting its length answered the
question the withholding was meant to refuse.

An escaping symlink that does not resolve to a denied directory is still reported as
a link without being followed, which is the documented `file.stat` contract and the
reason `Lstat` is used rather than `Stat`.

The deny-list comparison now uses `pathEqual` and `pathHasPrefix`, so the platform's
case rule applies. A byte-for-byte comparison on Windows let `CONFIG` reach
`config`, which is the same bypass the fence refuses elsewhere.

## Behaviour that must not change

The rule answers by identity, not by name, and that is deliberate:

| Layout | Answer | Why |
|---|---|---|
| A `config` directory at another path | readable | It is not the Node's directory |
| A sibling named `config-backup` | readable | The separator boundary is respected |
| A look-alike nested inside a look-alike | readable | No ancestor is the Node's directory |
| A look-alike nested inside the real config directory | refused | Its ancestor is the Node's directory |
| An alias to a look-alike config directory | readable | The target is not the Node's directory |

A name-based rule would make a whole-volume scope useless, because every directory
called `config` would become unreachable.

## Tests

`internal/node/fence_deny_alias_test.go`, 5 tests and 14 subtests:

- relative alias denied for `identity`, `policy.yaml` and `tunnel_token`; `Stat` and
  `List` through the alias denied; `Stat` of the alias itself denied; the alias
  omitted from its parent's listing; an ordinary file still readable
- absolute alias denied; omitted from a listing; `Stat` of the alias itself denied
- alias to a directory nested inside the real config denied
- alias to a look-alike config directory allowed
- whole-volume scope with the opt-in: alias denied for all three files, alias
  omitted from the listing

`internal/node/fence_deny_lookalike_test.go`, 8 subtests, covers the look-alike
direction that must not over-refuse.

`internal/node/fence_deny_case_windows_test.go` covers the case-varied spelling on
Windows.

## Test-design note

The alias tests must use a **relative** link target. `os.Root` refuses any absolute
target unconditionally, so an absolute link is refused before the deny list runs and
the test measures `os.Root` rather than the rule under test. The `linkRelative`
helper builds the relative target from the link's own directory.

A subdirectory scope whose alias points outside the root cannot be resolved through
the handle, so `isDeniedAncestor` cannot see it. `resolvesToDeniedDir` resolves the
target outside the handle for exactly that case, which is why the alias is refused
under both scope shapes rather than only under a whole-volume scope.

## Verified on

Linux build host, Go 1.25.12, `connector-node` built from `cmd/connector-node`.
`go test ./internal/node/` passes, `GOOS=windows go vet ./...` is clean, the Windows
test binaries compile, and `make check` returns 0.
