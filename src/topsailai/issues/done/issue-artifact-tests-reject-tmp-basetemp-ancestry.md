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

# Issue: Artifact Tests Reject the Default `/tmp` Basetemp Ancestry

## Symptom

A direct `pytest tests/unit/test_topsailai_hooks` invocation reported 255 failures.
Every failure converged on one assertion in `artifact_lease_helpers.py`:

```text
assert result.accepted and result.lease is not None
```

The capture result carried `errors: ('trust_rejected',)` and `lease: None`.

## Root Cause

`hooks/artifact_validation.py::_validate_directory_status()` rejects any
source-ancestry directory whose mode has group or other write bits
(`mode & 0o022`). The default pytest basetemp lives under `/tmp`, whose mode is
`0o777`, so no source tree created there can ever pass artifact trust.

A controlled three-directory probe isolated the cause to ancestry mode alone:

| Base directory | Ancestry modes | Capture result |
|---|---|---|
| `/tmp` | `/ 0o755` -> `/tmp 0o777` -> dir `0o700` | `accepted: False`, `trust_rejected` |
| `/root` | `/ 0o755` -> `/root 0o700` -> dir `0o700` | `accepted: True` |
| `/TopsailAI` | `/ 0o755` -> `/TopsailAI 0o755` -> dir `0o700` | `accepted: True` |

Changing only the basetemp directory moved
`test_hook_artifact_leases.py` from 31 failed / 9 passed to 40 passed.

## Why It Was Not a Product Defect

The trust rule is intentional: a group- or other-writable ancestor lets another
user replace the source tree between validation and execution. The defect was
that the tests depended on ambient basetemp location.

The repository already contained the knowledge:
`tests/unit/test_topsailai_hooks/conftest.py` defines a `trust_eligible_tmp_path`
fixture whose docstring states that the default `/tmp` basetemp "can never host a
trusted source tree". It was opt-in, and only 5 of 134 test files used it, so the
artifact series never benefited.

The mandatory runner was unaffected because `tests/run_tests.py` creates its own
basetemp under `.tmp` with mode `0o755`.

## Fix

`tests/unit/test_topsailai_hooks/conftest.py` now redirects the default basetemp
to a trust-eligible root through `pytest_configure`, so a direct `pytest`
invocation behaves like the runner. Two properties were required:

- The path is unique per process (`hooks-basetemp-{pid}`), because pytest deletes
  a given basetemp before using it; a fixed path would let concurrent runs erase
  each other's trees.
- `pytest_unconfigure` removes the tree the hook created, so repeated runs do not
  accumulate directories.

An explicit `--basetemp` still wins, preserving the documented opt-out for
privilege-dropping and socket-path cases.

## Verification

| Check | Result |
|---|---|
| `test_hook_artifact_leases.py`, no `--basetemp` | 40 passed |
| Two concurrent pytest processes | both 40 passed, no residue |
| Explicit `--basetemp=/tmp/...` | 31 failed / 9 passed (hook correctly defers) |
| Full hooks directory, explicit basetemp | 4907 passed |
| Full hooks directory, hook active | 4906 passed, 1 failed |

The single failure was
`test_module_worker_transport.py::test_descendant_cleanup[descendant-success]`
with `cleanup_confirmed` false. It passed 3 isolated reruns and 5 consecutive
file-level reruns, and the same file is already listed as load-sensitive in
`issues/done/issue-hooks-test-runner-parallel-contention.md`. It is a
pre-existing contention flake, not a regression from this change.

## Regression Scope

- Direct `pytest` invocations of `tests/unit/test_topsailai_hooks` now use a
  `.tmp` basetemp instead of `/tmp`.
- Tests that require the default basetemp keep working by passing an explicit
  `--basetemp`.
- No production code changed.
