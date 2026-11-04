---
maintainer: AI
author: DawsonLin
---
# Optional plugin workspace

This directory is maintained independently from core business code. Neither the workspace nor `tools/` requires an `__init__.py`. Core code must not directly import this workspace; the plugin loader imports tool modules only after explicit configuration. The tool implementations currently depend on TopsailAI core helpers; this is not a standalone distribution.

## Loading tools

Set `TOPSAILAI_PLUGIN_TOOLS` to the absolute path of this workspace's `tools/` directory. The existing loader scans direct child modules exporting `TOOLS` and optional `TOOLS_INFO`; it does not recursively search for tool directories. Configure before process startup. Leave the variable empty to omit these plugins.

Both bundled modules default to disabled. Set `TOPSAILAI_ENABLED_TOOLS` to `agent_tool;bigfile_tool` to enable them explicitly, or `*` to enable all tools. Existing disabled-tool rules still apply. Do not use `topsailai.plugins.tools` as a core-package dependency. Directory configuration still uses Python's import machinery internally, so avoid mixing unrelated same-named plugin packages in one process.

## Tests

Run `make test` from this workspace, or `make plugins-test` from the core workspace. Separate targets are `test-unit` and `test-bdd`. The core aggregate unit and BDD targets also invoke these suites. Test artifacts go under the core workspace's `.tmp/plugins-workspace/` directory; no model service is contacted.

Plugin export, discovery and file-reading tests live in `tests/`. Core helper tests remain in the core test tree. The plugin Makefile puts `tools/` on the test import path so tests import individual tool modules without importing the workspace as a package.
