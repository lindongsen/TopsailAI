---
maintainer: AI
author: DawsonLin
status: done
severity: low
created: 2026-11-11
platform: all
---

# A scope root that contains the Node's config directory is not refused at startup

## Symptom

`docs/permission-design.md` states, under "Scope to directory mapping":

> The path is not inside the Node's own config directory, and the config
> directory is not inside the path. A scope that can read its own credentials is
> a configuration mistake worth refusing at startup rather than denying per
> request.

The Node does not implement that check. A policy whose scope root contains the
config directory starts normally:

```yaml
version: 1
scopes:
  project:
    path: C:\connector          # contains C:\connector\config
grants:
  - scope: project
    permissions: [read, list, stat]
```

```
time=... level=INFO msg="connector-node ready" node_id=node_7jyj... scopes=[project]
time=... level=INFO msg="handshake accepted" node_id=node_7jyj... generation=5
time=... level=INFO msg="channel established" node_id=node_7jyj...
```

## Impact

The credentials are still protected at request time, so this is not a bypass.
The deny list refuses the Node's own files by resolved path:

```
file.read  config/identity    -> denied: path "config/identity" is one of the Node's own files
file.stat  config/identity    -> denied: path "config/identity" is one of the Node's own files
file.read  config/policy.yaml -> denied: path "config/policy.yaml" is one of the Node's own files
```

`file.list config` still enumerates the directory and reports the names and
sizes of `identity` and `policy.yaml`. That is a metadata leak the design
intended to prevent by refusing the configuration outright, and it is the
reason the startup check exists rather than being redundant with the deny list.

## Root cause

`validateScopeMapping` in `internal/node/fence.go` checks the identifier, the
absolute-path rule, symlink, directory, filesystem root, home directory and
mount point. It never compares the scope path with `Config.ConfigDir`, because
`OpenScope` receives only the scope name, the path and the deny paths. The
config directory is not passed down, so the check has nothing to compare
against.

## Re-verified in the second live run

The defect was reproduced again on the same Windows host with a freshly built
binary, and the exact leak was measured:

```
scope  = C:\connector
config = C:\connector\config

file.list config            -> identity      file  85
                               policy.yaml   file  123
                               policy.yaml.bak file 129
file.read config/identity   -> denied: path "config/identity" is one of the Node's own files
file.stat config/identity   -> denied
file.read config/policy.yaml-> denied
```

So the deny list protects the **contents** and the startup check that the design
requires is missing, which leaves the **names and sizes** of the Node's own
credential files readable. The Node started normally at `generation=7` with this
policy, confirming the startup refusal does not exist.

Note that the leak is only reachable when the config directory is inside a scope.
In the normal layout (`scope = C:\connector\scope`, `config = C:\connector\config`)
the path `../config` is refused at the grammar layer as `invalid_argument`, so the
defect needs a specific misconfiguration to trigger. That is why it is rated low.

## Detection failure

The design document states the rule and the enforcement checklist repeats it,
but no test asserts it. A rule that exists only in prose is a rule that is not
implemented.

## Fix direction

Pass the config directory into the scope validation and refuse a scope whose
resolved path is an ancestor of, equal to, or inside the config directory.
Compare with `samePath` so the Windows case rule applies.

## Verified on

Windows Server 2022 (10.0.20348.587), `connector-node.exe` built from
`cmd/connector-node` at commit `b544bc19`.

## Resolution

Fixed. `OpenScope` in `internal/node/fence.go` now takes the config directory and
`validateScopeMapping` refuses a scope whose resolved path equals, contains or sits
inside it:

```
scope %q: path %q overlaps the Node's config directory %q; a scope that can list
its own credentials is a configuration mistake
```

The comparison is on path components, not on a string prefix. `isPathInside` uses
`filepath.Rel` and requires the relative result to be `.` or to not begin with
`..` followed by a separator, so a sibling named `config-backup` is not mistaken for
a child of `config`. `overlapsConfigDir` checks all three directions: equal,
scope contains config, scope inside config. `samePath` is reused for the equality
case, so the Windows case-insensitive rule applies without a second comparison.

An empty config directory disables the check rather than refusing everything, which
keeps `OpenScope` usable from a caller that has no config directory to protect.

The config directory is threaded through `LoadAuthority` from `Config.ConfigDir` in
`internal/node/run.go`, so the value the check compares against is the one the Node
actually uses, not a second derivation.

Tests: `internal/node/fence_config_overlap_test.go` covers equal, containing,
ancestor, inside, deeply inside, sibling and unrelated layouts, plus the separator
boundary against `config-backup`, `config2` and `configuration`, a redundant
spelling with a trailing separator, a `.` segment and a doubled separator, and the
empty-config-dir case. `internal/node/fence_config_overlap_windows_test.go` covers
the case-insensitive comparison and the different-volume case on Windows.

`TestOpenDeniesTheIdentityFile` was replaced, because it deliberately pointed a
scope at the config directory and therefore asserted the behaviour this issue
reports as a defect. It is now
`TestOpenRefusesAScopeThatOverlapsTheConfigDirectory` for the three overlap
directions, plus `TestOpenDeniesThePolicyFileInsideAScope`, which keeps the deny-list
coverage for a policy file that legitimately sits inside a scope.

The rule is now in the enforcement checklist in `docs/permission-design.md`, next to
the deny-list item, because the two are halves of one protection: the deny list
hides the contents and the startup refusal hides the names and sizes.

Live verification on the build host, through the real binary:

```
scope = <root>/.tmp/ovl, config = <root>/.tmp/ovl/config
  -> rc=1, load authority: scope "whole": path ".../.tmp/ovl" overlaps the Node's
     config directory ".../.tmp/ovl/config"; a scope that can list its own
     credentials is a configuration mistake

scope = <root>/.tmp/ok/project, config = <root>/.tmp/ok/config
  -> starts, logs "connector-node ready ... scopes=[project]"

scope = <root>/.tmp/bnd/config-backup, config = <root>/.tmp/bnd/config
  -> starts, so the separator boundary is not over-refused
```

`go test ./...` passes, including `cmd/connector-node`, whose fixture had to be
corrected: `writeNodePolicy` created the scope inside the config directory, so the
fixture encoded the very misconfiguration this issue is about. The scope is now a
sibling `t.TempDir()`.
