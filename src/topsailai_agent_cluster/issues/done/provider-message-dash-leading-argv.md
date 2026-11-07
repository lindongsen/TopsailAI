---
maintainer: AI
author: DawsonLin
---

# Dash-leading single-token message is rejected by the provider parser

## Trigger

Human question: whether the provider command line is assembled as a command string or as a
list-form argv. Probing the installed provider CLI with the exact argv the adapter emits exposed a
message-delivery defect.

## Observed behavior

The adapter emits `runtime send -s KEY -m MESSAGE --json` (`internal/adapter/topsailai/adapter.go`).
Because the message is a separate argv element, the provider's own `argparse` still classifies it.
A message that is one dash-leading token without whitespace is consumed as an option and the
provider fails before delivery:

| Provider argv | Provider result |
|---|---|
| `runtime send -s no-such -m --json --json` | exit 2, `usage_error`, `Invalid runtime arguments` |
| `runtime send -s no-such -m -f --json` | exit 2, `usage_error` |
| `runtime send -s no-such -m -x --json` | exit 2, `usage_error` |
| `runtime send -s no-such -m --help` | exit 2, `usage_error` |
| `runtime send -s no-such -m=-x --json` | exit 3, `target_not_found` (value accepted) |
| `runtime send -s no-such --message=--json --json` | exit 3, `target_not_found` (value accepted) |
| `runtime send -s no-such -m '-- -g value with spaces' --json` | exit 3, `target_not_found` (value accepted) |

The last row explains why the existing regression test passes: `argparse` treats a token containing
a space as a value, so only the single-token dash-leading case is broken. `-1` is also accepted
because `argparse` recognizes negative numbers.

## Impact

A legitimate user message such as `--json`, `-f`, `-x` or `--help` cannot be delivered. The adapter
maps the provider's non-zero exit to `provider_failed` with `EffectUnknown`, so the operator sees an
uncertain effect for a message that was never sent.

## Root cause

`runtimeMessage` returns the literal text and `Execute` passes it as a separate argv element after
`-m`. The provider contract requires the assignment form (`-m=VALUE` / `--message=VALUE`) for values
that begin with a dash, which the adapter already uses for `--task=` in `agent.start`.

## Prevention

Emit the assignment form for `send` and `btw`, and assert the exact argv for a single-token
dash-leading message. Do not add a shell or a quoting layer: the argv list is correct, only the
provider's option/value boundary is wrong.

## Resolution

Fixed in `internal/adapter/topsailai/adapter.go`: `send` and `btw` now emit `"-m=" + message`.
Verified against the installed provider CLI:

| provider argv | before | after |
|---|---|---|
| `-m --json` | exit 2 `usage_error` | not emitted |
| `-m=--json` | exit 3 `target_not_found` | exit 3 `target_not_found` (value accepted) |

Regression test `TestExecuteUsesAssignmentFormForDashLeadingMessage` asserts the exact argv for
both `send` and `btw`. The existing argv expectation was updated to the assignment form.
