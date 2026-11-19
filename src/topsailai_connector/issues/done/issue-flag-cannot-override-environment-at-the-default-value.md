---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-19
---

# A flag could not override the environment when its value equalled the default

## Symptom

The documented precedence rule is "a flag wins over the environment". It was false
for exactly the values a caller is most likely to want to set explicitly.

Measured on the built binary against a live Server, with
`CONNECTOR_CLI_OFFSET=5` exported:

| Invocation | Output | Expected |
|---|---|---|
| `CONNECTOR_CLI_OFFSET=5 connector-cli --scope project --path notes.md file.read` | `ject notes...` (5 bytes skipped) | 5 bytes skipped |
| `CONNECTOR_CLI_OFFSET=5 connector-cli --scope project --path notes.md --offset 0 file.read` | `ject notes...` (5 bytes skipped) | the whole file |

The second row is the defect: the caller typed `--offset 0` and the environment
still won.

## Cause

`firstInt64` and `firstBool` decided whether the flag had been written by comparing
its value with the default:

```go
func firstInt64(flagValue int64, environmentValue, name string) (int64, error) {
    if flagValue != 0 {
        return flagValue, nil
    }
    ...
}
```

A value equal to the default is indistinguishable from an absent flag under that
test, so `--offset 0` read as "not set" and fell through to the environment. The
same shape affected `--length 0` and `--force=false`, and the boolean case was
worse: `CONNECTOR_CLI_FORCE=1` silently re-enabled a switch the caller had just
turned off.

## Fix

`parseArguments` now collects the set of flags actually written from
`flag.FlagSet.Visit`, which reports only the flags present on the command line, and
passes that set into both helpers. The signal is "was the flag written", not "does
the value differ from the default".

`Visit` is also what makes `-o ""` distinguishable from an absent `-o`, so the same
mechanism answers two questions that the value cannot.

## Verification

Mutation-tested in both directions, because a precedence test that passes with the
fix removed is measuring nothing.

| Mutation | Result |
|---|---|
| `firstInt64` reverted to `if flagValue != 0` | `TestParseArgumentsLetsAZeroOffsetOverrideTheEnvironment` fails: `Offset = 5, want 0` |
| `firstBool` reverted to `if flagValue` | `TestParseArgumentsLetsAFalseForceOverrideTheEnvironment` fails: `usage: --force requires -o` |
| Fix restored | both pass; `md5sum` of `command.go` matches the pre-mutation file |

Live re-verification after the fix, against the real Server:

```
CONNECTOR_CLI_OFFSET=5 connector-cli ... file.read              -> ject notes...   (5 skipped)
CONNECTOR_CLI_OFFSET=5 connector-cli ... --offset 0 file.read   -> # Project notes (whole file)
```

## Detection gap

`TestRunFlagsOverrideTheEnvironment` existed and passed, because it used a
non-default flag value. A precedence test that only uses a non-default value cannot
see this defect: the value-based test and the written-based test agree on every
input except the default, which is the one input the defect is about.

The rule that follows: a precedence test must include the case where the flag value
equals the default, because that is the only case where the two implementations
differ.
