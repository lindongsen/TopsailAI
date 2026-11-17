---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
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

## Resolution

Status: resolved. Commit `e4a57360`.

### Two claims in this issue were wrong

**The stated symptom never existed.** `git log -S "TOOLS_INFO" -- tools/file_tool_utils/file_read_line.py` returns nothing, so `file_read_line.py` has never declared `TOOLS_INFO` in any commit. The merge line quoted at `tools/file_tool.py:516-517` is commented out at line 548 and `file_read_line.py` declares only `TOOLS` at line 399. The issue described a hypothetical, not an observed state.

**Suggested fix 1 (recursive collection) cannot work.** `get_function_map` prefixes each key with the *module* name, while the `TOOLS` registry prefixes with the *registration* module. Measured:

```
registry key          : file_tool-read_file_with_context
recursive collection  : file_read_line-read_file_with_context
```

`get_tools_for_chat()` looks up `TOOLS_INFO` by the registry key, so recursive collection would register schemas under keys it never queries. A probe on a synthetic package confirmed the filter and the prefixing:

```
list_sub_mods_name('probe_tools')            -> ['top_mod']          # 'inner' package invisible
get_function_map('probe_tools', 'TOOLS')     -> ['top_mod.top_func']
get_function_map('probe_tools.inner','TOOLS_INFO') -> ['deep_mod.deep_func']
```

### The real defect

`utils/module_tool.py:88` filters `ispkg=True`, so `file_tool_utils`, `memory_tool_utils`, `jev_tool_utils`, `agent_tool_utils` and `tool_utils` are invisible to `TOOLS_INFO` collection. Measured production state before the fix:

```
TOOLS count: 24
TOOLS_INFO keys: ['cmd_tool-exec_cmd']
tools without schema: 23
```

Defining modules of those 23: `file_tool` (8), `file_read_line` (3), `file_stat` (1), `file_write_code_block` (1), `human_tool` (1), `self_tool` (1), `skill_tool` (4), `story_memory_tool` (4). None of them declares `TOOLS_INFO` today, so the gap is latent rather than active: it is a trap for the next maintainer who follows `tools/readme.md`.

### Fix

`tools/base/init.py` gains `_collect_package_tools_info()`, called once at module level after the existing collection. It resolves each registered tool's defining module via `__module__`, reads that module's `TOOLS_INFO`, and adopts the schema under the **already-registered** key. Key space is preserved; no `file_read_line-*` key is introduced.

The bare registry key is tried before `__name__` because a registered key can be an alias: `file_tool-overwrite_lines_in_file` maps to the function `overwrite_code_block`, and the schema is declared under the registered name.

Existing entries are never overwritten, so module-level collection keeps precedence. An unresolvable module is logged at `warning` and skipped rather than raising.

### Verification

```
tests/unit/test_topsailai_tools_base.py                 45 passed
tools_base + jev_tool + utils_file_tool + plugin_instruction  243 passed
```

Probe after the fix, with a package module declaring a schema:

```
file_tool-read_file_with_context present: True
spec: {'type': 'object', 'properties': {'x': {'type': 'string'}}}
file_read_line-* keys leaked: []
cmd_tool-exec_cmd still present: True
alias case file_tool-overwrite_lines_in_file adopted: True
```

### Negative control

Removing only the module-level call left the first 44 tests green, because they exercise the helper directly. That exposed a real gap in the test set, so `test_module_level_wiring_adopts_package_schema` was added: it re-imports the registry module in a subprocess with a package schema pre-declared and asserts the key is present. With the call removed it fails with `MISSING`; with the call restored it passes.

### Documentation

`tools/readme.md:17` said "Currently no tool module sets it", which was false (`cmd_tool.py:181` does) and contradicted line 68. It now states that only `cmd_tool.py` sets it today and that a schema declared inside a package under `tools/` is adopted automatically under the registered tool key.

### Not done

The issue's option 2 (registration-time warning for uncollected schemas) was not implemented. Adoption makes the warning unnecessary for the bundled subtree, and the plugin path already collects both `TOOLS` and `TOOLS_INFO` through `get_external_function_map`. A warning would only fire for a module that declares a schema for a tool it does not register, which is a different defect.
