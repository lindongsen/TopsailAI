---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
---

# Severe repetition check false-positives on formatted output

## Symptom

Session `wa-fc746aa24c8c` raised `LLM Mistake: Severe repetition loop pattern
detected!` 22 times while producing a capability inventory that contains Go code
blocks and Markdown tables. The generated content was not repetitive: each
repeated line is structural formatting, and each fuzzy-matched pair carries a
different meaning.

## Evidence

Measured on the actual response that triggered the check:

- `total_lines=1411`, `exact_duplicate_count=304`, `fuzzy_duplicate_count=173`,
  `repetition_rate=0.3381`, threshold `0.3`.
- Exact duplicates are formatting only: `}` 110, ` ``` ` 76, ` ```go ` 32,
  `|---|---|` 5, `|---|---|---|---|---|` 3, `|---|---|---|` 4, `},` 8.
- Fuzzy duplicates are semantically distinct, for example
  `list cd show info ... logs` versus `list endpoints cd show info ...` at
  similarity `0.8966`, and `- catalog 有、矩阵无：**空**` versus
  `- 矩阵有、catalog 无：**空**` at `0.8095`.

## Root cause

`utils/text_tool.py::check_repetition()` counts every non-empty line equally and
uses character-level `SequenceMatcher` similarity for fuzzy matching. Neither
step distinguishes structural formatting from repeated content, and character
similarity treats two different command inventories as near-duplicates because
they share most of their characters.

## Impact

Each false positive raises `ModelServiceError`, which the retry loop in
`ai_base/llm_base.py` catches and retries after a 30-second sleep, up to 18
attempts. 22 triggers cost roughly 11 minutes of pure sleeping plus 22 full
regenerations of a long response, and the regenerated response is likely to
contain the same formatting and be rejected again.

## Proposed fix

- Exclude formatting-only lines from both numerator and denominator: code
  fences, lone braces and `},`, and Markdown table separator rows.
- Require token overlap for fuzzy matches instead of character similarity alone.
- Log the excluded-line count so a future false positive stays diagnosable.
- Keep a negative control whose fixture is a genuine loop repeating a full
  sentence, so the guard cannot silently disable detection.

## Constraint

`tests/unit/test_topsailai_utils_text_tool.py::test_fuzzy_duplicate_similarity_value`
uses `"abcdef\nabcdeg"`, which shares no whole token. A strict token-overlap rule
would break it, so the character-level path must remain reachable or that test
must be revised deliberately.

## Runtime mitigation applied

`TOPSAILAI_REFUSE_SEVERE_REPETITION` was set to `0` in the affected process
memory only. The check still computes and logs the rate; it no longer raises.
This mitigation disappears when the process exits.

## Closure verification (2026-11-17)

Resolved in HEAD.

- `684a3feb fix: exclude structural lines from repetition judgement and remove quadratic scan`
  (2026-11-15) is an ancestor of HEAD `5da6bb49f651a501b041486590a0c87e5acd85c6`.
- `utils/text_tool.py:13-31` defines `is_structural_line()`, which excludes fenced code
  delimiters, table separators and symbol-only lines from the repetition judgement, so formatted
  output no longer trips the severe-repetition check.
- The same commit removed the quadratic scan from the judgement path.
