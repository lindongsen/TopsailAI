---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_count_tokens

Count tokens for text or file content.

## Purpose

Uses the project's tokenizer to count tokens in raw text, a single file, or multiple files. Relative paths are resolved against the original `TOPSAILAI_PWD` so the command works correctly when invoked through the dispatcher script.

## Invocation

```bash
./topsailai_count_tokens.py --text "hello world"
./topsailai_count_tokens.py --file path/to/file.txt
./topsailai_count_tokens.py file1.txt file2.txt
```

Because the script is registered in `../bin/` as `topsailai_count_tokens`, you can also run it as:

```bash
topsailai_count_tokens --text "hello world"
topsailai_count_tokens file1.txt file2.txt
```

## Options

| Option | Description |
|--------|-------------|
| `--text <text>` | Raw text to count tokens for. Mutually exclusive with `--file` and positional file arguments. |
| `--file <path>` | Path to a single file to count. Mutually exclusive with `--text` and positional file arguments. |
| `--encoding <name>` | Tiktoken encoding name (default: `cl100k_base`). |
| `files` | Positional arguments: one or more file paths to count. |

## Output

- For `--text` or `--file`, prints a single integer token count.
- For multiple positional files, prints one line per file: `<count> <path>`.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success. |
| 1 | One or more files not found. |
| 2 | Invalid argument combination (e.g. `--text` with positional files). |

## Examples

```bash
# Count tokens in raw text
topsailai_count_tokens --text "hello world"

# Count tokens in a single file
topsailai_count_tokens --file README.md

# Count tokens in multiple files
topsailai_count_tokens README.md docs/*.md

# Use a different encoding
topsailai_count_tokens --encoding o200k_base --file README.md
```
