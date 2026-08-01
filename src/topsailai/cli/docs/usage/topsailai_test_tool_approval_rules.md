---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_test_tool_approval_rules

Validate tool approval rule configuration.

## Purpose

Loads the tool approval rule set and reports whether each rule is syntactically valid and which tools would be allowed or denied. Use this script to preview the effect of approval rules before an agent run.

The script uses the same rule loader as the agent, so it supports:

- A single JSON file path.
- Multiple JSON file paths separated by `;`.
- An inline JSON array literal.
- The `TOPSAILAI_TOOL_APPROVAL_RULES` environment variable.
- The default fallback path `${TOPSAILAI_WORK_FOLDER}/tool_approval.json`.

## Invocation

```bash
./topsailai_test_tool_approval_rules.py
./topsailai_test_tool_approval_rules.py --rules /path/to/tool_approval.json
```

Because the script is registered in `../bin/` as `topsailai_test_tool_approval_rules`, you can also run it as:

```bash
topsailai_test_tool_approval_rules
topsailai_test_tool_approval_rules --rules /path/to/tool_approval.json
```

## Options

| Option | Description |
|--------|-------------|
| `--rules <value>` | Path to a `tool_approval.json` file, multiple paths separated by `;`, or an inline JSON array. If omitted, reads from `TOPSAILAI_TOOL_APPROVAL_RULES`. |
| `--tool <name>` | Default tool name for positional arguments (default: `cmd_tool-exec_cmd`). |
| `--json` | Output evaluation results as JSON. |
| `calls` | Positional tool calls to evaluate. Supports an optional `tool_name:value` prefix. |

## Examples

```bash
# Validate the default tool approval file
topsailai_test_tool_approval_rules

# Test a specific tool call
topsailai_test_tool_approval_rules --tool cmd_tool-exec_cmd "rm -rf /"

# Validate a custom file
topsailai_test_tool_approval_rules --rules /path/to/tool_approval.json

# Validate multiple rule files
topsailai_test_tool_approval_rules --rules "/path/to/a.json;/path/to/b.json"

# Validate an inline rule set
topsailai_test_tool_approval_rules --rules '[{"match":"cmd_*","mode":"require"}]'

# JSON output
topsailai_test_tool_approval_rules --json "rm -rf /" "echo hello"
```

## Notes

- The script does not modify any rule file.
- Rules are sorted by `priority` (ascending) before evaluation; the first matching rule wins.
- When loading fails, critical-level log messages are emitted by the shared rule loader.
