---
maintainer: AI
author: DawsonLin
status: open
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
