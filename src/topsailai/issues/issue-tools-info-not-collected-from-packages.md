---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# TOOLS_INFO Declared Inside A Tool Package Is Silently Never Registered

## Symptom

`tools/file_tool_utils/file_read_line.py` now declares a `TOOLS_INFO` for
`read_file_with_context`, but the runtime registry only sees it because
`tools/file_tool.py` explicitly merges it:

```python
# tools/file_tool.py:516-517
TOOLS_INFO = dict(file_read_line.TOOLS_INFO)
```

Without that merge line, the schema is silently dropped and the tool falls back
to the bare `{"parameters": {"type": "object"}}` schema produced by
`tools/base/common.py:108`, which is exactly the condition that makes providers
stringify every argument.

## Root Cause

`tools/base/init.py:114` collects tool metadata through
`module_tool.get_function_map("topsailai.tools", "TOOLS_INFO")`. That helper
iterates modules only; a package is not treated as a module container for this
purpose, so any `TOOLS_INFO` defined in a file that lives inside a package
directory under `topsailai.tools` is invisible to registration.

`TOOLS` itself survives only because the parent module re-exports it, e.g.
`tools/file_tool.py:513-514` calls `TOOLS.update(file_read_line.TOOLS)` and
`TOOLS.update(file_stat.TOOLS)`.

## Affected Files

Any tool module inside a package under `tools/`:

- `tools/file_tool_utils/file_read_line.py` (worked around by this change)
- `tools/file_tool_utils/file_stat.py`
- `tools/file_tool_utils/file_write_code_block.py`
- `tools/file_tool_utils/file_diff.py`
- `tools/file_tool_utils/file_write_line.py`
- `tools/memory_tool_utils/*` (currently exposes no LLM tools)

## Impact

A maintainer who follows the new rule in `tools/readme.md` ("tools with non-str
parameters MUST declare `TOOLS_INFO`") and adds the schema inside a package file
gets **no error, no warning and no schema**. The tool keeps stringifying
arguments and the silent type-inversion class of bug survives the fix attempt.
This makes the documented rule unreliable for a whole subtree.

## Suggested Fix

Either:

1. Make collection recursive, i.e. have `tools/base/init.py` walk subpackages
   for `TOOLS_INFO` the same way it resolves `TOOLS`; or
2. Fail loudly: at registration time, warn for every callable in `TOOLS` whose
   defining module declares a `TOOLS_INFO` entry that was not collected.

Option 2 is cheaper and converts a silent trap into an actionable log line.
Option 1 is the correct long-term behavior and should be evaluated together with
the framework-level parameter-coercion layer.

## Related

- `tools/readme.md` section "Tool Parameter Types Must Assume String-Typed
  LLM Output"
- Pending decision: framework-level parameter coercion layer at
  `ai_base/agent_types/tool.py:264-270`
- `tools/readme.md:16` still states `TOOLS_INFO: optional ... Do not set it
  unless necessary!`, which contradicts the root cause above.
