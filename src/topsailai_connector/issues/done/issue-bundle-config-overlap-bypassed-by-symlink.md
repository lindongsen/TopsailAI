---
maintainer: AI
author: DawsonLin
status: done
severity: medium
created: 2026-11-13
platform: all
---

# The bundle's config-overlap guard was bypassed by a symlinked bundle path

## Symptom

`packaging/start.sh` and `packaging/start.ps1` refuse a scope whose path overlaps
the bundle's own `config` directory, because that directory holds `identity`,
`tunnel_token` and `policy.yaml`. The guard compared two paths that were resolved
in different ways, so it never matched when the bundle was reached through a
symlink or a junction.

Reproduced on Linux with the scope set to the real bundle directory, which
contains `config`:

```
$ ln -s .../real/bundle .../link
$ printf 'project=%s\n' .../real/bundle > .../link/scopes.txt
$ bash .../link/start.sh
start: scope project -> .../real/bundle
start: config .../link/config
connector-node: CONNECTOR_NODE_TUNNEL_TOKEN is 3 bytes, want at least 16
```

The Node started. The scope was the bundle directory itself, so `config` was
inside a served scope.

## Impact

The Node's deny list still refuses `config/identity` and `config/policy.yaml` by
resolved path, so the credentials were not readable. What was reachable is the
metadata the startup check exists to prevent: `file.list config` enumerates the
names and sizes of the Node's own credential files. This is the same leak that
`issues/issue-scope-may-contain-config-directory.md` records, reached through a
different route.

The severity is medium rather than low because the bypass needs no
misconfiguration by the user: installing a bundle behind a symlink is a normal
way to place it, and the guard silently stopped working.

## Root cause

Two different resolution rules on the two sides of one comparison.

- `start.sh` computed `HERE` with `pwd`, which keeps symlinks, while scope paths
  were resolved with `pwd -P`, which follows them. A bundle reached through a
  symlink therefore had a logical `HERE` and a physical scope path, and
  `is_within` compared a symlinked path against a real one.
- `start.ps1` computed `$Here` with `Split-Path -Parent`, which does no
  resolution at all, while scope paths used `Resolve-Path`. Worse, `Resolve-Path`
  on PowerShell 5.1 returns a junction's own path unchanged, so even making both
  sides use `Resolve-Path` would not have fixed it.

## Detection failure

The end-to-end check started the bundle from its real path, so the two forms
happened to agree and the guard appeared to work. No check exercised a bundle
reached through a link, which is the only case where the two forms differ.

A second detection failure: the first fix attempt replaced `pwd` with `pwd -P` in
the shell script and `Resolve-Path` in the PowerShell script, and the PowerShell
half was a no-op. It was caught only by running the junction case on a real
Windows host and reading the printed `config` path, not by reading the diff.

## Fix

- `start.sh` resolves `HERE` with `pwd -P`, so both sides of the comparison are
  physical.
- `start.ps1` gained `Resolve-PhysicalPath`, which walks the path component by
  component and follows every junction and symbolic link it finds, because a
  junction can sit at any level rather than only at the leaf. Both `$Here` and
  every scope path now go through it.

## Verification

Linux, with the scope set to the real bundle directory and the bundle reached
through a symlink:

```
start: scope 'project' path '.../real/bundle' overlaps the bundle's config
directory '.../real/bundle/config'; move the folder or the bundle
```

Windows Server 2022, with the scope set to the real bundle directory and the
bundle reached through a junction:

```
Fail : start: scope 'project' path 'C:\connector-test\bundle\connector-node-windows-amd64'
overlaps the bundle's config directory
C:\connector-test\bundle\connector-node-windows-amd64\config; move the folder or the bundle
```

The normal layout still starts on both platforms, and
`tests/e2e/verify_package.sh` now asserts the symlinked-bundle refusal so the
defect cannot return silently.

## Verified on

Linux build host and Windows Server 2022 (10.0.20348.587), PowerShell 5.1.20348.558.
