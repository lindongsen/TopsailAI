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

Uses the project's tokenizer to count tokens in raw text, a single file, multiple files, or standard input. Relative paths are resolved against the original `TOPSAILAI_PWD` so the command works correctly when invoked through the dispatcher script.

## Input Sources

The text to count comes from exactly one of these sources:

- `--text <text>`: the literal text passed on the command line.
- `--file <path>`: the content of a single file.
- `files`: one or more positional file paths.
- Standard input: used when `--text -` or `--file -` is passed, or when neither `--text`, `--file`, nor any positional file is given.

When stdin is read implicitly (no input argument at all) and stdin is an interactive terminal, the command prints a usage error and exits with code 2 instead of blocking and waiting for input.

## Invocation

```bash
./topsailai_count_tokens.py --text "hello world"
./topsailai_count_tokens.py --file path/to/file.txt
./topsailai_count_tokens.py file1.txt file2.txt
./topsailai_count_tokens.py -
./topsailai_count_tokens.py --text -
```

Because the script is registered in `../bin/` as `topsailai_count_tokens`, you can also run it as:

```bash
topsailai_count_tokens --text "hello world"
topsailai_count_tokens file1.txt file2.txt
cat README.md | topsailai_count_tokens -
cat README.md | topsailai_count_tokens
```

## Options

| Option | Description |
|--------|-------------|
| `--text <text>` | Raw text to count tokens for. Use `-` to read the text from stdin. Mutually exclusive with `--file` and positional file arguments. |
| `--file <path>` | Path to a single file to count. Use `-` to read from stdin. Mutually exclusive with `--text` and positional file arguments. |
| `--encoding <name>` | Tiktoken encoding name (default: `cl100k_base`). |
| `files` | Positional arguments: one or more file paths to count. Use `-` to read from stdin. |

## Output

- For `--text`, `--file` (including `-`), or no input argument, prints a single integer token count.
- For multiple positional files, prints one line per file: `<count> <path>`. When `-` is used as a path, it is printed as `-`.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success. |
| 1 | One or more files not found. |
| 2 | Invalid argument combination (e.g. `--text` with positional files), or no input argument while stdin is an interactive terminal. |

## Examples

```bash
# Count tokens in raw text
topsailai_count_tokens --text "hello world"

# Count tokens in a single file
topsailai_count_tokens --file README.md

# Count tokens in multiple files
topsailai_count_tokens README.md docs/*.md

# Count tokens from stdin (implicit, no input argument)
cat README.md | topsailai_count_tokens

# Count tokens from stdin (explicit)
cat README.md | topsailai_count_tokens -

# Count tokens from stdin through --text or --file
cat README.md | topsailai_count_tokens --text -
cat README.md | topsailai_count_tokens --file -

# Use a different encoding
topsailai_count_tokens --encoding o200k_base --file README.md
```
