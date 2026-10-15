---
maintainer: AI
author: DawsonLin
---
# Human tool registration gate test gap

Status: resolved; registration coverage added without changing the Human-approved source logic.

The Human restored callback-first input resolution and changed FLAG_TOOL_ENABLED to env_tool.is_interactive_mode(). At review time, test_flag_tool_enabled_is_true unconditionally asserted True and did not cover disabled-mode module import or loader registration. The then-current suite passed 64 tests without verifying the new behavior.

Review recommendation: isolated import with mode unset, 1 and 0; default loader exclusion when disabled; preserve timeout/plain callback priority. Explicit enabled-tool overrides and post-import environment changes must be documented as existing loader semantics, not silently changed.

Boundary: tools/base/init.py checks explicit enabled-tool wildcard/name/prefix before FLAG_TOOL_ENABLED. Direct ask_decision calls with runtime callbacks remain usable when mode is 0 by the Human-approved original priority.

## Resolution

Human decision: "Accept as-is (explicit enable may override) and add registration-layer tests to close the gap". Six isolated subprocess cases now verify the real module flag, loader predicate and final TOOLS membership for unset/1/0 modes and disabled-mode explicit name/prefix/wildcard overrides. A regression also preserves callback-first input priority. No input-resolution source logic was modified.

Verification: project-venv focused pytest command with --color=no -q --tb=line --disable-warnings and task-scoped cache/basetemp: 70 passed in 2.75s (3.18s elapsed). No full-suite or coverage run.
