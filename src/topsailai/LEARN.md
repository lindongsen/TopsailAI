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
