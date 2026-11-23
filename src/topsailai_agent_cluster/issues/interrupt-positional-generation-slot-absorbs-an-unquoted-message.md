---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# `interrupt` positional generation slot absorbs an unquoted message

## Correction notice

An earlier version of this record claimed the usage string
`usage: interrupt [soft|hard] [message]` teaches a two-slot grammar the parser does not implement.
That claim was wrong, and the human rejected it. The string is a **content grammar for the single
`text` slot**, not a description of positional slots, and it agrees with `help interrupt`'s own
`text:` parameter description. The real defect is narrower and lives in the positional generation
slot, not in the usage text. The filename and this record were corrected accordingly.

## Trigger

Found while writing the non-interactive CLI skill. The skill's first draft documented
`interrupt <endpoint> <resource> [soft|hard] [message] [generation]`, copied from the usage string
the binary prints. Verifying that row against `help interrupt` and against real invocations showed
the usage string and the parser disagree about *slot count*. That reading was wrong; the
disagreement is about *which slot an unquoted message lands in*.

## Why the usage string is correct

`usage: interrupt [soft|hard] [message]` is emitted from three sites, and all three describe the
content of one argument rather than a sequence of positionals:

- `internal/tui/interactive_ops.go:422` — an invalid JSON payload was supplied as the text slot.
- `internal/tui/interactive_ops.go:438` — the text slot's first word is not a known action word.
- `internal/tui/interactive_ops.go:1137` — the guided `interrupt.action>` prompt, which asks for an
  action word and nothing else.

The command's positional grammar is stated separately and correctly in the Syntax line:

```text
Syntax: agent-cluster-cli [options] interrupt <endpoint> <resource> [text] [generation]
```

and the same slot is described in the Parameters block as:

```text
text: optional action word soft or hard, optionally followed by a literal message; hard accepts no
      message and is the default when no action word is given
```

`[soft|hard] [message]` and that sentence say the same thing: the `text` slot holds an action word
and, for `soft`, an optional message. Reading `[soft|hard] [message]` as two positionals is a
misreading, because the surrounding Syntax line already accounts for both positionals as
`[text] [generation]`. The usage string therefore needs no change.

## The real defect

The positional generation slot silently absorbs an unquoted message.

`generation` is an unconstrained `string` (`internal/protocol/command.go:47`), so no format check
can distinguish a real generation from a message fragment. `action` assigns positionals by index
(`src/main/agent-cluster-cli/main.go:1581-1648`): `args[3]` is the text slot and `args[4]` is the
generation. `positionalLimit = 5` (`main.go:1535`) is exactly the arity of

```bash
agent-cluster-cli interrupt ac.ai-dev res_8e7ef4b41d733a75867ccbff38c1dcd0 soft "stop now"
```

so `rejectExtraPositionals` accepts it as well-formed, `"stop now"` becomes the generation, and the
payload carries no message:

```text
confirmation required for interrupt target=res_8e7ef4b41d733a75867ccbff38c1dcd0 parameters={"action":"soft_interrupt"}; rerun with --yes
```

With `--yes` the command is rejected for the wrong reason:

```text
status = 'rejected'
error_code = 'target_generation_mismatch'
effect_certainty = 'not_applied'
```

The operator's actual mistake was an unquoted message. The reported cause is a generation mismatch,
which sends the investigation to target identity and the inventory.

## The design already contains the disambiguator

