---
maintainer: AI
author: DawsonLin
---
# Plan task message inspection retains the subagent target

Status: resolved in the working tree; nested ownership repair verified with the unchanged real CLI SSE-mock BDD.

## Reproduction

Run tests/bdd/test_two_layer_message_verification.py. The two direct-turn scenarios pass. The delegation scenario performs two actual subagent calls through the real plan_tasks CLI, then inspects /agent.messages and /ctx.history.

## Evidence and impact

Persisted history has the expected four-message groups: user manager task, user dispatch, assistant member result, assistant manager final. However /agent.messages exposes member runtime messages and omits MANAGER_REPLY_1. The manager inspection command therefore reports the wrong agent after delegation. Focused regression: one failure and two deselected in 9.28 seconds; preceding complete focused run: two passed and one failed in 25.64 seconds.

## Confirmed root cause

workspace/plugin_instruction/agent.py get_messages calls base.cache.get_ai_agent. workspace/plugin_instruction/base/cache.py stores one process-global g_ai_agent. workspace/agent/agent_chat_base.py constructor calls set_ai_agent(self.ai_agent). tools/subagent_tool.py creates a nested AgentChat during delegation, replacing that cache without restoring the outer manager on return.

## Acceptance for a separate repair

Bind inspection to the owning interactive AgentChat or restore the correct owner across nested lifecycle boundaries. Preserve standalone member inspection. Run the current delegation regression without xfail or weakened assertions and add focused nested-owner tests. Do not hide this failure as an availability skip.

## Step 4 verification

Mock BDD rerun: 2 passed and 1 failed in 22.67 seconds, exit status 1. The delegation assertion still lacks MANAGER_REPLY_1 in the runtime report and instead contains MEMBER_REPLY_1. Evidence: .tmp/regression-step4/focused.log and focused.xml. No production repair or weakened assertion applied.

## Nested ownership repair verification

Instruction inspection now uses a context-local execution owner bound at AgentChat._run, including the subagent tool's direct _run call. Constructor registration retains the standalone fallback but cannot replace it during an active execution. Exact token reset in finally restores the parent after normal return, ordinary errors, KeyboardInterrupt, and SystemExit.

Focused ownership tests: 8 passed in 12.55 seconds; cache statement and branch coverage: 100 percent. Unchanged two-layer real-tmux SSE-mock BDD: 3 passed in 38.10 seconds, including both actual delegations and manager inspection. Seven affected existing unit files: 175 passed. Original ai_team mock baseline: 68 passed in 23.84 seconds. All test invocations exited 0. Evidence: .tmp/nested-instruction-owner/ownership.log, coverage.json, bdd.log, bdd.xml, per-file unit logs/XML, and team.log/team.xml. No scenario-owned tmux sessions remain. No live requests or quota bypasses were made. Existing broad-suite failures from Step 4 remain separate and were not repaired or rerun by this unit.
