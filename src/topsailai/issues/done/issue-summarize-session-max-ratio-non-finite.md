---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Non-Finite Session Summary Ratio Bypasses Validation

## Symptom

Setting `TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO` to `NaN` caused Agent2LLM summarization to raise `ValueError` while converting the derived session-message threshold to an integer instead of falling back to the documented default ratio `0.5`.

## Root cause

The validation only checked whether the parsed float was outside `(0, 1]`. Ordered comparisons with `NaN` are both false, so `NaN` bypassed the guard and reached `int(ctx_quantity_threshold * session_max_ratio)`.

## Resolution

The ratio validation now explicitly rejects every non-finite float with `math.isfinite()` before applying range checks. `NaN`, positive infinity, and negative infinity therefore use the existing `0.5` fallback.

A focused unit regression exercises the existing out-of-range case together with `NaN` and both infinities through the real environment reader.

## Prevention

Validate floating-point configuration for finiteness before range checks, because range comparisons alone cannot reliably reject all non-finite values.
