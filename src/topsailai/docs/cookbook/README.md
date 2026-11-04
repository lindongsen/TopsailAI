---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Cookbook

Requirements for every document and example placed in this folder.

A cookbook entry answers one question: **how do I extend the agent from outside the package for a
task I actually have?** It is not an API reference, not a design rationale, and not a mechanism
demo.

## Scope

| Content | Owning location |
|---|---|
| Task-oriented, runnable recipes for external extension points | `docs/cookbook/<topic>/` |
| Environment variable reference | `docs/Environment_Variables.md` |
| Module behavior and options | that module's `readme.md` |
| Design rationale, responsibilities, trade-offs | `features/` |
| Public Python API contract | `docs/Hooks_API.md` and the owning module document |

An entry MUST link to the owning document instead of restating it. Duplicated reference tables are
rejected, because they drift.

## Folder Layout

```text
docs/cookbook/
├── README.md
└── <topic>/
    ├── <Topic_Name>.md
    └── examples/
        └── <plugin_folder>/
            └── <module>.py
```

- One topic per folder, named after the extension point (`tool/`, `instruction/`, ...).
- The document name states the capability, not the mechanism internals.
- `examples/<plugin_folder>/` MUST be a folder that the documented environment variable can point at
  directly: absolute path, no trailing slash, folder name a valid Python identifier, direct child
  `.py` files only.
- An example MUST NOT live in `tests/`, `.tmp/`, or a scratch directory. If it is not committed
  under `examples/`, it is not a cookbook example.

## Requirements for Examples

**R1 — Start from a real task.** Every example MUST open with a concrete operational situation: who
acts, what triggers the work, and what decision the agent or the human must make. State it in the
module docstring, in one or two sentences, before any code.

**R2 — No mechanical demo.** The following are rejected:

- placeholder data (`foo`, `bar`, `hello`, `a + b`, `item1`, `test123`);
- a scenario invented only to exercise the mechanism, with no plausible user behind it;
- the same scenario reused across topics with a renamed function;
- a wrapper, adapter, or extra layer whose only purpose is to make the demo run;
- an example copied from a unit-test fixture, where the data exists to assert a branch rather than
  to do work.

**R3 — The extension point must be the natural solution.** The example has to show a case where the
mechanism is the right answer, not merely a possible one. State the reason the capability is needed
(for example: the model generates SQL, so the connection is opened read-only; the context is
expensive, so the output is bounded and reports what it skipped). If the same result is easier to
get without the extension point, the example is wrong.

**R4 — Runnable as committed.** The example MUST run from a clean checkout with only the documented
environment variables set. No manual editing, no uncommitted helper, no undeclared third-party
dependency. Standard library only unless the document states the dependency and its install step.

**R5 — Verified output.** Every command and every output block MUST come from an actual run on this
repository. Invented output, "should print", and reconstructed-from-memory output are rejected. Keep
the exact command next to the output it produced.

**R6 — Show the failure path.** At least one rejected or malformed input MUST be shown with its real
message. A tool example MUST return an error string rather than raise, and the document MUST show
that behavior instead of only describing it.

**R7 — Limitations verified from the loader.** Every claim about path rules, separators, load
timing, precedence, error isolation, or reload behavior MUST be checked against the loading code, not
assumed from the mechanism's name. A limitation that cannot be reproduced MUST be removed rather than
softened.

**R8 — Safe by default.** No credentials, tokens, private keys, internal hostnames, or personal
paths. No destructive command, no write outside a temporary folder, no unbounded read. An example
that can damage data MUST be read-only or explicitly bounded, and the document MUST say which layer
provides the protection.

**R9 — One idea per example.** Do not add a second example that only renames the first. A new example
is justified only by a different task, a different risk, or a different output shape.

## Requirements for the Document

- Front matter with `maintainer: AI`, `author`, `workspace`, `ProjectFolder`, `ProjectRootFolder`,
  `ProjectCode`, and `programming_language`.
- English prose. No numbered headings. Every fenced block declares a language. Blank lines around
  tables, lists, and fences.
- Open with the problem the reader has, then the mechanism. A document that starts with the
  environment variable name is rejected.
- A full-file code block MUST match the committed file under `examples/` byte for byte. Partial
  snippets MUST be marked as excerpts and MUST be copied from the same file.
- Requirements and limitations belong in a table, one row per fact, phrased as observed behavior.
- Cross-links MUST resolve relative to the document's own folder. A rename or move requires sweeping
  both directions: outgoing `](...)` targets and inbound references to the old path.
- No secrets, no absolute personal paths, no `curl`-style examples where a named request or command
  is clearer.

## Acceptance Checklist

- [ ] The scenario is real, stated up front, and has an identifiable actor and trigger.
- [ ] The example is not a placeholder demo, not a renamed duplicate, and not a test fixture.
- [ ] The extension point is the natural solution for the stated task.
- [ ] The example runs as committed through the documented environment variable.
- [ ] Every command and output block was produced by a real run.
- [ ] A rejected input and its real message are shown.
- [ ] Every limitation was verified against the loading code.
- [ ] Each full-file block equals the committed example file.
- [ ] Links resolve, and no reference table is duplicated from the owning document.
- [ ] No secrets, no destructive command, no unbounded read or write.
