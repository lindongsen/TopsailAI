---
maintainer: AI
author: DawsonLin
status: resolved
---
# Mixed JSON content breaks request formatting with KeyError step_name

## Trigger and evidence

2026-10-30 12:25:51.322, PID 395426: streaming request preparation fails in to_topsailai_format before provider I/O. The same process previously logged a mixed serialized list containing a command argument dictionary without step_name followed by a dictionary with step_name=action. Native streaming response events identify gpt-6-luna.

## Root cause

utils/format_tool.py accepted any JSON text containing the identifier substring, then indexed every top-level dictionary as a step. Ordinary JSON mixed with a step record therefore raises KeyError and poisons subsequent requests using that history. The llm_base.py generic exception handler is the reporting site, not the defect site.

## Repair and verification

Validate all parsed top-level members before converting serialized steps; preserve non-step content verbatim rather than invent identifiers or drop content. Valid step rendering is unchanged. Eight new regression cases cover the actual shape and related boundaries. Format-tool tests: 41 passed. Message and base-class regressions: 146 passed. Loading old HEAD converter separately reproduces the exact KeyError; current converter preserves the identical payload. No commit, full-suite or live-provider validation performed. Awaiting independent review.

Detailed command/evidence index: ../.task/code_20261030T123028_step-name-format.md.

## Closure verification (2026-11-17)

The repair is committed as `c5510af6 fix: Preserve mixed JSON content during step formatting`
(`utils/format_tool.py`, +6/-1). The earlier "no commit performed" note is superseded.

Executed evidence:

- `tests/unit/test_topsailai_utils_format_tool.py` — 41 passed.
- Related regressions (`test_topsailai_utils_format_tool_xml.py`,
  `test_topsailai_ai_base_llm_control_message.py`,
  `test_topsailai_utils_message_tool_pairing.py`) - 195 passed together.
- Direct probe of the reported shape: a serialized list mixing an ordinary
  dictionary (`{"command": "ls -la", "timeout": 10}`) with a real step record no
  longer raises `KeyError: step_name`; the payload is preserved verbatim, and a
  step-only payload still renders as `topsailai.action`.

Residual limitation: no live-provider validation was performed; the defect was
pre-provider request preparation, which the probe covers directly.
