---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# Response Parsing Mistakes

This directory collects real response parsing bugs and edge cases observed when handling LLM outputs.

## File Layout

For each mistake, create two files with the same base name:

- `{case-name}.md` — Human-readable description of the mistake.
- `{case-name}.txt` — Raw LLM response content that reproduces the mistake.

Example:

```text
parsing-action-vs-final-answer.md
parsing-action-vs-final-answer.txt
```

The `.txt` file should contain the exact raw response text so it can be fed directly into `topsailai_format_response` for reproduction and regression testing.

## How to Test a Case

Use the `topsailai_format_response` CLI from the CLI workspace:

```bash
cd /TopsailAI/src/topsailai
./bin/topsailai_format_response tests/mistakes/response/parsing-action-vs-final-answer.txt
```

Or read from stdin:

```bash
./bin/topsailai_format_response - < tests/mistakes/response/parsing-action-vs-final-answer.txt
```

## Adding a New Case

1. Copy an existing `.md` file as a template.
2. Fill in symptom, example input, expected behavior, actual behavior, root cause, and fix direction.
3. Create a matching `.txt` file with the raw response content.
4. Verify the case reproduces with `topsailai_format_response`.
5. Update this README's case list if necessary.

## Current Cases

- `parsing-action-vs-final-answer` — `action` and `final_answer` appearing in the same response should prioritize `action`.
