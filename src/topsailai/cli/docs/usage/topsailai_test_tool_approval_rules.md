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

Parses `tool_approval.json` from `TOPSAILAI_HOME` and reports whether each rule is syntactically valid and which tools would be allowed or denied. Use this script to preview the effect of approval rules before an agent run.

## Invocation

```bash
./topsailai_test_tool_approval_rules.py
./topsailai_test_tool_approval_rules.py --home <path>
```

Because the script is registered in `../bin/` as `topsailai_test_tool_approval_rules`, you can also run it as:

```bash
topsailai_test_tool_approval_rules
topsailai_test_tool_approval_rules --home /path/to/home
```

## Options

| Option | Description |
|--------|-------------|
| `--home <path>` | Override `TOPSAILAI_HOME` directory. |
| `--file <path>` | Path to a specific `tool_approval.json` file. |
| `--tool <name>` | Test whether a specific tool name would be approved. |
| `--json` | Output the parsed rules as JSON. |

## Examples

```bash
# Validate the default tool approval file
topsailai_test_tool_approval_rules

# Test a specific tool
topsailai_test_tool_approval_rules --tool cmd_tool-exec_cmd

# Validate a custom file
topsailai_test_tool_approval_rules --file /path/to/tool_approval.json

# JSON output
topsailai_test_tool_approval_rules --json
```

## Notes

- The script does not modify `tool_approval.json`.
- Rules are evaluated in the order they appear in the file.
