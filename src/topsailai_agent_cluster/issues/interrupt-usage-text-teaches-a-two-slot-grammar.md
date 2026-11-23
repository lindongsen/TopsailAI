---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# `interrupt` usage text teaches a two-slot grammar the parser does not implement

## Trigger

Found while writing the non-interactive CLI skill. The skill's first draft documented
`interrupt <endpoint> <resource> [soft|hard] [message] [generation]`, copied from the usage
string the binary itself prints. Verifying that row against `help interrupt` and against real
invocations showed the usage string and the parser disagree.

## Symptom

The usage error prints:

```text
usage: interrupt [soft|hard] [message]
```

That reads as two independent positional slots: an action word, then a message. The parser
implements one slot. `interrupt <endpoint> <resource> <text> <generation>` is the real grammar,
and `<text>` is a single argument that must itself contain the action word and, for `soft`, the
message.

An operator who follows the usage text literally writes:

```bash
agent-cluster-cli interrupt ac.ai-dev res_8e7ef4b41d733a75867ccbff38c1dcd0 soft "stop now"
```

The message lands in the generation slot. The confirmation line proves it, because the payload
carries no message at all:

```text
confirmation required for interrupt target=res_8e7ef4b41d733a75867ccbff38c1dcd0 parameters={"action":"soft_interrupt"}; rerun with --yes
```

With `--yes` the command is rejected for the wrong reason:

```text
status = 'rejected'
error_code = 'target_generation_mismatch'
effect_certainty = 'not_applied'
```

The operator's actual mistake was an unquoted message. The reported cause is a generation
mismatch, which sends the investigation to the target identity and the inventory.

## Root cause

`action` assigns positionals by index (`src/main/agent-cluster-cli/main.go:1581-1648`):

- `args[3]` is the text payload, resolved through `resolveActionPayload`.
- `args[4]` is the generation.

`InterruptPayload` (`internal/tui/interactive_ops.go:417`) receives only `args[3]`, already
joined into one string, so it can never see that a second argument existed. It splits that one
string with `splitInteractiveArguments` and treats the first word as the action word.

`rejectExtraPositionals` does not catch the case because the text-bearing family sets
`positionalLimit = 5` (`main.go:1535`), which is exactly the arity of
`interrupt <endpoint> <resource> soft "stop now"`. The invocation is therefore accepted as
well-formed and the message is silently reclassified as a generation.

The usage string is produced in three places and all three describe the two-slot grammar:

- `internal/tui/interactive_ops.go:422` (invalid JSON payload)
- `internal/tui/interactive_ops.go:438` (unknown action word)
- `internal/tui/interactive_ops.go:1137` (guided prompt, unknown action)

## Why the tests do not catch it

Two tests pin the wrong string, so the defect is certified rather than detected:

- `internal/tui/interactive_test.go:584` asserts `usage: interrupt [soft|hard] [message]` for an
  unknown action word.
- `internal/tui/interactive_test.go:668` asserts the same string for the guided prompt.

Both assert the message text, never the grammar it describes. This is the recorded pattern from
`LEARN.md`: a test that asserts the buggy behaviour converts "nobody checked" into "somebody
checked and approved".

## Second defect: the JSON form bypasses every local check

`InterruptPayload` forwards any JSON object unchanged (`interactive_ops.go:419-424`), so the
following all pass the local confirmation gate and reach the Endpoint:

| Payload | Local result | Provider result |
|---|---|---|
| `{"action":"nuke"}` | accepted | `invalid_request`: `interrupt action "nuke" is not supported` |
| `{"action":"soft_interrupt","msg":"x"}` | accepted | `invalid_request`: `json: unknown field "msg"` |
| `{}` | accepted | `invalid_request`: `interrupt action "" is not supported` |

All three are rejected by the Provider before any argv exists (`providers/topsailai/src/mutation.go:107-116`
validates, then builds argv, then runs), so `effect_certainty` is `not_applied` and nothing is
executed. The defect is therefore not a safety hole. It is a wasted round trip and a misleading
error surface: the CLI prints a confirmation prompt for a payload it could have refused locally.

`{}` is the sharpest case, because the two forms disagree about the same intent. A bare
`interrupt <endpoint> <resource>` submits `{"action":"hard_interrupt"}` and is documented as the
hard default, while `interrupt <endpoint> <resource> '{}'` submits `{}` and is rejected. One
intent, two outcomes, decided by which spelling was typed.

This is a project-wide convention rather than an `interrupt` omission: `MessagePayload`
(`interactive_ops.go:371-384`) has the identical shape, and `send` with `{"txt":"hello"}` is
also forwarded unchanged. `ctl` is the exception, because `ctlPayload`
(`internal/tui/interactive_ctl.go:73-82`) rejects a non-object and `ctlPreflightAction`
validates the action name against the advertised capabilities. So the codebase already contains
the stronger pattern; `interrupt` and `send` simply do not use it.

## Third defect: accepted spellings are undocumented

`interruptActions` (`interactive_ops.go:405-412`) accepts six spellings, and `help interrupt`
documents two:

| Accepted | Documented |
|---|---|
| `soft`, `hard` | yes |
| `s`, `h` | no |
| `soft_interrupt`, `hard_interrupt` | no |

Verified: `interrupt <ep> <res> s` submits `{"action":"soft_interrupt"}` and
`interrupt <ep> <res> h` submits `{"action":"hard_interrupt"}`. The help body contains no
mention of either abbreviation, and `grep -ci 'json object'` on `help interrupt` returns `0`,
so the JSON form is undocumented as well even though `resolveActionPayload`'s own comment
(`main.go:1471-1472`) calls it "the advanced form".

## Impact

- A documented invocation silently discards the message and fails with an unrelated error code.
- The failure is safe (`not_applied`), so nothing is interrupted by accident.
- The cost is diagnostic: the operator is told the generation is wrong when the generation was
  never the subject, and the message they wrote is gone with no mention of it.
- Scripts that follow the usage text cannot deliver a soft interrupt with a message at all.

## Fix direction

1. Make the usage string state the real grammar: `usage: interrupt [text] [generation]`, with
   the text described as "action word, optionally followed by a message". One slot, not two.
2. Reject a text-bearing invocation whose text slot is an action word and whose next positional
   is present, because that shape can only mean an unquoted message. The existing
   `unexpected arguments ... quote the message text` wording already exists for the three-word
   case and is the right message here.
3. Validate the JSON form locally against the same action vocabulary `interruptActions` already
   defines, and reject an unknown or empty action before the confirmation prompt. Reuse
   `ctlPayload`'s reasoning rather than adding a second convention.
4. Document `s`, `h`, `soft_interrupt`, `hard_interrupt` and the JSON form in `help interrupt`,
   or remove the undocumented spellings.
5. Replace the two tests that pin the old usage string instead of adding new ones beside them,
   because the old assertions will otherwise keep certifying the two-slot grammar.

## Evidence

All commands were read-only or rejected before execution; no live session was interrupted.

```text
interrupt <ep> <res> "hard msg"        -> exit 2, "interrupt hard does not accept a message"
interrupt <ep> <res> hard msg          -> exit 2, parameters={"action":"hard_interrupt"}
interrupt <ep> <res> soft "stop now"   -> exit 2, parameters={"action":"soft_interrupt"}
interrupt <ep> <res> '{"action":"nuke"}' <gen> --yes -> rejected, invalid_request, not_applied
interrupt <ep> <res> '{}' <gen> --yes  -> rejected, invalid_request, not_applied
interrupt <ep> <res> soft msg --yes    -> rejected, target_generation_mismatch, not_applied
```
