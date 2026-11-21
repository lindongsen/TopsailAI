---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: done
---

# Issue: `make -n` Dry Run Fails Because Prerequisites Are Skipped

## Symptom

`tests/unit/test_bdd_entrypoints.py` reported two failures:

```text
FAILED test_packaged_gate_is_explicit
FAILED test_release_gate_requires_source_slow_and_packaged_verification
```

Both raised `subprocess.CalledProcessError: ... returned non-zero exit status 2`.

## Root Cause

`make -n` does not execute prerequisites, but it does execute recipe lines that
contain `$(MAKE)`. The `test-release` and `test-bdd-packaged` recipes reach
`plugins-unit-test`, whose recipe pipes output into `tee`:

```text
tee: .tmp/test-logs/plugins-unit-test_<timestamp>.log: No such file or directory
make: *** [Makefile:154: plugins-unit-test] Error 1
```

`LOG_DIR` is normally created by the `test-log-init` prerequisite, which a dry
run skips. `tee` therefore fails, and `pipefail` propagates the failure as exit
status 2.

## Why It Was Not a Product Defect

The Makefile is correct for real invocations: `test-log-init` runs first and
creates `LOG_DIR`. The defect was that the test's `dry_run` helper assumed a dry
run has no side effects, so it depended on ambient state that a fresh checkout
does not have.

## Fix

`dry_run` now creates `LOG_DIR` before invoking `make -n`, so the assertion about
gate structure no longer depends on whether a previous real run happened to leave
the directory behind.

## Verification

| Check | Result |
|---|---|
| `LOG_DIR` removed, fix present | 4 passed |
| `LOG_DIR` removed, fix reverted | 2 failed / 2 passed |
| `LOG_DIR` auto-created by the helper | confirmed |

The negative control proves the test observes the directory dependency rather
than passing incidentally.

## Regression Scope

- Only the test helper changed; the Makefile is untouched.
- Real `make` invocations still create `LOG_DIR` through `test-log-init`.
