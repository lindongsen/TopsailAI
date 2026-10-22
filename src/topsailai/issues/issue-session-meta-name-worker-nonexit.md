---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: open
---

# Session metadata BDD naming worker does not exit

## Symptom

`tests/bdd/test_session_meta_name.py` fails at `tests/bdd/session_name_startup_context_harness.py:619` with `AssertionError: assert not worker.is_alive()`. The session-name worker does not exit within the 10-second join during child cleanup.

## Reproduction

Run `pytest -q --color=no --tb=line --disable-warnings tests/bdd/test_session_meta_name.py` from the workspace.

## Evidence

The failure was reproduced on the current tree and on an isolated pristine-HEAD worktree at `73cff13831657eb3af01d97e96e996e353601663`, with the same worker non-exit assertion. One pristine-HEAD run also observed the harness-internal 30-second child timeout.

## Impact

This blocks BDD acceptance for the hostname metadata change because the new hostname assertions cannot be evaluated.

## Status

PRE-EXISTING and out of scope for the hostname metadata change. The root cause is not confirmed; the cause of the worker non-exit is unknown.
