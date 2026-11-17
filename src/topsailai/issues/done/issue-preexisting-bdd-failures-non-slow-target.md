---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: resolved
---

# Eleven pre-existing BDD failures in the non-slow core target

**Status:** open, registered only, not fixed in this change
**Date:** 2026-11-13
**Severity:** medium — the default BDD target is not green, so a real regression
in these five modules would be indistinguishable from the existing noise

## Summary

The non-slow core BDD target reports `11 failed, 792 passed, 9 deselected`.
All eleven failures are pre-existing. They were not introduced by the event
source wiring work, and they reproduce identically when the five affected
modules are run alone, without any of the new event source test files present.

This issue exists because "not introduced by this change" is not the same as
"acceptable to leave unrecorded". A permanently red default target trains
readers to ignore failures.

## Affected modules

```text
tests/bdd/test_compiled_module_discovery.py
tests/bdd/test_llm_chat_attempt_points.py
tests/bdd/test_llm_first_byte_control.py
tests/bdd/test_llm_first_byte_timeout_warning.py
tests/bdd/test_tool_execute_hooks.py
```

## Failing test ids

```text
test_compiled_module_discovery.py::test_source_discovery_exposes_the_expected_registries_and_hooks

test_llm_chat_attempt_points.py::test_named_attempt_points_deliver_exact_metadata_to_real_modules[error-normal-success]
test_llm_chat_attempt_points.py::test_named_attempt_points_deliver_exact_metadata_to_real_modules[error-failing-completed_with_errors]

test_llm_first_byte_control.py::test_consume_a_flag_from_the_existing_http_wait_hook[first_item-1-force_retry]
test_llm_first_byte_control.py::test_consume_a_flag_from_the_existing_http_wait_hook[headers--1-hard_interrupt]
test_llm_first_byte_control.py::test_consume_a_flag_from_the_existing_http_wait_hook[first_item-0.01-hard_interrupt]

test_llm_first_byte_timeout_warning.py::test_warning_precedes_a_genuine_provider_error_and_existing_retry

test_tool_execute_hooks.py::test_native_tool_outcomes_retain_their_paired_result[success]
test_tool_execute_hooks.py::test_native_tool_outcomes_retain_their_paired_result[error]
test_tool_execute_hooks.py::test_streamed_native_tool_outcomes_retain_metadataonly_observations_and_paired_results[success]
test_tool_execute_hooks.py::test_streamed_native_tool_outcomes_retain_metadataonly_observations_and_paired_results[error]
```

## Reproduction

Full non-slow target:

```text
PYTHONPATH=/TopsailAI/src/topsailai:/TopsailAI/src:/TopsailAI/src/topsailai/cli \
  python3 -B -m pytest -m "not slow and not packaged" tests/bdd -q --color=no
```

Result: `11 failed, 792 passed, 9 deselected`.

The five affected modules alone:

```text
PYTHONPATH=/TopsailAI/src/topsailai:/TopsailAI/src:/TopsailAI/src/topsailai/cli \
  python3 -B -m pytest \
    tests/bdd/test_compiled_module_discovery.py \
    tests/bdd/test_llm_chat_attempt_points.py \
    tests/bdd/test_llm_first_byte_control.py \
    tests/bdd/test_llm_first_byte_timeout_warning.py \
    tests/bdd/test_tool_execute_hooks.py \
    -q --color=no
```

Result: `11 failed, 19 passed`.

## Evidence that these are pre-existing

The same eleven test ids fail in both runs, with the same count. Running the five
modules in isolation removes every other BDD module from the process, including
the event source suite, and the failure set does not change. That rules out the
event source work as the cause.

The `cli` path entry in `PYTHONPATH` is required for the full target. Without it,
`tests/bdd/test_heartbeat_control.py` cannot import `cli_topsailai` and pytest
aborts collection with exit code 2 before any scenario runs. That collection
abort is a separate concern from the eleven failures recorded here.

## Observed failure characteristics

The failures cluster around three areas, which suggests they are not eleven
independent defects:

- Hook point discovery and registry exposure
  (`test_compiled_module_discovery`).
- LLM attempt-point metadata delivery and first-byte control flags
  (`test_llm_chat_attempt_points`, `test_llm_first_byte_control`,
  `test_llm_first_byte_timeout_warning`).
- Native tool outcome pairing through Hook observations
  (`test_tool_execute_hooks`).

The first-byte group is timing-sensitive by nature, so at least part of this set
may be flaky rather than deterministically broken. That has not been established
here and must not be assumed.

## Scope of this record

This issue registers the failures only. No production code, test code, or
configuration was changed to address them. Fixing them requires its own
investigation, its own logical unit, and its own verification.

## Next steps when this is picked up

1. Run each of the five modules alone and capture the exact assertion text, not
   only the pass/fail count.
2. Separate deterministic failures from timing-sensitive ones by repeating each
   failing test several times.
3. For any suspected regression, compare against a pristine worktree at the same
   HEAD before concluding causation.
4. Fix or quarantine each group as its own logical unit, and keep the default
   target green afterwards so future regressions are visible.

## Closure verification (2026-11-17)

Resolved. The eleven failures recorded here no longer reproduce.

Ran the five affected modules together:

```text
tests/bdd/test_compiled_module_discovery.py
tests/bdd/test_llm_chat_attempt_points.py
tests/bdd/test_llm_first_byte_control.py
tests/bdd/test_llm_first_byte_timeout_warning.py
tests/bdd/test_tool_execute_hooks.py
```

Result: **30 passed**, 0 failed. The recorded baseline was `11 failed, 19 passed` for the same
five modules, so every listed test id now passes.

The failures were fixed by the intervening Hook Point and first-byte work rather than by a
dedicated repair for this record, which is why no single commit is cited. This issue existed to
keep the red default target traceable; that purpose is now served and the target is green.

Limitation: this run used the five modules directly, not the full `-m "not slow and not packaged"`
target, so a failure elsewhere in that target is not covered by this verification.
