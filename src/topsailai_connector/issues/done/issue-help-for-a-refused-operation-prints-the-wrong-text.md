---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-19
---

# `help file.write` printed the help for `help` itself and exited 0

## Symptom

Asking for help about an operation this version refuses answered with the wrong
text and a success status.

Measured on the built binary:

| Invocation | Output | Exit |
|---|---|---|
| `connector-cli help file.read` | the `file.read` help | `0` |
| `connector-cli help file.write` | the `help` subcommand's own help | **`0`** |
| `connector-cli help command.exec` | the `help` subcommand's own help | **`0`** |

The second and third rows are the defect. The caller asked about an operation, was
shown a page describing the `help` subcommand, and was told it succeeded.

## Cause

`handleInformational` validated the name with `Validate`:

```go
if name != "help" {
    if protocol.Operation(name).Validate() != nil {
        // refuse
    }
}
fmt.Fprint(stdout, operationHelpText(program, name))
```

`Validate` answers "is this a declared operation in the wire vocabulary", and
`file.write` and `command.exec` are declared so that a second-version policy parses.
They are therefore valid names. `operationHelpText` has no case for them, so the
call fell through to its `default:` branch, which is the help for `help`.

The two questions are different and the code asked the wrong one:

| Question | Function | Answer for `file.write` |
|---|---|---|
| Is this a declared operation? | `Validate` | yes |
| Does this version offer it? | `Enabled` | no |

## Fix

Ask `Enabled`, which already expresses "declared but not implemented" and is the
same predicate the dispatcher uses to refuse the operation. Reusing it means the
help text and the dispatch cannot disagree about what this version offers.

The refusal is status `2` with a message naming the three operations that do work,
because the caller asked about something that does not exist in this build.

## Verification

Mutation-tested, because a refusal test that passes with the check removed is
measuring nothing.

| Mutation | Result |
|---|---|
| `Enabled()` reverted to `Validate() != nil` | `TestHandleInformationalRefusesAnUnimplementedOperation` fails for both operations: `status = 0, want 2` |
| Fix restored | passes; `md5sum` of `command.go` matches the pre-mutation file |

Live re-verification after the fix:

```
connector-cli help file.write     -> usage: "file.write" is not an operation this version offers; want file.list, file.stat or file.read   rc=2
connector-cli help command.exec   -> the same refusal                                                                                        rc=2
connector-cli help file.read      -> the file.read help                                                                                      rc=0
```

## A second defect in the same function

The same function scanned the arguments for the literal text `--help`:

```go
for _, argument := range arguments {
    if argument == "--help" || argument == "-h" { ... }
}
```

A scan cannot tell a flag from a value, so `--path --help file.read` printed the help
instead of reporting the path. The fix registers `-h`, `--help` and `--version` on the
one flag set and asks `Visit` which of them was written, so the answer comes from the
grammar rather than from a string comparison.

Measured after the fix: `--path --help file.read` no longer prints help; it reports
the missing scope, which is the next real problem with that command line.

Registering `h` is also required for a second reason: without a registered `h`, the
parser returns `ErrHelp` and prints its own usage, which would bypass the documented
help text entirely.

## Detection gap

No test called `handleInformational` at all. The function was reachable only through
`Run`, and every existing `Run` test passed a real operation, so the help path was
never exercised with an operation name.

The rule that follows: a function that answers a question about the vocabulary must
be tested with a name from each category — offered, declared-but-refused, and
unknown — because a single category cannot distinguish the predicates.
