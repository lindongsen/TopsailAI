---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
references:
  - /TopsailAI/src/topsailai/ai_base/llm_control/message.py
---

# Issue: A JSON array of bare scalars crashes `format_response`

## Symptom

When the LLM answers with a JSON array whose elements are bare scalars instead of
step objects, for example:

```json
["fix: wait for the channel before the first inventory publish"]
```

`format_response()` accepts the parsed array as a step list, and
`format_response_finally()` then calls `update_response_item(item)` on that `str`.
`update_response_item()` immediately calls `item.get("step_name")`, so the whole
agent turn dies with:

```text
AttributeError: 'str' object has no attribute 'get'
```

Observed in session `wa-74fa6c1621f5` (pid `608827`) at `2026-11-07 08:12:19`,
surfacing to the operator as `Error: Some errors have occurred: ['str' object has
no attribute 'get']`.

## Reachability

Any model or provider can emit this shape; it is not provider-specific. The
triggering payload was the only `llm.response.raw` event in that session whose
content started with `[`. The crash is deterministic and was reproduced with a
standalone script before the fix.

Two independent injection paths existed:

1. `format_response_finally()` guarded the multi-element branch
   (`if not isinstance(item, dict): continue`) but not the single-element branch,
   which called `update_response_item(item)` unguarded.
2. The `finally` block of `format_response()` executed
   `response.append(new_response)` whenever the hook returned a non-list, so a
   bare `str` could enter the step list by a second route.

`fix_llm_mistakes()` also indexed `response[0]` and called `len(item)` without
checking that the single element was a mapping.

## Impact

The failure aborts the entire User2Agent turn after the work was already done.
In the observed session the agent had already produced a complete `final_answer`;
the fatal request was the follow-up call that generates the commit message, so the
pending logical unit was never committed.

Because `ai_base/llm_base.py` catches `except (KeyError, Exception)`, this internal
programming error is additionally misclassified as a retryable provider failure and
logged as `Some errors have occurred: [...]` instead of surfacing as a defect.

## Fix

Normalize instead of skip. Skipping would only move the crash downstream into
`pre_execute()` (`step["step_name"]` raises `TypeError`) and would silently discard
the model's text.

- Added `_normalize_response_items(response)`, which converts every non-dict item
  into `{"step_name": "thought", "raw_text": <text>}` in place and emits one
  warning per call.
- Called it from `format_response_finally()`, from the already-structured
  `list`/`dict` early return of `format_response()`, from both
  `TOPSAILAI_HOOK_AFTER_LLM_CHAT` return paths, and from the `finally`-block
  append path.
- Added a defensive `if not isinstance(item, dict): return item` guard in
  `update_response_item()`.
- Guarded the single-element branch of `fix_llm_mistakes()` with
  `isinstance(response[0], dict)`.
- Removed the now-unreachable `isinstance` skip in the multi-element branch of
  `format_response_finally()`.

The invariant is now: every step returned by `format_response()` is a dict.

## Verification

- Original payload no longer raises and yields one `thought` step preserving the
  model text.
- 12 regression tests added in
  `tests/unit/test_topsailai_ai_base_llm_control_message.py`
  (`TestNonObjectStepNormalization`), covering bare strings, multiple bare
  strings, numeric and null scalars, list input with scalars, the non-dict
  invariant across six payloads, `format_response_finally`, the
  `update_response_item` guard, the `fix_llm_mistakes` guard, warning-once,
  dict identity preservation, and non-list passthrough.
- Negative control: removing the normalization call re-introduces 6 failures with
  the original `AttributeError`, proving the tests guard the defect.
- Target file: 109 passed. Related LLM/agent modules: 567 passed.

## Retry classification of internal errors

`ai_base/llm_base.py` previously classified `AttributeError` as a retryable
provider failure through `except (KeyError, Exception)`. Because the bounded
retry loop runs 18 attempts with sleeps of up to 120 seconds, an internal
programming defect appeared as roughly 765 seconds of hanging and then surfaced
as a misleading `LLMRetryExhaustedError`.

Resolution: `AttributeError` now logs the traceback and re-raises immediately,
so an internal contract violation surfaces at once with one provider call. The
redundant `KeyError` in the tuple was removed because it is already a subclass of
`Exception`.

`TypeError` deliberately keeps its existing retry behavior. An empty LLM
response raises `TypeError` while parsing, and retrying that case is designed
behavior covered by `test_chat_handles_type_error` and the `retry_reason ==
"type_error"` assertions. Re-raising `TypeError` immediately would break it.

Regression tests: `test_chat_reraises_attribute_error_without_retrying` asserts a
single provider call and no sleep, and `test_chat_attribute_error_is_logged_with_traceback`
asserts the diagnostic log. Removing the new branch makes both fail with
`LLMRetryExhaustedError`, proving they guard the defect.

## Discovered while

Analyzing why session `wa-74fa6c1621f5` terminated abnormally. The session
metadata still reports `status="running"` and `end_ts=null` for a dead process,
because the normal error-status bookkeeping in `AgentChat.run()` never executed;
the termination mechanism itself (external kill versus abnormal exit) remains
unestablished.
