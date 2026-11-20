---
maintainer: AI
author: DawsonLin
status: fixed
created: 2026-11-20
updated: 2026-11-20
severity: medium
---

# A reused scratch config directory made the second packaging run fail

## Symptom

The second `make package PACKAGE_EMBED_IDENTITY=1` run failed, or produced a binary
whose embedded identity disagreed with the env file it had just written. The scratch
config directory `.tmp/embed/config` still held the identity and credential from the
previous run.

## Root cause

`packaging/build-package.sh` generates the identity and credential by running the
host Node's own `id` and `credential add` commands against a scratch config
directory. The directory was created but never cleared, so the second run found an
existing identity file and an existing credential file. `EnsureIdentity` and
`EnsureCredentials` both return the existing value rather than creating a new one,
which is the correct runtime behaviour and the wrong packaging behaviour: the
packaging step needs a fresh identity per package.

The consequence is worse than a failed build. A run that silently reused the previous
identity would produce two packages sharing one node id, which is the identity
collision the design document warns about, and the env file would record values that
are not the ones compiled in.

## Detection gap

The first packaging run always succeeds, because the directory does not exist yet.
The defect only appears on the second run, and the first run is the one a developer
tests. Nothing asserted that two consecutive runs produce two different identities.

## Fix

The script removes the scratch config directory before generating, and logs the
removal so the deletion is visible:

```
package: removing the previous scratch config directory <path>
```

The removal is scoped to a directory the script itself creates under `.tmp/`, so it
cannot delete anything the operator owns.

## Prevention

A packaging step that generates a value must start from a state that cannot contain a
previous value. Clear the scratch directory first and log the removal, because a
silent reuse produces two artifacts that look correct and disagree.

Test a packaging mode by running it twice. The second run is where a reused scratch
state, a stale output file and an overwrite refusal all appear.
