---
maintainer: AI
author: DawsonLin
---

# Terminal editing

| Case | Exact keys | Expected effect |
| --- | --- | --- |
| EDIT-01 | `he`, TAB | input becomes `help `; no execution until Enter |
| EDIT-02 | session `st`, TAB | candidates stop and status; typed st retained; no stop performed |
| EDIT-03 | empty TAB twice | scope-permitted canonical candidates; prompt remains usable |
| EDIT-04 | `unknownprefix`, TAB | no match, text preserved, no exit |
| EDIT-05 | `send hello`, TAB | arguments unchanged; do not press Enter on a user session |
| EDIT-06 | `hep`, Left, TAB | cursor-middle input remains unchanged; no malformed-key error |
| EDIT-07 | type `helx`, Backspace, `p`, Enter | executes help, one green prompt after completion |
| EDIT-08 | Up, Down | prior command recalled; unfinished draft restored; confirmation/task answers excluded from history |
| EDIT-09 | Home/Ctrl-A, End/Ctrl-E, Left/Right, Delete | expected cursor movement/deletion, Unicode rune boundaries preserved |
| EDIT-10 | long printable line, narrow then wide terminal | soft-wrapped input block keeps the head visible; block bounded by terminal height; over-limit submission rejected without executing partial text |
| EDIT-11 | confirmation or wizard field TAB | no command completion, answer not submitted or exposed to history |
| EDIT-12 | new disposable CLI window: Ctrl-D on empty line; separate window Ctrl-C at prompt | CLI exits under current policy, terminal restored; neither kills provider agent |

Save ANSI output for color checks. Do not use Ctrl-C as an input-clear shortcut: current policy exits at the prompt. Use backspace or a disposable window. Malformed escape input must never execute trailing pasted text as a command.
