---
maintainer: AI
author: DawsonLin
status: planned-not-executed
---

# Startup and configuration

Apply [safety, prerequisites and evidence rules](README.md). Expand all variants; initial status NOT RUN.

| ID | Priority / environment | Given | When | Then |
|---|---|---|---|---|
| CFG-01 | P0 I | Missing root with writable parent, then existing empty root | Run list twice | Creates object/meta, current layout marker and namespace lock; empty structural array; second invocation preserves layout; no .env generated |
| CFG-02 | P0 I | Synthetic HOME, no root setting, clean cwd | Run list/create | Uses synthetic HOME/.topsailai/data only; no operator-store access |
| CFG-03 | P0 I | Explicit root plus competing default/sentinel root | Invoke installed skill | Only explicit root used; resolved executable hash matches intended build |
| CFG-04 | P1 I | Different clean cwds; relative and absolute root settings | Start separate processes | Relative root follows cwd; absolute root stable across cwd changes; stored refs remain relative |
| CFG-05 | P1 I | Conflicting process env/.env/.env.local | Run precedence variants | Nonempty env wins; current loader fills .env before missing .env.local keys; do not assume .env.local overrides |
| CFG-06 | P1 I | Quotes, spaces, Unicode paths, comments and blank dotenv lines | Load supported dotenv forms | Correct root, no assumed shell expansion; settings apply only to child, no persistent config written |
| CFG-07 | P0 F | Nonempty unmarked or legacy-marked root | Run list and help | Clear refusal; no implicit migration; existing bytes unchanged; record possible namespace-lock creation |
| CFG-08 | P0 F | Corrupt/newer/wrong-layout marker; root/object/meta is file or symlink | Initialize each variant | Reject unsafe/incompatible structure; no outside target change |
| CFG-09 | P1 F | Proven unwritable path | Initialize/create | Actionable nonzero error; no false success; partial initialization effects recorded |
| CFG-10 | P1 I | Unknown adapters, negative/nonnumeric retention, unsupported stat flush, nonpositive file limit | Invoke command | Clear validation failure, no object mutation |
| CFG-11 | P1 I | READ_LOCK/INCLUDE_DELETED/TRACK_STAT values 0/1/false/true | Run relevant cases | Supported boolean behavior matches configuration; invalid spelling behavior explicitly checked, not guessed |
| CFG-12 | P1 I | Safe root | No args/help/top-level and subcommand help/unknown command | Readable usage and correct exit; initialization effects confined to root |
| CFG-13 | P1 I | Missing/excess arguments, unknown flags, flags before/after positionals, closed stdin | Invoke command families | Useful errors or supported interaction; no silent indefinite wait, corruption or stray objects |
| CFG-14 | P2 I | Real PTY and separate start/interact scripts | Missing inputs, EOF, cancellation, Unicode, narrow terminal | Human can understand next action; confirm actual prompts per command, do not assume universal interactive mode or exposed REPL |
| CFG-15 | P0 I | Agent uses registered skill with isolated root | Ask for create/list/show/read | Correct binary/root and --from behavior; not merely a project-local smoke check |

Traceability: additional live startup/configuration coverage; smoke.feature supplies the basic business-flow baseline. Exit only after required variants pass, sentinels are intact and blocked prerequisites receive disposition.
