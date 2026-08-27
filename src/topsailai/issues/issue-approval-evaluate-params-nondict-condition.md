---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
references:
  - /TopsailAI/src/topsailai/ai_base/tool_approval/matcher.py
---

# Issue: `_evaluate_params` raises on a non-dict parameter condition

## Symptom

`ai_base/tool_approval/matcher.py::_evaluate_params()` iterates the rule `params`
list and immediately calls `condition.get("param")`. When an element is not a
mapping (for example a bare string inside `params`), evaluation raises
`AttributeError: 'str' object has no attribute 'get'` instead of being skipped as
a misconfigured condition.

## Reachability

`_parse_rule()` validates that each rule is a mapping and that `params` is a
list, but it does not validate that every element of `params` is a mapping. A
`RuleMatch`/`ApprovalRule` built directly in code (not through
`TOPSAILAI_TOOL_APPROVAL_RULES`) therefore reaches the crash path. Rules loaded
from JSON are protected only incidentally by the element type check that the
detail API performs.

## Contrast with the new detail API

`_evaluate_params_detail()` (added for the approval-request display work)
records an error-carrying `ConditionMatch` for a non-mapping element and
continues, so the same input is tolerated there. The two evaluators therefore
diverge in robustness even though their boolean result is otherwise identical.

## Impact

Advisory path only: the approval gate is fail-open for configuration problems,
but an unhandled `AttributeError` here propagates out of `ToolApprovalInstance.decide()`
and aborts the tool call rather than degrading to "condition ignored".

## Suggested fix

Skip non-mapping conditions inside `_evaluate_params()` with a warning log,
mirroring `_evaluate_params_detail()`, and add a unit test that passes a mixed
`params` list (mapping plus non-mapping) through both evaluators.

## Discovered while

Implementing readable argument rendering and matched-content highlighting for
the tool approval request prompt. A parity test between the two evaluators was
written with a non-dict condition, which exposed the pre-existing crash; the
parity case was removed from the new tests rather than changing legacy behavior
in the same change.
