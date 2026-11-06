---
maintainer: AI
author: DawsonLin
---

# Message text containing --json is rejected or misparsed before delivery

## Trigger

Human report: "cli执行send指令的时候，如果里面有 `--json`这样的内容，就会报错".

## Observed behavior

Three independent layers mishandle a legitimate message whose text contains `--json`. They are
separate defects and must be fixed separately.

### Defect A: interactive REPL rejects prose containing --json

`internal/tui/interactive_ops.go:225` (`interactiveSend`) and `:605`
(`interactiveSessionPayload`) guard with a substring match:

```go
if !json.Valid([]byte(payloadText)) && strings.Contains(payloadText, "--json") {
    return fmt.Errorf("interactive send does not support --json")
}
```

Replicating the guard verbatim shows ordinary prose is refused:

| Input | Result |
|---|---|
| `send please add --json to the config` | `interactive send does not support --json` |
| `send the flag is --json-output` | `interactive send does not support --json` |
| `send hello world` | accepted |
| `send {"text":"use --json"}` | accepted (`json.Valid` short-circuits) |
| `send --json` | rejected (correct) |

The interactive REPL has no `--json` flag at all, so the guard protects nothing while blocking
valid text. The same file already uses the correct exact-token form at `:485`
(`if len(args) == 1 && args[0] == "--json"`), which shows the intended design.

### Defect B: provider argv swallows a single-token dash-leading message

Recorded separately in `issues/provider-message-dash-leading-argv.md`. The adapter emits
`{"runtime","send","-s",key,"-m",message,"--json"}` (`internal/adapter/topsailai/adapter.go:254`
and `:260`), so the provider's own `argparse` classifies the message. Verified live against the
installed CLI:

| Provider argv | Provider result |
|---|---|
| `runtime send -s no-such -p 1 -m --json --json` | `usage_error`, `Invalid runtime arguments` |
| `runtime send -s no-such -p 1 -m=--json --json` | `target_not_found` (value accepted) |

`adapter.go:297-298` then maps that failure to `provider_failed` with `EffectUnknown`, so the
operator sees an uncertain effect for a message that was never sent.

### Defect C: non-interactive CLI turns a trailing --json into the generation

`src/main/agent-cluster-cli/main.go` `action()` maps positionals as `payload=args[3]` and
`generation=args[4]` (`:300`, `:306-307`). `flag.Parse` stops at the first positional, so a
trailing `--json` stays positional. Verified with a replicated `flag.FlagSet`:

| argv | parsed args | payload | generation |
|---|---|---|---|
| `send ep-1 res-1 hello --json` | `["send","ep-1","res-1","hello","--json"]` | `hello` | `--json` |
| `send ep-1 res-1 hello gen-1` | `["send","ep-1","res-1","hello","gen-1"]` | `hello` | `gen-1` |
| `--json send ep-1 res-1 hello` | `["send","ep-1","res-1","hello"]` | `hello` | `` |

The endpoint then fails with `resource generation does not match`
(`internal/endpoint/executor.go:216-232`). The `jsonMode` parameter is accepted by `action()` but
never referenced in its body, so the operator receives neither JSON output nor a diagnostic
explaining the misparse.

Quoted prose is safe in this path: `send ep-1 res-1 "please add --json to the config"` reaches
`parameters=please add --json to the config`.

## Impact

A user cannot send a message that mentions `--json`, which is common when discussing CLI usage. In
the non-interactive path the same token silently corrupts the target generation and produces a
misleading generation-mismatch error instead of a usage error.

## Root cause

All three layers classify options by substring or by raw positional index instead of by token
boundary. The REPL uses `strings.Contains`; the CLI relies on `flag.Parse` having already stopped at
the first positional; the adapter relies on the provider parser treating a separate argv element as
a value.

## Prevention

Classify options by token boundary, never by substring. Reject only a payload that is itself an
option token, reject or consume a dash-leading positional before it can be mapped to a generation,
and emit the provider assignment form (`-m=VALUE`) for values that may begin with a dash. Add
regression tests for prose containing `--json` in the interactive path, for a trailing `--json` in
the non-interactive path, and for a single-token dash-leading message in the adapter argv.

## Test blind spots

- `internal/tui/interactive_actions_test.go:33` iterates
  `{"resume","stop","inject","interrupt","btw","control"}`; `send` is absent, and the only
  `--json` payloads are JSON documents that short-circuit `json.Valid`.
- `internal/adapter/topsailai/adapter_test.go:147-152` asserts the argv for a message containing
  spaces, which `argparse` treats as a value, so the single-token case is never exercised.
- No test asserts that a dash-leading positional is rejected before generation mapping.

## Resolution

All three defects are fixed.

| Defect | Fix | Regression test |
|---|---|---|
| A: REPL substring match | `rejectJSONFlagPayload` rejects only a bare `--json` or a JSON object followed by a stray `--json`; prose stays deliverable | `TestInteractivePlainTextActionsNeedNoJSON` prose cases |
| B: provider option/value boundary | `send`/`btw` emit `-m=VALUE` | `TestExecuteUsesAssignmentFormForDashLeadingMessage` |
| C: trailing `--json` became generation | `rejectMisplacedFlags` rejects a dash-leading positional before mapping | `TestActionRejectsMisplacedFlag` |

Verified behavior of the built CLI:

| argv | result |
|---|---|
| `send ep-1 res-1 hello --json` | exit 2, `option "--json" must be written before the command` |
| `send ep-1 res-1 hello -1` | accepted, generation `-1` |
| `send ep-1 res-1 '{"text":"--json"}' gen-1` | accepted, payload `{"text":"--json"}` |

Defect D (unquoted multi-word text truncated to `args[3]`) remains open: the misplaced-flag guard
does not cover a plain extra word. Tracked separately.
