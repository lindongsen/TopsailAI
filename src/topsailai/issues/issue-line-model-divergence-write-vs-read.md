---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: fixed
---

# Issue: Write Path and Read Path Disagree on What a Line Is

## Symptom

The file tools disagree about line boundaries for eight characters. A line number
obtained from the read tool can therefore select a different line than the one the
model intended, and the write silently corrupts the file.

Reproduction with a file whose bytes are `a\x0cb\nc\n` (form feed inside line 1):

```
read_file_lines shows:
1-a\x0cb
2-c

Model asks: replace line 2 with "REPLACED"
EXPECTED: b'a\x0cb\nREPLACED\n'
ACTUAL  : b'a\x0cREPLACED\nc\n'
```

The model asked to replace line 2 (`c`) and line 1 was modified instead. The file
still parses and no error is raised.

## Root Cause

Two different line models are in use:

- Write path: `tools/file_tool_utils/file_write_code_block.py:197,204` and
  `tools/file_tool_utils/file_write_line.py:66` call `str.splitlines(keepends=True)`,
  which treats eleven characters as line boundaries.
- Read path: `tools/file_tool_utils/file_read_line.py:35` wraps the file in
  `io.TextIOWrapper`, whose universal-newline mode recognises only `\n`, `\r`, and
  `\r\n`.

The line numbers shown to the model come from the read path, so the read path is the
authority. The write path counts more lines than the model was shown.

## Affected Characters

Fixture `f"a{ch}b\nc\n"`; `splitlines` count versus read-path count:

| Character | `splitlines` | read path | Agree |
|---|---|---|---|
| LF `\n` | 3 | 3 | yes |
| CR `\r` | 3 | 3 | yes |
| CRLF | 3 | 3 | yes |
| VT `\x0b` | 3 | 2 | no |
| FF `\x0c` | 3 | 2 | no |
| FS `\x1c` | 3 | 2 | no |
| GS `\x1d` | 3 | 2 | no |
| RS `\x1e` | 3 | 2 | no |
| NEL `\x85` | 3 | 2 | no |
| LS `\u2028` | 3 | 2 | no |
| PS `\u2029` | 3 | 2 | no |

## Second Symptom: Wrong Reported Range

The `## Changed Range` section added in `c336185f` renders the range from the same
`splitlines` result, so it reports a line count the file does not have when the
replacement content contains one of those characters:

```
initial = "a\nb\nc\n", start=2, end=2, content="X\fY\n"
reported: ## Changed Range (current content, lines 2-3)
          2-X\x0c
          3-Y
final bytes: b'a\nX\x0cY\nc\n'      <- one line, not two
```

This part is new; the wrong-line edit is not.

## Third Symptom: Editing One Line Rewrites Every Line Ending

`file_write_code_block.py:189` reads with `open(file_path, 'r', encoding='utf-8')`,
whose default `newline=None` translates `\r\n` and `\r` to `\n` before the tool ever
sees the text. Writing the result back therefore converts the whole file to LF, not
just the replaced range.

```
before: b'a\r\nb\r\nc\r\n'
edit  : replace line 2 with "B\n"
after : b'a\nB\nc\n'          <- every CRLF destroyed
```

CR-only files and mixed-ending files are flattened the same way. Measured:

| Initial bytes | After editing line 2 |
|---|---|
| `b'a\r\nb\r\nc\r\n'` | `b'a\nB\nc\n'` |
| `b'a\rb\rc\r'` | `b'a\nB\nc\n'` |
| `b'a\r\nb\nc\r\n'` | `b'a\nB\nc\n'` |

### Why the Existing Test Suite Does Not Catch It

`test_content_with_carriage_return_newline` asserts the file content after
`test_file.read_text()`, which itself translates `\r\n` to `\n`. The assertion
therefore passes whether or not the tool preserved the endings, so the test appears
to cover CRLF while observing a translated string. Any test for line endings must
read with `newline=""` and compare raw bytes.

## Attribution

Both the wrong-line edit and the line-ending flattening are pre-existing, not
regressions from `c336185f`. A pristine worktree at `aa2cf117` reproduced each one
identically, with the probe printing `PROBE_FILE` inside the pristine tree and
`PROBE_HAS_HELPER: False`.

