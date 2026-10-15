---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: open
---

# Issue: U3 first-byte terminal handoff defects

## Symptoms

The U3 first-byte timeout implementation had two terminal handoff defects:

- A late EOF or ERROR publication could bypass the warn-only diagnostic path because the worker handled the warning only for VALUE outcomes. When the consumer had already observed the committed outcome, no warning was emitted.
- An explicit timing ticket was resumed before the first `next()` call and paused only from generator finalization, so caller processing after first-item delivery was incorrectly counted as active time.

## Root Causes

In `ai_base/llm_control/first_byte_timeout.py`, terminal publication and consumer dispatch used separate warning paths, and the explicit-ticket pause was located in the generator cleanup path rather than immediately after the consumer claimed the first terminal outcome.

## Fix

The production change adds a unified consumer-side late-terminal warning check for VALUE, ERROR, and EOF outcomes, preserving the existing warning latch and diagnostic protection. It also pauses an explicit ticket once after first-item claim and before VALUE delivery, EOF return, or ERROR propagation, with finalization retained only as a no-duplicate fallback and local-owner cleanup preserved.

The original request is not restarted, EOF performs no extra read, production continuation behavior is unchanged, and close remains at-most-once.

## Authorized Test Migration

Human authorization approved the precise migration of the existing pause/tail test: the first pause failure remains primary, prevents first-value delivery and tail reads, and occurs exactly once with one close. The actual test is in `tests/unit/test_topsailai_ai_base_llm_control_terminal_cleanup_regression.py:48`, not in the restored legacy timeout file named imprecisely by the design. The restored file `tests/unit/test_topsailai_ai_base_llm_control_first_byte_timeout.py` remains identical to HEAD.

## Verification

Focused P2 regressions passed 22 tests after the deterministic boundary coverage was completed. The approved U2 six-file gate passed 89 tests. The focused U3 matrix passed 77 tests, and the U3 first-byte BDD retry plus cleanup set passed 15 tests. Syntax, AST, and real-import checks passed for changed production and test modules. No commit or staging was performed in the implementation turn.
