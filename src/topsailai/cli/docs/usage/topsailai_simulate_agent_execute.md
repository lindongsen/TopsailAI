---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# `topsailai_simulate_agent_execute`

Simulate the agent execution phase for a given LLM response.

## Overview

`topsailai_simulate_agent_execute` reads raw LLM output and runs the AGENT EXECUTION PHASE headlessly: it parses the response into steps (`thought`, `action`, `final_answer`), dispatches each `action` through the registered tool set, feeds back observations, and stops when a `final_answer` is reached -- without needing a live LLM. It complements `topsailai_format_response`, which only performs the parsing stage.

Parsing reuses the same `format_response` function the agent runtime uses, and action dispatch goes through the framework's step-call machinery, so simulation matches production behavior.

## Usage

### Simulate text from a command-line argument

```bash
./bin/topsailai_simulate_agent_execute --text 'topsailai.action
{"tool_call": "time_tool-get_local_time", "tool_args": {}}
'
```

### Simulate text from a file

```bash
./bin/topsailai_simulate_agent_execute --file response.txt
./bin/topsailai_simulate_agent_execute response.txt
```

### Simulate text from stdin

```bash
cat response.txt | ./bin/topsailai_simulate_agent_execute -
```

### Print available tools before executing

```bash
./bin/topsailai_simulate_agent_execute --show-tools --file response.txt
```

### Restrict or exclude tools

```bash
./bin/topsailai_simulate_agent_execute --only-tools time_tool;cmd_tool --file response.txt
./bin/topsailai_simulate_agent_execute --exclude-tools human_tool --file response.txt
```

### Cap the number of processed steps

```bash
./bin/topsailai_simulate_agent_execute --max-steps 10 --file response.txt
```

### Output structured JSON

```bash
./bin/topsailai_simulate_agent_execute --output-format json --file response.txt
./bin/topsailai_simulate_agent_execute --output-format json --compact --file response.txt
```

### Render steps using topsailai tags

```bash
./bin/topsailai_simulate_agent_execute --output-format topsailai --file response.txt
```

### Quiet mode (print only the final answer)

```bash
./bin/topsailai_simulate_agent_execute --quiet --file response.txt
```

## Options

| Option | Description |
|---|---|
| `--text TEXT` | Provide the response text directly as an argument. Mutually exclusive with `--file` and positional files. |
| `--file PATH` | Read the response text from a file. Mutually exclusive with `--text` and positional files. |
| `PATH` | Positional file path. Use `-` to read from stdin. Only one input may be provided. |
| `--max-steps N` | Hard cap on total processed steps across the run. Default is `50`. If exceeded, exits with status `3`. |
| `--interactive` | Allow interactive prompts for inquiry/single-thought steps; otherwise automatic non-interactive observation is used. |
| `--show-tools` | Print the list of available tool names before executing. |
| `--exclude-tools PREFIXES` | Filter out tools whose full name starts with any `;`-separated prefix. |
| `--only-tools PREFIXES` | Restrict the tool map to tools matching any `;`-separated prefix. |
| `--output-format FORMAT` | Output format: `transcript` (default), `json`, or `topsailai`. |
| `--indent N` | Indentation level for JSON output. Default is `2`. |
| `--compact` | Output compact JSON instead of pretty-printed JSON. |
| `--quiet` | Suppress informational chatter and print only the final answer. |
| `-h`, `--help` | Show help message and exit. |

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success -- a final answer was produced. |
| `1` | Runtime error (e.g. unreadable/missing file, no final answer produced). |
| `2` | Argument misuse (no input, conflicting inputs). |
| `3` | Max-steps exceeded without reaching a final answer. |

## Input Format

Input must contain native `topsailai.*` step tags (such as `topsailai.thought`, `topsailai.action`, and `topsailai.final_answer`) or a JSON list-of-steps shape accepted by `format_response`. XML-style tag-step inputs are not supported, consistent with what `format_response` accepts.

An `action` step carries its tool call either inline via the `topsailai.action` payload or through the parsed `tool_call`/`tool_args` fields. Each dispatched action produces an observation that is fed back before processing continues.

## Error Handling

- If no input is provided, the CLI prints a usage message and exits with status `2`.
- If the file cannot be found or read, an error is printed and the CLI exits with status `1`.
- If the response cannot be parsed, the best-effort result according to `format_response` rules is used.
- If the step budget is exhausted before a final answer, the CLI exits with status `3`.
- Inquiry-only responses that produce no final answer cause a non-zero exit under the default non-interactive mode.