---
maintainer: AI
author: DawsonLin
---
# Plugin tool prompts resolve the wrong module

Trigger: assistant tool migration to an explicitly loaded plugin. Prompt lookup and reload hardcoded the core namespace, dropping optional-plugin policy text. Imported helper functions retain their core __module__, so that attribute cannot identify the registration owner.

Repair: capture registration module provenance through an optional discovery output; registry owns the mapping and prompt/observation/reload lookup prefers it. Keep existing env defaults and explicit-only loading unchanged.

Verification: resolved; see .task/check_20261104T140911_agent-tool-to-plugin.md and the closure section below.

## Closure verification (2026-11-17)

Production code confirmed present and committed in `f469655b refactor: move assistant tools to an explicitly loaded plugin`:

- `utils/module_tool.py` accepts an optional `module_sources` output mapping and records each discovered submodule's registration path (lines 99, 114, 161-162, 254, 291).
- `tools/base/init.py` owns `TOOL_MODULES = {}` and passes it as `module_sources=TOOL_MODULES` (lines 83, 88).
- `prompt_hub/prompt_tool.py::_get_tool_module_path()` prefers `TOOL_MODULES` and falls back to `topsailai.tools.{module_name}` (lines 223-227), so prompt, observation and reload all resolve the registration owner instead of an imported function's core `__module__`.

Executed evidence:

- `plugins/tests/test_agent_plugin.py` -> 7 passed.
- `plugins/tests/test_agent_plugin_bdd.py` -> 4 passed in 3.28s. The packaged-root gap recorded in the check document no longer blocks the source explicit-plugin scenarios.

Residual limitation, unchanged from the check document: packaged-artifact BDD remains unverified because the packaged root is absent in this environment. This is unavailable evidence, not a claimed pass.

Out of scope: the full-runner failure `test_prepared_script_plans.py::test_public_points_register_independently_and_execute_all_members` contains no plugin or prompt references and is tracked separately.