`--generation` exists (`main.go:150`, "target generation; alternative to the positional generation
argument"). Supplying it frees the positional slot, and the comment at `main.go:1557-1561` states
the intent exactly: "A generation supplied by the flag frees its positional slot, so an unquoted
multi-word message is rejected instead of being silently truncated to its first word."

That intent is implemented and observable. The same unquoted message is refused when the generation
comes from the flag:

```text
interrupt <ep> <res> soft "stop now" --generation 626121439
  -> exit 2, unexpected arguments "soft stop now"; quote the message text so it stays one argument
interrupt <ep> <res> soft "stop now"
  -> exit 2, confirmation required ... parameters={"action":"soft_interrupt"}
```

So the codebase already knows how to reject this shape; it only does so when the generation slot is
vacated. The defect is that the positional form has no equivalent guard, which makes the same
mistake silent in one spelling and loud in the other.

## Second defect: the JSON form bypasses every local check

`InterruptPayload` forwards any JSON object unchanged (`interactive_ops.go:419-424`), so the
following all pass the local confirmation gate and reach the Endpoint:

| Payload | Local result | Provider result |
|---|---|---|
| `{"action":"nuke"}` | accepted | `invalid_request`: `interrupt action "nuke" is not supported` |
| `{"action":"soft_interrupt","msg":"x"}` | accepted | `invalid_request`: `json: unknown field "msg"` |
| `{}` | accepted | `invalid_request`: `interrupt action "" is not supported` |

All three are rejected by the Provider before any argv exists
(`providers/topsailai/src/mutation.go:107-116` validates, then builds argv, then runs), so
`effect_certainty` is `not_applied` and nothing is executed. The defect is therefore not a safety
hole. It is a wasted round trip and a misleading error surface: the CLI prints a confirmation
prompt for a payload it could have refused locally.

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

- An unquoted message is silently discarded and the command fails with an unrelated error code.
- The failure is safe (`not_applied`), so nothing is interrupted by accident.
- The cost is diagnostic: the operator is told the generation is wrong when the generation was
  never the subject, and the message they wrote is gone with no mention of it.
- The same mistake is loud when `--generation` is used and silent when it is not, so the outcome
  depends on a spelling choice the operator has no reason to consider.
- Scripts that pass the generation positionally cannot deliver a soft interrupt with a message at
  all unless they quote it.

## Fix direction

1. Do not change the usage string. It correctly describes the `text` slot's content, and the
   Syntax line already states the positional grammar.
2. Reject a text-bearing invocation whose text slot is an action word and whose next positional is
   present, because that shape can only mean an unquoted message. The existing
   `unexpected arguments ... quote the message text` wording is already correct and is already
   produced when `--generation` frees the slot; apply the same guard to the positional form.
3. Prefer `--generation` in the documented examples for the text-bearing family, so the
   unambiguous spelling is the one an operator copies.
4. Validate the JSON form locally against the same action vocabulary `interruptActions` already
   defines, and reject an unknown or empty action before the confirmation prompt. Reuse
   `ctlPayload`'s reasoning rather than adding a second convention.
5. Document `s`, `h`, `soft_interrupt`, `hard_interrupt` and the JSON form in `help interrupt`,
   or remove the undocumented spellings.
6. Keep the two tests that pin the usage string (`internal/tui/interactive_test.go:584,668`). They
   assert a correct string. Add a test for the new positional guard instead, and prove it fails
   when the guard is removed.

## Evidence

All commands were read-only or rejected before execution; no live session was interrupted.

```text
interrupt <ep> <res> "soft stop now"                    -> exit 2, parameters={"action":"soft_interrupt","message":"stop now"}
interrupt <ep> <res> soft "stop now"                    -> exit 2, parameters={"action":"soft_interrupt"}   (message absorbed)
interrupt <ep> <res> soft "stop now" --generation <gen> -> exit 2, unexpected arguments "soft stop now"; quote the message text
interrupt <ep> <res> soft <gen>                         -> exit 2, parameters={"action":"soft_interrupt"}
interrupt <ep> <res> "hard msg"                         -> exit 2, interrupt hard does not accept a message
interrupt <ep> <res> hard msg                           -> exit 2, parameters={"action":"hard_interrupt"}
interrupt <ep> <res>                                    -> exit 2, parameters={"action":"hard_interrupt"}   (documented default)
interrupt <ep> <res> '{"action":"nuke"}' <gen> --yes    -> rejected, invalid_request, not_applied
interrupt <ep> <res> '{}' <gen> --yes                   -> rejected, invalid_request, not_applied
interrupt <ep> <res> soft msg --yes                     -> rejected, target_generation_mismatch, not_applied
```
