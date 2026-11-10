---
maintainer: AI
author: DawsonLin
---
# The bin wrapper drops empty arguments, so an empty filter value cannot be passed

## Status
Resolved. The human authorized the cross-workspace change with
"授权，但是应该都用这个的做法：../bin/topsailai.cli", so all five real wrappers
now quote every argument the same way `../bin/topsailai.cli` does.

## Symptom
Passing an exactly empty value to a filter option failed when the command was
invoked through its `bin/` wrapper:

```bash
../bin/ai_list_sessions --json --category ""
# ai_list_sessions.py: error: argument --category: expected one argument
# exit code 2
```

The same command invoked directly succeeded:

```bash
./ai_list_sessions.py --json --category ""
# exit code 0, uncategorized sessions listed
```

## Root cause
Each wrapper ended with:

```bash
DEBUG=${DEBUG} run_cli ai_list_sessions $*
```

The unquoted `$*` word-splits the argument list, so an empty string is removed
before `run_cli` sees it. The child then receives `--category` with no value and
argparse rejects it.

## Scope
A wrapper defect, not a script defect. It affected every option that assigns a
meaning to the empty string, and it predates the `--excluded-categories` option.

Twelve command names were affected, but only five real files carried the defect;
the other seven are symlinks to them:

| Real file | Symlinks pointing at it |
|---|---|
| `ai_list_sessions` | `topsailai_list_sessions`, `topsailai_session_list` |
| `ai_delete_session` | `topsailai_delete_session`, `topsailai_session_delete` |
| `ai_clean_messages` | `topsailai_clean_messages` |
| `ai_clean_sessions` | `topsailai_clean_sessions` |
| `ai_retrieve_messages` | `topsailai_retrieve_messages` |

## Two further defects found in the same line
The unquoted `$*` did more than drop empty strings:

- **Glob expansion.** A value containing `*` was expanded against the current
  directory. A probe measured one argument becoming 63 filenames, so
  `--category "agent*"` produced an argparse usage error instead of the intended
  invalid-value error.
- **Silent wrong results for spaced values.** `--category "agent x"` was split
  into two arguments, so the wrapper exited `0` with `Matched Total: 0` while the
  direct script correctly exited `2` with `invalid category 'agent x'`. The
  wrapper turned a should-be-error into an empty result.

## Fix applied
Each of the five real wrappers now quotes every argument exactly as
`../bin/topsailai.cli` does:

```bash
get_args_id() {
  for i in $(seq $1 $2); do
    echo -n " \"\${${i}}\""
  done
}

DEBUG=${DEBUG} eval "run_cli ai_list_sessions $(get_args_id 1 $#)"
```

## Verification
- `bash -n` passes on all five files; `grep -rn 'run_cli .* \$\*'` finds none.
- `git diff --stat` reports 5 files, `+35/-5`, one hunk per file.
- `--category ""` now exits `0` and lists 40 uncategorized sessions, both directly
  and through `topsailai_list_sessions` and `topsailai_session_list`.
- `--category "agent x"`, `--category "agent*"`, `--category $'agent\nx'`,
  `--category "agent,agent_driver"`, `--category Agent`, and a repeated
  `--category` all exit `2` with the intended message.
- Normal multi-argument calls are unchanged: `--category agent --limit 2` returns
  2 rows with `Matched Total: 100`, and `--json --limit 1` still emits JSON.
- The other four wrappers keep their behaviour: `ai_clean_messages 999999` and
  `ai_clean_sessions 999999` exit `0`, `ai_delete_session <unknown>` exits `1`,
  `ai_retrieve_messages` with no argument exits `2`.
- `tests/unit/ai_list_sessions` plus `tests/unit/topsailai`: 3273 passed.
- The untouched `topsailai.cli` dispatcher still resolves `topsailai_session_info`.

## Behaviour change to be aware of
One form stops working: a single argument that contains a space and an option
name, such as `ai_list_sessions "--category agent"`. It previously worked only
because `$*` split it; it is now one token, so argparse treats it as a positional
session filter and returns `No sessions found.` with exit `0`. No caller in the
repository uses that form, and Python callers pass argument lists directly
without going through the shell.

## Note on `eval`
`get_args_id` emits `"${1}"`, so each value is expanded inside quotes during
`eval` and is never re-parsed as shell syntax. Eighteen hostile values were
tested against both this implementation and a plain `"$@"` — empty string, space,
double quote, single backslash, trailing backslash, `$HOME`, `${HOME}`, `$(id)`,
backtick, `*`, newline, semicolon, zero arguments, and a lone `-` — and both
produced identical argument vectors. `DEBUG` propagation was also identical.
