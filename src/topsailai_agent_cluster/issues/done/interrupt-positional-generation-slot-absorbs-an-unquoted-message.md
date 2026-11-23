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

## Remaining gap: the JSON form still forwards unknown fields

The JSON form is now bound to the positional action word: a conflicting or unknown `action` is
refused locally, and `{}` receives the action word instead of being sent empty.

```text
interrupt soft <ep> <res> '{"action":"nuke"}'            -> exit 2, JSON action nuke conflicts with the "soft_interrupt" action word
interrupt soft <ep> <res> '{}'                           -> exit 2, parameters={"action":"soft_interrupt"}
```

An unknown **field** is still forwarded, so `{"action":"soft_interrupt","msg":"x"}` reaches the
Endpoint and is refused there with `invalid_request` / `not_applied`. This is the project-wide
convention rather than an `interrupt` omission: `MessagePayload` has the identical shape, and `ctl`
is the exception because `ctlPayload` and `ctlPreflightAction` validate more. The action is the
safety-relevant part and it is now validated locally; a stricter field check remains a separate
decision.

## Accepted spellings

`interruptActions` accepts six spellings: `soft`, `hard`, `s`, `h`, `soft_interrupt`,
`hard_interrupt`. `help interrupt` documents `soft` and `hard`. The abbreviations and the JSON form
are accepted but undocumented; documenting or removing them remains open.

## Evidence

All commands were read-only or refused before execution; no live session was interrupted. The target
`res_8e7ef4b41d733a75867ccbff38c1dcd0` stayed `running` with generation `626121439` throughout.

```text
interrupt soft <ep> <res> "stop now"                     -> exit 2, parameters={"action":"soft_interrupt","message":"stop now"}
interrupt hard <ep> <res> "please stop"                  -> exit 2, parameters={"action":"hard_interrupt","message":"please stop"}
interrupt <ep> <res>                                     -> exit 2, parameters={"action":"hard_interrupt"}   (documented default)
interrupt <ep> <res> "stop now"                          -> exit 2, needs an action word (soft or hard) before the message
interrupt nope <ep> <res>                                -> exit 2, needs an action word (soft or hard) before the message
interrupt soft <ep> <res> stop now                       -> exit 2, unexpected arguments "stop now"; quote the message text
interrupt soft <ep> <res> "stop now" --generation <gen>  -> exit 2, parameters={"action":"soft_interrupt","message":"stop now"}
interrupt soft <ep> <res> '{"action":"nuke"}'            -> exit 2, JSON action nuke conflicts with the "soft_interrupt" action word
interrupt soft <ep> <res> '{}'                           -> exit 2, parameters={"action":"soft_interrupt"}
```

Both refusal assertions were proven reachable by deliberately breaking the guard: restoring the old
wording failed the positive assertion, and keeping the wording while naming the endpoint failed the
negative assertion.
