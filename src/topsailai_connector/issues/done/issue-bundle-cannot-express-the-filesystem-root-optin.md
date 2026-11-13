---
maintainer: AI
author: DawsonLin
status: done
severity: medium
created: 2026-11-14
resolved: 2026-11-14
platform: all
---

# A packaged bundle cannot express the filesystem-root opt-in

## Symptom

The Node accepts `allow_filesystem_root: true` in a policy file, but a bundle
produced by `make package` or `make package-windows` could not use it. The start
scripts refused a volume root before the Node ever saw the policy, and the
generated `policy.yaml` never contained the key, so even a hand-edited `scopes.txt`
naming a drive root was refused by the script rather than passed through.

## Impact

The opt-in was unreachable on the delivery path the operator actually uses. The
Windows deployment on `gd-dev-windows` runs from a bundle, so the fourteen
per-directory scopes remained the only way to cover that volume, with the two gaps
recorded in `issues/done/issue-no-way-to-expose-a-whole-volume.md`: files directly
under the volume root were unreachable, and a top-level directory created later was
silently not covered.

## Root cause

The start scripts were written before the opt-in existed, and they duplicate the
Node's startup refusals so the message appears next to the person who can fix it.
That duplication is deliberate and useful, but it means every new policy key has
two places to update and only one of them was updated.

The scripts also generate the policy from `scopes.txt`, which has no syntax for a
policy-level key. `scopes.txt` is a list of `name=path` lines, so there is nowhere
to state `allow_filesystem_root`.

## Detection failure

No test asserted that a bundle can express every policy key the Node accepts. The
packaging e2e test checked that a scope listed in `scopes.txt` is served and that a
scope not listed is not, which is a different property. A key added to the Node
therefore had no test that would notice the bundle cannot carry it.

## Resolution

The decision went to the packaging operator, not the bundle recipient, because the
blast radius should be written down by the person who understands it and the
recipient of a bundle is not that person. A recipient editing `scopes.txt` would be
a weaker control than an operator-set flag.

`PACKAGE_ALLOW_FILESYSTEM_ROOT` is a Make variable, unset by default. `1` enables
it, empty or `0` disables it, and any other value fails packaging rather than being
read as "off". The decision is written into the bundle as a file named
`allow_filesystem_root` holding `0` or `1`, and the start scripts read that file.

The file rather than an environment variable is the point: an environment variable
would let whoever runs the bundle widen the blast radius without touching a file,
which is exactly the control the operator/recipient split exists to prevent. The
file is always written, so "not enabled" is a recorded decision rather than a
missing file that could mean either.

Under the opt-in the start scripts skip the volume-root and config-overlap
refusals, the same two the Node relaxes. The home-directory refusal is never
skipped, because the Node refuses it unconditionally and a bundle that allowed it
would fail on the recipient's machine instead of at packaging time.

## Files changed

| File | Change |
|---|---|
| `Makefile` | variable, comment, help text, pass-through to the packaging script |
| `packaging/build-package.sh` | read, strict validate, write `allow_filesystem_root`, summary line |
| `packaging/start.sh` | read the file, emit the key, gate two refusals |
| `packaging/start.ps1` | the same three changes for Windows |
| `packaging/bundle-README.md` | explain the file to the recipient |
| `tests/e2e/verify_package.sh` | five assertions covering both variants and the invalid value |
| `Makefile` (`e2e` target) | run `verify_package.sh`, so the assertions actually execute |
| `docs/permission-design.md` | how a bundle expresses the opt-in, plus three checklist items |

## Verification

Linux, on this build host:

| Check | Result |
|---|---|
| Bundle built without the flag records `0` | `cat allow_filesystem_root` -> `0` |
| That bundle refuses `/` | `start: scope 'root' is '/', whose blast radius is the whole machine`, rc=1 |
| Bundle built with the flag records `1` | `cat allow_filesystem_root` -> `1` |
| That bundle accepts `/` | `start: scope root -> /`, then the dummy-token refusal, as expected |
| Generated policy | `allow_filesystem_root: true` and `root: path: "/"` |
| Invalid value | `PACKAGE_ALLOW_FILESYSTEM_ROOT=true` -> rc=2, message names the flag |

Windows, on the real host `gd-dev-windows` (192.168.2.6, `i-rxrgnhw9`) over SSH:

| Check | Result |
|---|---|
| Bundle without the flag records `0` | `off allow_filesystem_root=0` |
| That bundle refuses `C:\` | rc=1, `scope 'root' is the root of a drive, whose blast radius is the whole volume` |
| Bundle with the flag records `1` | `on allow_filesystem_root=1` |
| That bundle accepts `C:\` | `start: scope root -> C:\`, Node logged `scopes=[root]` |
| Generated policy | `allow_filesystem_root: true` and `root: path: "C:\\"` |
| Home directory still refused under the opt-in | rc=1, `scope 'home' is the home directory` |
| Invalid value | rc=1, `$AllowRootFile holds 'true'; it must hold 0 or 1` |

`tests/e2e/verify_package.sh` was run directly and passed all five new assertions,
and it is now part of the `e2e` target so `make check` executes it.

## Note on documentation placement

`PACKAGE_ALLOW_FILESYSTEM_ROOT` is a Make variable, not a process environment
variable, so it is documented in the Makefile help, the bundle README and
`docs/permission-design.md` rather than in `docs/Environment_Variables.md`. That
document describes what the two binaries read from the environment, and a Make
variable is not read by a binary.
