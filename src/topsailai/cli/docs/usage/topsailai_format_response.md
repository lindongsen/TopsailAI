---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# `topsailai_format_response`

Parse LLM responses into structured steps.

## Overview

`topsailai_format_response` reads raw LLM output and extracts the embedded `topsailai.*` steps (such as `topsailai.thought`, `topsailai.action`, and `topsailai.final_answer`). It is useful for inspecting, debugging, or testing response parsing without running a full agent session.

The parser is imported from `../src/topsailai/ai_base/llm_control/message.py` and uses the same `format_response` function that the agent runtime uses, so the CLI output matches production behavior.

## Usage

### Parse text from a command-line argument

```bash
./bin/topsailai_format_response --text 'topsailai.thought
hello world'
```

### Parse text from a file

```bash
./bin/topsailai_format_response --file response.txt
./bin/topsailai_format_response response.txt
```

### Parse text from stdin

```bash
cat response.txt | ./bin/topsailai_format_response -
```

### Output compact JSON

```bash
./bin/topsailai_format_response --compact --file response.txt
```

### Control JSON indentation

```bash
./bin/topsailai_format_response --indent 4 --file response.txt
```

## Options

| Option | Description |
|---|---|
| `--text TEXT` | Provide the response text directly as an argument. |
| `--file PATH` | Read the response text from a file. |
| `PATH` | Positional file path. Use `-` to read from stdin. |
| `--indent N` | JSON indentation level. Default is `2`. |
| `--compact` | Output compact JSON without indentation. |
| `-h`, `--help` | Show help message and exit. |

## Output Format

The command prints a JSON array of parsed steps. Each step contains at least `step_name` and `raw_text`. Additional fields may be present depending on the step type.

Example:

```json
[
  {
    "step_name": "thought",
    "raw_text": "I need to check the current directory."
  },
  {
    "step_name": "action",
    "tool_call": "cmd_tool-exec_cmd",
    "tool_args": {
      "cmd": "pwd"
    }
  }
]
```

## Error Handling

- If no input is provided, the CLI exits with a non-zero status and prints a usage message.
- If the file cannot be read, the underlying `OSError` is propagated with a clear message.
- If the response text cannot be parsed, the parser returns the best-effort result according to `format_response` rules.

## Known Parsing Issues

Known response parsing bugs and edge cases are collected in the shared mistake repository so they can be referenced and extended as new cases are discovered.

Location: `../src/topsailai/tests/mistakes/response/`

Current entries:

- `parsing-action-vs-final-answer.md` — `action` and `final_answer` appearing in the same response should prioritize `action`.

When you encounter a new parsing mistake, add a new markdown file to that directory with the same structure: symptom, example input, expected behavior, actual behavior, root cause, and fix direction.
