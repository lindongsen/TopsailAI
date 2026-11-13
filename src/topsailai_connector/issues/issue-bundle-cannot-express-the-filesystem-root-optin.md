---
maintainer: AI
author: DawsonLin
status: open
severity: medium
created: 2026-11-14
platform: all
---

# A packaged bundle cannot express the filesystem-root opt-in

## Symptom

The Node now accepts `allow_filesystem_root: true` in a policy file, but a bundle
produced by `make package` or `make package-windows` cannot use it. The start
scripts refuse a volume root before the Node ever sees the policy:

```
packaging/start.ps1:195:  Fail "scope '$name' is the root of a drive, whose blast radius is the whole volume"
packaging/start.sh:134:   fail "scope '$name' is '/', whose blast radius is the whole machine"
```

And the generated `policy.yaml` never contains the key, so even a hand-edited
`scopes.txt` naming a drive root is refused by the script rather than passed
through:

```
packaging/start.sh:97-98:    echo "version: 1" / echo "scopes:"
packaging/start.ps1:160-161: $lines.Add('version: 1') / $lines.Add('scopes:')
```

## Impact

The opt-in is unreachable on the delivery path the operator actually uses. The
Windows deployment on `gd-dev-windows` runs from a bundle, so the fourteen
per-directory scopes remain the only way to cover that volume, with the two gaps
recorded in `issues/done/issue-no-way-to-expose-a-whole-volume.md`: files directly
under the volume root are unreachable, and a top-level directory created later is
silently not covered.

The Node-level fix is therefore correct but not yet usable where it matters.

## Root cause

The start scripts were written before the opt-in existed, and they duplicate the
Node's startup refusals so the message appears next to the person who can fix it.
That duplication is deliberate and useful, but it means every new policy key has
two places to update and only one of them was updated.

The scripts also generate the policy from `scopes.txt`, which has no syntax for a
policy-level key. `scopes.txt` is a list of `name=path` lines, so there is nowhere
to state `allow_filesystem_root`.

## Detection failure

No test asserts that a bundle can express every policy key the Node accepts. The
packaging e2e test (`tests/e2e/verify_package.sh`) checks that a scope listed in
`scopes.txt` is served and that a scope not listed is not, which is a different
property. A key added to the Node therefore has no test that would notice the
bundle cannot carry it.

## Fix direction

Two changes are needed, and the second is the one that needs a decision:

1. Let `scopes.txt` state the opt-in, for example a `!allow_filesystem_root` line
   or a `allow_filesystem_root=true` entry distinguished from a scope by having no
   path. The scripts then emit the key and skip the drive-root refusal.
2. Decide whether the bundle should permit a volume root at all. A bundle is handed
   to someone who did not write the policy, so an opt-in that the recipient can set
   by editing one line is a weaker control than an opt-in the operator writes. The
   alternative is a packaging-time variable, such as
   `PACKAGE_ALLOW_FILESYSTEM_ROOT=1`, which puts the decision in the operator's
   hands and keeps the recipient from widening the blast radius by editing a text
   file.

The second option is the one that matches the design's intent: the blast radius
should be written down by the person who understands it, and the recipient of a
bundle is not that person.

## Not yet done

No code change has been made. The Node-level opt-in is complete and tested; the
bundle path is recorded here so the gap is not mistaken for a working feature.
