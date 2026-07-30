# Learn

## When user provides negative or corrective feedback, treat it as high-signal design constraints rather than just a code-location fix

In the auto session_name task, the user first rejected placing logic in session_manager/sql.py, then had to explicitly specify get_llm_chat(session_id="", need_stdout=False).

Lessons:
(1) proactively ask where business logic belongs when user rejects a layer;
(2) for LLM side effects that should not pollute session history or stdout, default to session_id="" and need_stdout=False without being told;
(3) negative feedback often reveals unstated architectural rules—extract and confirm them immediately.

## Capture the latency start timestamp before the operation whose overhead must be measured

When measuring first-byte latency for streaming LLM responses, the start timestamp must be captured **before** the request-creation call (`_create_with_first_byte_timeout()`), not after it. Capturing it after the request is created excludes the request-setup overhead and under-reports the true first-byte latency.

Lessons:
(1) define the measurement boundary explicitly: "first byte" should include everything from the caller's decision to start the request up to the first useful response chunk;
(2) place the start timestamp at the earliest point inside that boundary, immediately before any work that contributes to the latency;
(3) when a user reports a metric "looks wrong", verify the placement of the start and end timestamps before questioning the unit conversion or aggregation logic.

## Do not use assert for recoverable control flow that must cross a swallowing exception boundary

When `workspace/agent/agent_chat_base.py::HeavyTaskBase.block_heavy_task()` used `assert` to stop an overloaded task, the resulting `AssertionError` was swallowed by `ai_base/prompt_base.py::call_hooks_pre_chat()`, which catches all exceptions and only logs them. The agent's ReAct loop therefore never terminated, context summarization never ran, and `msg_count` grew without bound.

Lessons:
(1) Use a dedicated exception class (`HeavyTaskError`) for control-flow errors that must propagate through generic catch-all handlers;
(2) Generic hook callers should explicitly re-raise domain-specific exceptions rather than swallowing them;
(3) Any termination signal that crosses a layer boundary must be treated as part of the API contract, not as an internal invariant.

## Respect existing control flow and obtain explicit approval before behavioral changes

When implementing a display-only feature (cache hit rate), a previous change moved the summary block outside the `while` loop and deleted `self.last_message = answer`, altering behavior beyond the user's request and was committed without explicit approval. The user rejected it with "改动太多了".

Lessons:
1. A "small display change" must not silently restructure control flow or remove state mutations.
2. Before committing any change that affects when/how output is produced or mutates object state, obtain the user's explicit approval.
3. When the user says a change is too large, stop and revert to the minimal version rather than iterating on top of the rejected approach.

## Each layer's lifecycle must be self-contained: setup and teardown belong to the same layer

Commit `8a853e43b02b930d82746a06062d74d9033f5314` fixed a regression where the Agent2LLM message source was unset after the first turn and never re-established, causing subsequent turns to ignore injected messages. The deeper issue was a lifecycle boundary violation: User2Agent set up a per-conversation resource, but Agent2LLM's per-turn execution tore it down.

Background:
- `AgentChat._run()` in `workspace/agent/agent_shell_base.py` starts the User2Agent conversation loop and calls `self.call_hooks_pre_run()` **once** before the loop.
- That pre-run hook (`workspace/agent/hooks/pre_run_agent2llm_source.py`) registers the Agent2LLM message source via `set_agent2llm_message_source(source)`.
- Each User2Agent turn then calls `ai_agent.run()`, which executes `AgentBase.run()` in `ai_base/agent_base.py`.
- Inside `AgentBase.run()`, `_inject_runtime_messages()` calls `apply_agent2llm_message_source(self)`, which returns early if `get_agent2llm_message_source()` is `None`.

The bug:
- The old `AgentBase.run()` had `unset_agent2llm_message_source()` in its `finally` block.
- `AgentBase.run()` is a **per-turn** function; the message source was set up **once per conversation** by User2Agent.
- After the first turn completed, the per-turn `finally` cleared the per-conversation source.
- Because `call_hooks_pre_run()` is not invoked again for later turns, the source stayed `None`.
- From the second turn onward, any messages written to the Agent2LLM inject file were silently ignored.

The fix:
- Remove the premature `unset_agent2llm_message_source()` from `AgentBase.run()`.
- The source now survives for the entire User2Agent conversation.
- The file source itself clears consumed messages in `consume_messages()`, so there is no duplication or leak.
- The teardown, if needed, belongs in the User2Agent conversation loop's exit path — not inside a per-turn `finally` in Agent2LLM.

Lessons:
1. **A layer's lifecycle must be self-contained: setup and teardown must be paired in the same layer and at the same granularity.** User2Agent created the Agent2LLM message source once per conversation in its pre-run hook, so only User2Agent should destroy it, and only when the conversation ends.
2. **A per-turn function must not teardown a per-conversation resource.** `AgentBase.run()` runs once per User2Agent turn; its `finally` block is the wrong place to clean up state that outlives a single turn.
3. **If teardown is missing in the owning layer, add it there instead of borrowing another layer's cleanup.** The correct place to unset the message source is the User2Agent conversation loop's exit path, not `AgentBase.run()`.
4. **Always verify multi-turn behavior for features that inject or mutate Agent2LLM context,** because single-turn tests will not catch lifecycle mismatches.
