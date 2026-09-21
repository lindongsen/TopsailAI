---
maintainer: AI
workspace: /TopsailAI/src/topsailai
status: resolved
---

# JEV Score Criteria Shape Rejected by Upstream

## Trigger

A live JEV Tool score request returned HTTP 422 while noul and choice requests succeeded. The Tool required score criteria to be a non-empty object, even though the deployed service requires an ordered array containing 2–10 levels; each level may be a string, object, or array.

## Impact

Every score request accepted by the local Tool contract used an upstream-incompatible criteria shape and was rejected before evaluation, so the advertised score capability was unusable.

## Resolution

Validate choice and score criteria separately: choice retains its non-empty object contract, while score requires an ordered 2–10 item array with only string, object, or array levels. Update the LLM-facing Tool docstring and prompt, and add unit and BDD regressions for validation, wire ordering, and structured score responses.

## Verification

The public Tool completed a live score evaluation with `status=ok` using minimal synthetic context. Focused JEV unit tests passed 69 tests, JEV BDD passed 4 scenarios, and the project unit runner passed all 229 test files.
