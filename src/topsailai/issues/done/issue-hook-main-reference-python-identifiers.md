---
maintainer: AI
author: DawsonLin
status: resolved
---
# Unified Module reference identifier validation mismatch

## Evidence and impact

U01 commit 4926a68b16282c391b9d2c89dba2121ce1e4fb05 adds an ASCII-leading/Unicode-word regex in hooks/hook_script.py::_validate_plan_inputs. The exact regex rejects valid Python identifier components 插件, éclair and a followed by U+0301, and accepts a², which fails str.isidentifier(). Module discovery uses isidentifier in hooks/module_discovery.py:642. Valid discovered names can therefore fail the unified builder metadata gate. No plugin import is needed to reproduce this grammar disagreement.

## Root cause and detection gap

The regex mixes ASCII-leading restrictions with Unicode word characters instead of Python identifier semantics. Existing U01 acceptance tests use only ASCII references; full branch coverage does not cover identifier-domain partitions.

## Correction and acceptance

Use exact module:main structure and nonempty dotted Python identifier components in the unified builder only. Do not normalize names, import plugins, change global Binding validation, or broaden into U02. Add direct/bridge RED cases for Unicode-leading and combining identifiers, plus malformed components including a²; preserve registered aliases, atomic rejection, input immutability and prior error precedence. Run the four focused U01 guard files and scoped coverage, then review/commit the correction as a separate unit. This historical correction gate was satisfied before U02 approval.

## Resolution evidence

Resolved by `924566a6c90b3e5e9a4699a36ee126f7aed7b287` and its independent U01R approval: exact `module:main`, per-dotted-component `isidentifier()`, no normalization, plugin import or global Binding change. Focused regression/coverage and post-commit review are recorded in the [implementation plan](../../.task/plan_20261010T101643_unified-hooks-contract-repair.md). U02 subsequently committed and was approved; this issue is fully resolved.
