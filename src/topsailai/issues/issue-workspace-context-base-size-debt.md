---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: open
---

# Issue: Workspace Context Base Code-Size Debt

## Symptom

`workspace/context/base.py` is 1,298 lines, exceeding the project's mandatory 700-line limit by 598 lines.

## Evidence

This is pre-existing size debt. The file was already oversized before U5 and U6:

- U6 added a passive executor seam, changing the file from 1,250 to 1,251 lines.
- U5 added the narrow generation-checkpoint seam, changing the file from 1,251 to 1,298 lines.

Both additions were explicitly approved narrow exceptions. They do not make further growth acceptable.

## Impact

The oversized module has a high maintenance and review cost. Further non-trivial changes increase the risk of coupling unrelated context lifecycle responsibilities and make the mandatory file-size constraint harder to restore.

## Recommended Follow-up

Before any non-trivial future modification to `workspace/context/base.py`, separately authorize a maintenance/refactor task to split the module into cohesive files, with every resulting code file at or below 700 lines.

The U5 and U6 narrow exceptions must not be reused as authority for additional growth. The refactor must preserve public behavior and include targeted regression coverage for the separated responsibilities.
