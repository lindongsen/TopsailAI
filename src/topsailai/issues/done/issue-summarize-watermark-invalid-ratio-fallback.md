---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Invalid Watermark Ratio Fallback Is Not Atomic

## Symptom

When only one LOW or HIGH watermark environment value was malformed, the valid counterpart was retained instead of resetting the pair to defaults `0.73` and `0.93`. This contradicted the documented ordered-pair contract and could produce behavior different from the configured LOW/HIGH invariant.

## Root cause

`ContextRuntimeBase._get_watermark_ratios()` passed an independent default to each `EnvReaderInstance.get()` call. `EnvReader.get()` replaces an unset or conversion-failed value with that call's default before returning, so pair validation could no longer distinguish malformed input from an explicitly configured default. For example, malformed LOW plus HIGH `0.90` became `0.73/0.90`, which still satisfied `0 < LOW < HIGH < 1` and escaped paired fallback.

## Resolution

The ratio reader now parses both values without per-key defaults and applies defaults only after validating the complete pair. Any missing, malformed, non-finite, out-of-range, equal, or reversed pair therefore resolves atomically to `0.73/0.93`.

A focused unit regression covers malformed LOW and malformed HIGH through the real environment reader. The focused source unit suite and summarize-watermark BDD suite both pass.

## Prevention

For configuration values that form one invariant-bearing tuple, preserve missing and parse-failure states until the tuple is validated; do not independently normalize members before pair validation. Test malformed input on every tuple member through the real configuration boundary.
