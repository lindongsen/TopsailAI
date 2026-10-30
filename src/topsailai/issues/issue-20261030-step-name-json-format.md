---
maintainer: AI
author: DawsonLin
status: awaiting-review
---
# Mixed JSON content breaks request formatting with KeyError step_name

## Trigger and evidence

2026-10-30 12:25:51.322, PID 395426: streaming request preparation fails in to_topsailai_format before provider I/O. The same process previously logged a mixed serialized list containing a command argument dictionary without step_name followed by a dictionary with step_name=action. Native streaming response events identify gpt-6-luna.

## Root cause

utils/format_tool.py accepted any JSON text containing the identifier substring, then indexed every top-level dictionary as a step. Ordinary JSON mixed with a step record therefore raises KeyError and poisons subsequent requests using that history. The llm_base.py generic exception handler is the reporting site, not the defect site.

## Repair and verification

Validate all parsed top-level members before converting serialized steps; preserve non-step content verbatim rather than invent identifiers or drop content. Valid step rendering is unchanged. Eight new regression cases cover the actual shape and related boundaries. Format-tool tests: 41 passed. Message and base-class regressions: 146 passed. Loading old HEAD converter separately reproduces the exact KeyError; current converter preserves the identical payload. No commit, full-suite or live-provider validation performed. Awaiting independent review.

Detailed command/evidence index: ../.task/code_20261030T123028_step-name-format.md.
