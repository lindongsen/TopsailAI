# Learn & Memory Of Project

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

## A value containing embedded line breaks is not a scalar for display purposes

When adding pretty-printed rendering for tool-approval arguments, the first implementation
classified only containers (dict/list/tuple/set) as "block" values and inlined everything
else. Multi-line strings therefore still rendered as a single line with literal `\n`
escapes, which was exactly the complaint the change was meant to fix.

Lessons:
(1) "Is this value block-formatted?" must be decided by how it will read on screen, not by
its Python type — a `str` containing `\n` or `\r` must be emitted as an indented block;
(2) introduce one predicate for that decision and use it at every value call site,
otherwise sibling code paths (dict values, list items, top-level keys) disagree;
(3) a rendering feature needs at least one test whose fixture actually contains an
embedded newline, otherwise the tests pass while the reported symptom survives.

## Configuration that originates as JSON may arrive as a mapping, not a dataclass

Approval rules are parsed from JSON, so a renderer that displays "which rule matched"
cannot assume attribute access. Reading `rule.name` alone silently produces empty output
for dict-shaped rules.

Lessons:
(1) when formatting data that crossed a JSON/deserialization boundary, read fields through
a helper that handles both mappings and objects;
(2) add a test that passes a plain dict rule, because that is the real production shape;
(3) prefer returning structured match results (which condition matched, its operator,
expected and actual value) over a bare boolean, so downstream layers can explain the
decision instead of re-deriving it.

## An autouse timeout fixture equal to a test's sleep turns the test into a coin flip

`tests/unit/conftest.py` sets `TOPSAILAI_TOOL_APPROVAL_DEFAULT_TIMEOUT=0.05` for speed,
while the approval integration test sleeps `0.05` before approving. The wait budget and the
approval delay are identical, so the result depends only on thread scheduling.

Lessons:
(1) when a test fails intermittently, compare its own timing constants against global
autouse fixtures before suspecting the new code;
(2) before reporting a failure as a regression, reproduce it at pristine `HEAD` in an
isolated `git worktree` — that converts a suspicion into evidence;
(3) never express a wait budget and the event that must arrive inside it as the same
constant; drive the event with a `threading.Event` instead of a fixed sleep.

## A human-facing "explain the decision" block should start minimal, not grow

The approval-prompt focus block was implemented with a heading plus a per-condition
breakdown, then had to be simplified twice on user feedback: first the labels, then the
heading and the whole condition list were removed, leaving only `Rule:` and `Pattern:`.
The verbose version was rejected as noise because the full arguments are already shown
right below it.

Lessons:
(1) for a prompt a human reads under time pressure, default to the minimum that answers
"why am I being asked this?" and let the existing detail sections carry the rest; do not
restate data the reader can already see;
(2) when a rendering layer is simplified, delete the now-unreachable helpers and branches
instead of leaving dead code, but keep the underlying data pipeline (structured match
results) so other consumers such as CLI tooling and audit logs can still use it;
(3) encode rejected verbosity as negative assertions (`"Trigger" not in text`) so a future
"improvement" cannot silently reintroduce it.

## Features tightly coupled to the LLM must be covered by BDD tests

Any capability whose behavior depends closely on the LLM (prompt construction, message injection, tool-call/ReAct loop, streaming, approval decisions driven by model output, session/context handling) MUST have BDD (Gherkin) tests under `tests/bdd/` that express the user-visible behavior, in addition to unit tests.


## Verify feature enablement and reachable execution paths before implementation, testing, or optimization

The native tool-call incident review initially treated tool-shaped messages appearing in a non-native request as evidence that non-native execution could produce them, but source tracing showed that only native mode creates new `tool_calls` and `tool_call_id` values; non-native mode can only replay structures inherited from earlier native history after persistence, restart, or a mode transition. This distinction also exposed that BDD scenarios running with native mode disabled were valid cross-mode compatibility tests but were not faithful reproductions of the original native incident.

Lessons:
1. Before developing a feature, write down its complete enablement predicate: configuration flags, model/provider capabilities, startup-time auto-detection, runtime overrides, and lifecycle transitions.
2. Separate producers from carriers and consumers. A structure observed on a path may have been inherited from an earlier enabled path rather than created under the current configuration.
3. Build a reachability matrix covering enabled, disabled, transition, persisted-history, and restart cases before selecting implementation points or test configurations.
4. Match at least one regression test to the exact production enablement state that caused the incident; label transition and compatibility scenarios separately instead of presenting them as faithful reproductions.
5. Before optimizing disabled-mode work, verify whether the boundary also protects data created while the feature was previously enabled; this prevents a locally reasonable gate from removing the final compatibility safeguard.
6. In this project, `build_parameters_for_chat()` in `ai_base/llm_control/base_class.py` must keep its request-boundary calls to `normalize_message_tool_calls` and `drop_orphaned_tool_messages` mode-independent: the earlier cleanup sites in `workspace/context/agent.py` and `ai_base/llm_hooks/hook_before_chat/tool_call_pairing.py` are already gated by `TOPSAILAI_USE_TOOL_CALLS`, so adding the same gate at the request boundary removes the final safeguard for inherited native history and reopens the provider 400 `No tool call found for function call output with call_id ...`.

## Keep utility-layer classes free of business-layer dependencies

When the LLM request-statistics feature caused `utils.StateVisualizer` to import, instantiate, and invoke `context.LLMRequestStat`, the trigger was a review request to keep utility methods generic. The correction moved statistics coordination into `context.LLMStateVisualizer`, a subclass of the generic utility visualizer, and moved the LLM model-specific decorator into the context layer. This prevents recurrence by requiring dependency direction to remain business/context to utility and by keeping both runtime dependencies and examples in utility modules free of domain-specific concepts.