## Candidate Fix

`io.StringIO(text, newline="")` reproduces the read path's line model exactly and
preserves line endings byte for byte. Measured on all eleven characters: it agrees
with the read path on every one, while `newline=None` translates `\r\n` and `\r` to
`\n` and must not be used.

The write path and the range rendering must be changed together. Fixing only the
rendering makes the display disagree with the write, which is worse than the current
state because the reported range would then be wrong in the opposite direction.

For the line-ending loss, the read must use `newline=""` so the endings reach the
tool intact, and the write must use `newline=""` as well so they are not translated
on the way out.

## Scope

`file_write_line.py` shares the same `splitlines` line model and therefore the same
wrong-line defect. It is not covered by the three-section output change.

## Impact

Any file containing one of the eight characters is edited on the wrong line. Form
feed is the realistic case: it appears in legacy source, in some generated files, and
in output captured from paginated tools.

Any file with CRLF or CR line endings is silently converted to LF by a single-line
edit, which turns a one-line change into a whole-file diff.

## Decision Needed

Fixing the write path changes the behaviour of an existing tool, which is outside the
scope of the output-format task that discovered it. It needs an explicit decision
rather than a silent fix.

## Resolution

The human authorized fixing all four defects together with unit and BDD coverage.

A new module `tools/file_tool_utils/file_line_model.py` is now the single definition
of the line model, used by both write tools:

- `split_lines(text)` — `io.StringIO(text, newline="").readlines()`, which agrees with
  the read path on all eleven characters and preserves endings byte for byte.
- `read_text(file_path)` / `write_text(file_path, text)` — UTF-8 with `newline=""`, so
  endings are neither translated on read nor on write.
- `line_ending_of(line)` — returns `\r\n`, `\n`, `\r`, or `''`.

A fourth defect was found while fixing the third: `file_write_line.py` stripped only
`\n` from the last line, so content ending with `\r\n` left a stray `\r`
(`b'a\nB\r'`). It now removes the whole ending via `line_ending_of`.

A fifth defect was found in the same expression: `line[len(line.rstrip()):]` looks
like it extracts the ending but also strips spaces and tabs, so the "ending" of
`"b  \n"` was `"  \n"` and the next line's trailing whitespace was injected into the
edited line. `line_ending_of` replaces it.

### Verified behaviour

| Case | Before | After |
|---|---|---|
| `a\x0cb\nc\n`, replace line 2 | `a\x0cREPLACED\nc\n` | `a\x0cb\nREPLACED\n` |
| `a\r\nb\r\nc\r\n`, replace line 2 | `a\nB\nc\n` | `a\r\nB\nc\r\n` |
| `a\rb\rc\r`, replace line 2 | `a\nB\nc\n` | `a\rB\nc\r` |
| `a\nb  \nc\n`, replace line 1 with `X` | `X  \nb  \nc\n` | `X\nb  \nc\n` |
| `a\nb`, replace line 2 with `B\r\n` | `a\nB\r` | `a\nB` |

### Coverage

- `tests/unit/test_topsailai_tools_file_tool_utils_file_line_model.py` — 45 tests,
  including negative controls proving `str.splitlines` disagrees and that a
  default-`open()` read translates endings.
- `file_write_code_block` — 131 tests; `file_write_line` — 55 tests.
- The two `xfail(strict=True)` markers were removed because the defects are fixed.
- Nine BDD scenarios in `tests/bdd/features/tools_param_coercion_cmd_git_file.feature`
  drive the real tools through the harness and read the file with `newline=""`.
- Pristine control at `aa2cf117`: all nine new scenarios fail there, so they observe
  the fix rather than passing vacuously.

## Remaining Scope

`tools/file_tool.py::_insert_data_to_file` (the `insert_content_to_file` tool) still
opens the file with `open(file_path, 'r')` and `open(file_path, 'w')` without
`encoding` or `newline`, so it has the same line-ending flattening defect. It was not
changed because it is outside the authorized scope of this fix; it should be migrated
to `file_line_model` in a follow-up.

`file_diff.py` reads with the default `newline` at four sites. Both diff sides are
translated identically, so the diff itself stays correct, but this was not verified
explicitly.
