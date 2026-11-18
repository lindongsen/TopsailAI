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

## Re-measured on 2026-11-17

`workspace/context/base.py` is now **1,658 lines**, not the 1,298 recorded above. The debt grew
by 360 lines after this issue was written, so the recorded figure and the "598 lines over the
limit" statement are both stale.

This remains a standing constraint rather than a defect to repair: the file must not grow further
without a separately authorized split, and the U5/U6 narrow exceptions still do not authorize
additional growth. The issue stays open until that refactor is authorized and completed.

## Split plan prepared on 2026-11-18, awaiting authorization

A concrete split plan now exists at `.task/plan_20261118T094031_workspace-context-base-split.md`.
No production code was changed. The plan is the "separately authorized maintenance/refactor
task" this issue requires, and the issue stays open until a human authorizes it.

The plan records the constraint that makes this refactor non-mechanical: **312 test patch
sites** target module-level names on `topsailai.workspace.context.base`
(`env_tool` 72, `ctx_manager` 70, `AgentBase` 51, `get_llm_chat` 28, and ten more names).
`patch("base.env_tool")` replaces the name in the base module namespace only, so a method
that moves to another file and keeps its own `from ... import env_tool` reads the unpatched
original. Measured: `patch pkg2.base.env_tool` leaves a mixin reading `original`, while
`patch mixin.env_tool` reaches it. A naive move therefore disables all 312 patches while
every test still passes, which is the dangerous failure mode for this refactor.

Five mechanisms were measured; only one works in both import orders: moved methods read
dependencies through `self._deps.<name>`, where `_deps` is a property on the composed class
returning `sys.modules[__name__]`. A mixin that instead does
`from pkg import base as _base` at module top raises `ImportError: cannot import name
'Mixin' from partially initialized module` when the mixin is imported first.

The proposed decomposition yields six files, all at or below 700 lines: `base.py` ~200,
`context_message_mixin.py` ~326, `context_observation_mixin.py` ~351,
`context_summary_window_mixin.py` ~387, `context_watermark_mixin.py` ~234,
`context_summary_generation_mixin.py` ~314. All 14 cross-group call edges are
`self.<method>`, so no mixin needs to import another.

Baseline for the four directly affected test files is **285 passed in 2.60s**, recorded
before any edit so the split can be proven behaviour-preserving.

Two items still need a decision before implementation:

1. `workspace/context/ctx_runtime.py` is **708 lines**, a second violation in the same
   package that this issue does not name. It must be included or explicitly scoped out.
2. `init(self, session_id: str, ai_agent: AgentBase)` carries a bare `AgentBase`
   annotation evaluated at class-definition time, and `AgentBase` is patched 51 times.
   The moved method must either stay in `base.py` or annotate through `_deps` with
   `from __future__ import annotations`.

Authorization was requested and the question timed out after 600 seconds with the default
"keep the issue open and move on". This is a timeout default, not approval. No code changed.
