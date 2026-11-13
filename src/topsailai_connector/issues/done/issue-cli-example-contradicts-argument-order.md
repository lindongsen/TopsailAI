---
maintainer: AI
author: DawsonLin
status: done
severity: low
created: 2026-11-13
platform: all
---

# The CLI example in `docs/API.md` contradicts the documented argument order

## Symptom

`docs/API.md` stated the rule correctly in prose:

> Flags must precede the operation name, because Go's flag parser stops at the
> first non-flag argument.

The example immediately above it did the opposite, and also used a path the
grammar refuses:

```
connector-server cli file.list --server https://cloud.example:8443 \
    --client-token <client_token> --node node_7f3a.kQ2v... --scope project --path .
```

Copying that example fails:

```
connector-server cli: usage: got 4 positional arguments, want 1
```

## Impact

An operator following the document cannot make a first request. The failure
message names positional arguments rather than the real cause, so the natural
next step is to re-read the flags table, which is correct, and conclude the
binary is broken.

The `--path .` value is a second defect in the same example: the path grammar
rejects a `.` component rather than normalising it, so even with the flags in the
right order the request returns `invalid_argument`.

## Root cause

`parseArguments` in `internal/server/cli/command.go` calls `flags.Parse` and then
`parseOperation(flags.Args())`. Go's `flag` package stops at the first non-flag
argument, so every flag written after the operation name becomes a positional
argument. The prose was written from the implementation; the example was written
from the natural reading order and never executed.

## Detection failure

No test executes the examples in `docs/API.md`. The CLI unit tests call
`parseArguments` with a correctly ordered slice, so they assert the parser and
never the document.

## Fix

The example now puts every flag before the operation name and uses a real file
path:

```
connector-server cli --server https://cloud.example:8443 \
    --client-token <client_token> --node node_7f3a.kQ2v... --scope project \
    --path notes.md file.read
```

## Verified on

Linux build host and Windows Server 2022 (10.0.20348.587). The corrected form
returned `hello from windows` for `file.read` and a directory listing for
`file.list` on the Windows host.
