---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
references:
  - /TopsailAI/src/topsailai/ai_base/llm_control/message.py
  - /TopsailAI/src/topsailai/utils/json_tool.py
  - /TopsailAI/src/topsailai/tests/unit/test_topsailai_ai_base_llm_control_message.py
  - /TopsailAI/src/topsailai/tests/unit/test_topsailai_utils_json_tool.py
  - /TopsailAI/src/topsailai/tests/mistakes/response/json-with-trailing-thinking-close-tag.txt
---

# Issue: format_response fails on JSON with trailing think tag or extra text

## Status

Resolved

## Resolution

The generic JSON extraction capability was added to `src/topsailai/utils/json_tool.py` via `_extract_first_balanced_json()`. It is invoked from `fix_llm_mistakes_on_json()` before the legacy array heuristics, so leading JSON followed by trailing text such as `</thinking>` is now extracted cleanly instead of causing an `Extra data` parse error.

Key implementation points:

- Only handles JSON that starts with `{` or `[` as the first non-whitespace character.
- Does not search for JSON in the middle of arbitrary text.
- Does not handle Markdown code fences.
- Uses a stack to track nested `{}` and `[]`.
- Respects JSON string literals and escaped quotes.
- Validates the candidate substring with `safe_json_load()` before returning.

The dedicated `trailing_json_garbage` mistake fixer and its test file were not restored; the fix lives in the shared JSON utility as requested.

## Verification

### Sample response

A new sample response file was added to the mistake collection:

```text
tests/mistakes/response/json-with-trailing-thinking-close-tag.txt
```

Content:

```text
[
  {
    "step_name": "thought",
    "raw_text": "I have finished checking the available context."
  },
  {
    "step_name": "final_answer",
    "raw_text": "The requested analysis is complete."
  }
]</thinking>
```

### CLI verification

```bash
./bin/topsailai_format_response tests/mistakes/response/json-with-trailing-thinking-close-tag.txt
```

Output:

```json
[
  {
    "step_name": "thought",
    "raw_text": "I have finished checking the available context."
  },
  {
    "step_name": "final_answer",
    "raw_text": "The requested analysis is complete."
  }
]
```

Exit code: `0`

### Direct Python verification

```python
from topsailai.utils.json_tool import fix_llm_mistakes_on_json, _extract_first_balanced_json

content = open('tests/mistakes/response/json-with-trailing-thinking-close-tag.txt').read()
print(_extract_first_balanced_json(content))
print(fix_llm_mistakes_on_json(content))
```

Both functions return the clean JSON array shown above.

### Unit tests

The following test files pass:

```text
python tests/run_tests.py tests/unit/test_topsailai_utils_json_tool.py
python tests/run_tests.py tests/unit/test_topsailai_ai_base_llm_control_message.py
python tests/run_tests.py tests/unit/test_topsailai_ai_base_llm_control_llm_mistakes.py
```

Result: all passed.

## Problem Description

