---
maintainer: AI
author: DawsonLin
---

# Interactive `help btw` renders the canonical name `inject`

## Symptom

In the REPL, `help btw` prints a detail block whose heading is `inject`:

```text
inject

Syntax: inject [text]
Available in: session
Description: inject context into the selected session; ...
```

The operator asked for `btw` and receives a block titled with the other spelling.

## Cause

`helpTarget` normalizes the argument through `canonicalCommandName`, and
`commandAliases` maps `btw` to `inject`. `PrintScopedCommandHelp` then renders
`commandHelpCatalog["inject"]` under the canonical name, so the alias the
operator typed is replaced by the canonical spelling.

## Impact

Cosmetic, but it weakens the alias: an operator who only knows `btw` sees a
heading for a command they never typed, and may conclude `btw` is not a real
command. The exception line added for the interactive no-options rule names
`btw` inside the body, so the heading and the body now disagree.

## Reproduction

```text
agent-cluster-cli interactive
help btw
```

## Suggested fix

Render the spelling the operator asked for as the heading while keeping the
canonical entry for the body, or state the alias explicitly in the block, for
example `btw (alias of inject)`. The same question applies to `control`
(`interrupt`) and `q` (`quit`).

## Resolution

Fixed by rendering the spelling the operator typed as the heading while keeping
the canonical entry for the body. `printCommandDetail` now takes a separate
`heading` and `target`: the heading is the typed spelling, and `target` stays
canonical so the scope line and the `list` field list are still looked up by the
command that owns them. `helpSpelling` normalizes the argument the same way
`helpTarget` does but without alias canonicalization.

The same fix covers `control` (`interrupt`) and `l` (`list`). `q` (`quit`) is
unaffected in practice because its scoped entry is rewritten per scope, but it
follows the same rule.

The alias tests were updated to compare bodies while asserting the heading is the
typed spelling: `TestInteractiveControlAliasesAreDocumented`,
`TestListAliasMatchesCanonicalHelp` and `TestUnitACommandMetadataIsConsistent`.
Byte-identity was the wrong contract, because it forced the heading to the
canonical name.

`PrintCommandHelp` deliberately keeps the canonical heading: it is a test-only
entry point, and `TestUnitCStartStandaloneHelpMatchesCurrentPreCContract` pins
SHA-256 digests for `btw` and `control` through it. The REPL path is
`PrintScopedCommandHelp`, which is the one that had the defect.

## Status

Resolved. Moved to `issues/done/`.
