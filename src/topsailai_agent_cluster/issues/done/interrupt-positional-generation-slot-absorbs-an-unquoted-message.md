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

Status: resolved by the grammar change described under "Resolution".

## Correction notice

Two earlier readings of this defect were wrong, and both were rejected by the human.

1. The first version claimed the usage string `usage: interrupt [soft|hard] [message]` teaches a
   two-slot grammar the parser does not implement. That was wrong: the string describes the
   **content of one slot**, not a sequence of positionals, and it agreed with `help interrupt`'s own
   `text:` description.
2. The second version kept the single-text-slot grammar and proposed adding a guard to it. The human
   rejected the grammar itself: the action word must be its own slot, so the message never has to be
   prefixed with an action word and the ambiguity is removed structurally rather than guarded.

## Trigger

Found while writing the non-interactive CLI skill. The skill's first draft documented
`interrupt <endpoint> <resource> [soft|hard] [message] [generation]`, copied from the usage string
the binary printed. Verifying that row against `help interrupt` and against real invocations showed
the single-text-slot form silently discarded a message.

## The defect

The positional generation slot silently absorbed an unquoted message.

`generation` is an unconstrained `string` (`internal/protocol/command.go:47`), so no format check
could distinguish a real generation from a message fragment. `action` assigned positionals by index:
`args[3]` was the whole text slot and `args[4]` was the generation. `positionalLimit = 5` was exactly
the arity of

```bash
agent-cluster-cli interrupt ac.ai-dev res_8e7ef4b41d733a75867ccbff38c1dcd0 soft "stop now"
```

so `rejectExtraPositionals` accepted it as well-formed, `"stop now"` became the generation, and the
payload carried no message:

```text
confirmation required for interrupt target=res_8e7ef4b41d733a75867ccbff38c1dcd0 parameters={"action":"soft_interrupt"}; rerun with --yes
```

With `--yes` the command was rejected for the wrong reason:

```text
status = 'rejected'
error_code = 'target_generation_mismatch'
effect_certainty = 'not_applied'
```

The operator's actual mistake was an unquoted message. The reported cause was a generation mismatch,
which sent the investigation to target identity and the inventory.

The design already contained the disambiguator: `--generation` (`main.go:150`) frees the positional
slot, and the same unquoted message was correctly refused when the flag was used. The same mistake
was loud in one spelling and silent in the other.

## Resolution

The human fixed the contract rather than the guard: the action word is a subcommand with its own
positional slot, and both actions accept a message.

```text
interrupt [soft|hard] <endpoint> <resource> [message] [generation]
```

- The action word occupies its own slot, exactly like `drive <start|stop|status>`, so the message is
  a separate positional and never has to be prefixed with an action word.
- Both `soft` and `hard` accept a message. The cluster forwards it without deciding which action may
  carry one, because that is a provider implementation detail.
- The action word may be omitted; omitted means `hard`.
- The generation travels in `--generation` only. There is no positional generation slot, because a
  positional generation is an unconstrained string and would be indistinguishable from a second word
  of an unquoted message.
- A message with no action word is refused rather than guessed.

Implemented in `internal/tui/interactive_ops.go` (`ParseInterruptArguments`, `InterruptActionWord`,
`InterruptPayload(name, action, message)`, `advancedInterruptPayload`) and
`src/main/agent-cluster-cli/main.go` (action word stripped at `args[1]`, `positionalLimit` 4 with an
action word and 3 without, generation from `--generation` only). Both surfaces call the same parser,
so the interactive and standalone grammars cannot drift apart.

## The refusal names no token, because the shape is ambiguous

`interrupt nope ep res` (misspelled action word) and `interrupt ep res "stop now"` (message with no
action word) are structurally identical: three positionals after the command, no known action word.
Naming either token would blame an argument that may be correct. The refusal therefore states the
grammar and the positional count instead:

```text
interrupt needs an action word (soft or hard) before the message; with 3 positionals after the
command the action word is either misspelled or missing; run help interrupt for valid syntax
```

## The JSON form is validated locally against a closed field set

The JSON form is bound to the positional action word, and its field set is closed. A conflicting or
unknown `action` is refused locally, `{}` receives the action word instead of being sent empty, and a
field outside `{action, message}` is refused by name.

```text
interrupt soft <ep> <res> '{"action":"nuke"}'            -> exit 2, JSON action nuke conflicts with the "soft_interrupt" action word
interrupt soft <ep> <res> '{}'                           -> exit 2, parameters={"action":"soft_interrupt"}
interrupt soft <ep> <res> '{"action":"soft_interrupt","msg":"x"}'
                                                         -> exit 2, JSON field "msg" is not part of the interrupt payload; only action and message are accepted
interrupt soft <ep> <res> '{"action":"soft","message":"x"}'
                                                         -> exit 2, the document carries the wire action name
```

The closed set is not a new convention invented here. The provider decodes exactly these two fields
with a strict decoder (`providers/topsailai/src/mutation_argv.go:176-179`), so an unknown key was
already a hard error there. Refusing it locally converts a wasted round trip, which had already asked
the operator for confirmation, into an immediate error that names the offending key.