The actual observed suffix is the literal string `</thinking>` (the model's `</thinking>` thinking tag close format). Earlier reports used `/think` or `思考 extra` as placeholders, but the real trailing text is `</thinking>`.

### Reproduction examples

```python
from topsailai.ai_base.llm_control.message import format_response

# action JSON with trailing think tag
format_response('{"tool_call":"x","tool_args":{}}</thinking>')
# -> JsonError: Extra data: line 1 column 33 - line 1 column 37

# thought JSON with trailing think tag
format_response('{"step_name":"thought","raw_text":"hello"}</thinking>')
# -> JsonError

# final_answer JSON with trailing think tag
format_response('{"step_name":"final_answer","raw_text":"done"}</thinking>')
# -> JsonError

# list_dict (JSON array) with trailing think tag
format_response('[{"step_name":"thought","raw_text":"hello"}]</thinking>')
# -> JsonError, and the current heuristic corrupts the input
```

## Impact

- The failure is not limited to `action` responses. `thought`, `final_answer`, and any other JSON object type are affected.
- When the JSON is a list (list_dict), the previous `fix_llm_mistakes_on_json()` heuristic in `case1` incorrectly appended an extra `]`, corrupting the input further.
- After three failed parse attempts, `format_response()` fell back to `TOPSAILAI_HOOK_AFTER_LLM_CHAT`, which could produce malformed tool-call arguments and cascading errors such as `read_file_around_line() missing 2 required positional arguments`.

## Root Cause

In `src/topsailai/utils/json_tool.py`, `fix_llm_mistakes_on_json()` did not handle the case where a valid JSON value is followed by trailing non-whitespace text.

```python
# fix_llm_mistakes_on_json (simplified)
if safe_json_load(content):
    return content

# case: startswith '{', endswith '\n}'
...

# case1: Missing closing bracket for array
if content[0] == '[' and content[-1] != ']' and "]\n" not in content:
    return content + "]"
```

For input `[{"step_name":"thought"}]</thinking>`:

- `safe_json_load` failed because of the trailing text.
- `case1` saw `[` at the start and a non-`]` character at the end, so it appended `]`, producing `[{"step_name":"thought"}]</thinking>]`.
- This corrupted string was still invalid JSON, so parsing continued to fail.

## Fix Applied

A "first balanced JSON extraction" step was added near the start of `fix_llm_mistakes_on_json()`, before the existing `case1`/`case2` array heuristics.

### Algorithm

1. If the input starts with `{` or `[`, scan for the first balanced closing bracket.
2. Track string literals and escape sequences so that brackets inside strings are ignored.
3. When the outermost bracket closes, validate the candidate substring with `safe_json_load()`.
4. If valid, return that substring.
5. Only if no valid leading JSON is found does the function fall through to the existing heuristics.

This ensures:

- `{"tool_call":"x"}</thinking>` extracts `{"tool_call":"x"}`.
- `[{"step_name":"thought"}]</thinking>` extracts `[{"step_name":"thought"}]` instead of being corrupted by `case1`.
- Nested strings containing `{}`/`[]`/`"` and escaped quotes are handled correctly.

### Tail text handling

`json_tool.py` is responsible only for extracting the first valid JSON. The caller (`format_response()` in `message.py`) discards the trailing text. The issue originally suggested preserving trailing text as an additional `thought` step for `thought`/`final_answer` responses; this has not been implemented and is not required for the core fix.

## Test Coverage

The following scenarios are covered by unit tests:

### `test_topsailai_utils_json_tool.py`

- `fix_llm_mistakes_on_json` extracts the first valid JSON object followed by `</thinking>`.
- `fix_llm_mistakes_on_json` extracts the first valid JSON array (list_dict) followed by `</thinking>` without appending an extra `]`.
- Nested strings containing `{}`, `[]`, and `"` do not confuse the extractor.
- Escaped quotes inside strings do not confuse the extractor.
- Empty object `{}` and empty array `[]` with trailing text are handled.
- Normal JSON without trailing text still passes through unchanged.
- Normal whitespace/newline suffixes still parse correctly without triggering extraction.

### `test_topsailai_ai_base_llm_control_message.py`

- `format_response` parses `action` JSON with `</thinking>` and produces an `action` step.
- `format_response` parses `thought` JSON with `</thinking>` and produces a `thought` step.
- `format_response` parses `final_answer` JSON with `</thinking>` and produces a `final_answer` step.
- `format_response` parses a list_dict with `</thinking>` and produces the expected steps.
- Existing `format_response` behavior for valid JSON, XML function calls, and TopsailAI format remains unchanged.

## Related Files

- `src/topsailai/ai_base/llm_control/message.py`
- `src/topsailai/utils/json_tool.py`
- `src/topsailai/tests/unit/test_topsailai_ai_base_llm_control_message.py`
- `src/topsailai/tests/unit/test_topsailai_utils_json_tool.py`
- `src/topsailai/tests/mistakes/response/json-with-trailing-thinking-close-tag.txt`
