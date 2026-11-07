---
maintainer: AI
author: DawsonLin
---

# Global options written after the subcommand are silently ignored

## Trigger

Observed while verifying a rejected `send` on the live local cluster:

```text
agent-cluster-cli send local-endpoint res-does-not-exist "probe" --yes
confirmation required for send target=res-does-not-exist parameters={"text":"probe"}; rerun with --yes
```

The operator did rerun with `--yes`, and the tool still asked for confirmation.

## Observed behavior

Go's `flag` package stops parsing at the first non-flag argument, so every global option written after
the subcommand becomes positional data:

| Invocation | Actual result |
|---|---|
| `send ep res "probe" --yes` | `--yes` ignored, confirmation still required |
| `send ep res --yes` | `--yes` delivered as the message text |
| `send ep res "probe" --endpoint ep` | `--endpoint` ignored |
| `--yes send ep res "probe"` | works |

The `--yes` case is the most damaging because the error message tells the operator to add `--yes`, and
adding it in the natural place has no effect. The `--endpoint` case silently changes the query scope
instead of failing.

## Impact

- A mutating action cannot be confirmed in the position the error message suggests.
- A filter written after the subcommand is silently dropped, so the operator may act on a different
  scope than intended.
- The failure mode is silent for filters and misleading for confirmation.

## Resolution

`hoistTrailingFlags` moves recognized global options that appear after the subcommand in front of it
before parsing. Options the subcommand owns (for example `list --clean`) are left in place, and `--`
still terminates option parsing so a literal value beginning with a dash remains expressible.

## Prevention

`TestHoistTrailingFlags` and `TestTrailingGlobalFlagsAreHonoured` pin the hoisting rules and the
end-to-end behaviour, including the `list --clean` case that must not be hoisted and the `--` terminator.