The two layers carry different spellings on purpose. The command line carries the CLI word (`soft`),
and the JSON document carries the wire name (`soft_interrupt`), because the document is what reaches
the provider. A CLI word inside the document is refused rather than translated, so an operator can
never believe the document is the command line.

## Accepted spellings are exactly the two documented words

`interruptActions` accepts `soft` and `hard`. The abbreviations `s` and `h`, and the wire names
`soft_interrupt` and `hard_interrupt`, are refused.

The reason is consistency rather than minimalism. `drive` accepts `start`, `stop` and `status` with no
abbreviations, and a `ctl` action name is exact. Keeping an abbreviation here would make `interrupt`
the only command where an operator has to guess whether a short form exists. The wire names stay
distinct from the CLI words because they are what the provider decodes, and they are never typed.

## Provider limitation: this provider refuses a message on `hard`

The cluster contract allows a message on both actions, and the cluster forwards it without deciding
which action may carry one. The shipped TopsailAI provider does not implement that: it returns
`hard_interrupt does not accept a message` as `invalid_request` with `not_applied`
(`providers/topsailai/src/mutation_argv.go:218-220`, asserted by `mutation_test.go:613`).

This is a provider limitation, not a cluster contract violation. The cluster side must not be
narrowed to match it, because narrowing the contract to one provider's current behaviour is exactly
the coupling the abstraction layer exists to prevent. An operator on this provider therefore sees a
`hard` interrupt with a message refused at the provider seam, after the cluster accepted it.

## Evidence

All commands were read-only or refused before execution; no live session was interrupted.

An earlier version of this section claimed the target `res_8e7ef4b41d733a75867ccbff38c1dcd0` stayed
`running` with generation `626121439` throughout. That claim is withdrawn. The provider session
`wa-74a99df8715a` (pid 1869631) records `status: completed` with `end_ts: 2026-11-23T13:07:11`, and
its stdout ends at its own `Your Turn` prompt with `q` typed. The interrupt attempts ran at
09:57-09:59 and were all refused before the provider built argv, so they did not end it; the session
finished on its own about three hours later. The correct statement is that no attempt reached the
provider, not that the target was still running afterwards.

```text
interrupt soft <ep> <res> "stop now"                     -> exit 2, parameters={"action":"soft_interrupt","message":"stop now"}
interrupt hard <ep> <res> "please stop"                  -> exit 2, parameters={"action":"hard_interrupt","message":"please stop"}
interrupt <ep> <res>                                     -> exit 2, parameters={"action":"hard_interrupt"}   (documented default)
interrupt <ep> <res> "stop now"                          -> exit 2, needs an action word (soft or hard) before the message
interrupt nope <ep> <res>                                -> exit 2, needs an action word (soft or hard) before the message
interrupt s <ep> <res>                                   -> exit 2, needs an action word (soft or hard) before the message
interrupt h <ep> <res>                                   -> exit 2, needs an action word (soft or hard) before the message
interrupt soft_interrupt <ep> <res>                      -> exit 2, needs an action word (soft or hard) before the message
interrupt soft <ep> <res> stop now                       -> exit 2, unexpected arguments "stop now"; quote the message text
interrupt soft <ep> <res> "stop now" --generation <gen>  -> exit 2, parameters={"action":"soft_interrupt","message":"stop now"}
interrupt soft <ep> <res> '{"action":"nuke"}'            -> exit 2, JSON action nuke conflicts with the "soft_interrupt" action word
interrupt soft <ep> <res> '{}'                           -> exit 2, parameters={"action":"soft_interrupt"}
interrupt soft <ep> <res> '{"action":"soft_interrupt","msg":"x"}'
                                                         -> exit 2, JSON field "msg" is not part of the interrupt payload
interrupt soft <ep> <res> '{"action":"soft","message":"x"}'
                                                         -> exit 2, the document carries the wire action name
interrupt soft <ep> <res> 'use {braces} here'            -> exit 2, parameters={"action":"soft_interrupt","message":"use {braces} here"}
```

Every guard was proven reachable by deliberately breaking it and observing the matching test fail:
removing the closed-field-set check failed `TestInterruptPayloadRefusesFieldsOutsideTheClosedSet`,
and re-adding `"s"` to the action table failed `TestInterruptActionWordsAreExactlyTheDocumentedPair`
with `undocumented action word "s" is accepted`. Both breaks were restored immediately.

One defect was found only by running the real binary, not by any unit test. `main.go` stored the wire
name into `interruptAction` and passed it to `InterruptPayload`, which maps a CLI word to a wire name
and does not accept a wire name, so every interrupt failed with the usage string. The unit tests
called `InterruptPayload` directly with CLI words and therefore never exercised the composition.
`TestInterruptActionWordFeedsInterruptPayload` now asserts that composition, and `InterruptActionWord`
returns the normalized CLI word.

Verification after the change: `make test-unit` green across all four component groups,
`make test-bdd` green for all six groups, `make test-integration` green at 94.261s.
