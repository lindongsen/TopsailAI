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

## Analysis (2026-11-17)

Status: **open, confirmed defect, but the stated impact is now inaccurate.**

### Confirmed

`_evaluate_params()` at `ai_base/tool_approval/matcher.py:210-211` indexes every
element as a mapping, while `_evaluate_params_detail()` at line 257 guards with
`isinstance(condition, dict)`. `_parse_rule()` (line 316-318) accepts any list for
`params`, so a JSON rule with a bare string element reaches the crash path.

Executed reproduction with `TOPSAILAI_TOOL_APPROVAL_RULES` set to a rule whose
`params` is `[{"param": "command", "op": "exists"}, "bare-string-condition"]`:

- `match_approval_rule(...)` raises `AttributeError: 'str' object has no attribute 'get'`.
- `match_approval_rule_detail(...)` returns no match and reports one
  `ConditionMatch(op="invalid", error="not an object: ...")`.
- `_evaluate_params_detail(...)` returns `(False, [valid condition, invalid condition])`.

### Impact claim is stale

The issue says the `AttributeError` "propagates out of
`ToolApprovalInstance.decide()` and aborts the tool call". That is no longer true:
commit `e69c05c1` replaced `match_approval_rule` with `match_approval_rule_detail`
inside `decide()`. Executed check with approval enabled and the same malformed
rule: `decide()` returns `no_approval` without raising, and the decorator path
(`ai_base/tool_approval/decorator.py:115`) therefore does not abort.

So the defect is real but currently reachable only through the exported boolean
API `match_approval_rule` / `find_matching_rule` and direct `_evaluate_params`
calls. No production caller uses it today; the exposure is the public export in
`ai_base/tool_approval/__init__.py`.

### The suggested fix is wrong as written

The issue proposes "skip non-mapping conditions ... mirroring
`_evaluate_params_detail()`". The detail evaluator does **not** skip: it appends
`False` to `results` and then applies `all`/`any`. Skipping instead changes the
boolean outcome and breaks the documented parity contract
(`test_boolean_parity_with_evaluate_params`).

Measured with `params=[{"param":"command","op":"exists"}, "bad"]` and
`{"command":"ls"}`:

| logic | detail | "skip" fix | parity |
|---|---|---|---|
| and | False | True | broken |
| or | True | True | ok |

Treating a non-mapping element as a failed condition (`results.append(False)`)
matches the detail evaluator in all five probed cases, including `and`/`or` with
only invalid elements.

### Recommended repair

1. In `_evaluate_params()`, guard each element with `isinstance(condition, dict)`;
   on failure log a warning and append `False` to the result set instead of
   skipping, then apply `all`/`any` exactly as the detail evaluator does.
2. Keep the short-circuit behavior for valid conditions so existing semantics and
   performance are unchanged.
3. Add a parity test that includes a non-mapping element for both `and` and `or`,
   restoring the case that was removed when the defect was found.
4. Optionally reject non-mapping `params` elements in `_parse_rule()` so a
   configuration error is reported once at load time rather than per call.

No code change was made in this analysis pass.
