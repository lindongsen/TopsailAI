# Learn Of Project

Lessons the agent discovered while implementing, debugging, and testing this project.
Human-required rules and decisions live in [MEMORY.md](./MEMORY.md).

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

Pristine-worktree attribution is mandatory before calling a failure a regression:
run the same failing file with the same flags at the same HEAD in an isolated
worktree, force `PYTHONPATH` to its project and source roots, and print the
imported production module's `__file__` to prove it resolves inside that tree;
an editable installation can otherwise silently import the modified checkout.
Keep evidence under the workspace `.tmp`, record exact failures and per-run
results on both trees, then remove the owned worktree and log its removal.
Identical failures establish a pre-existing baseline; non-reproduction alone
establishes neither causation nor a confirmed root cause.

During native-SSE verification at `6fd1862eb163e1be95e0b4b8bb389efa8f45107d`,
`tests/bdd/test_instruction_message_integrity.py` (10 failures),
`tests/bdd/test_session_meta_name.py` (1 failure), and
`tests/bdd/test_session_name_startup_context.py` (2 failures) reproduced the same
failures at pristine HEAD and were classified PRE-EXISTING.
`test_raising_timeout_uses_injected_exception` passed three reruns on each tree;
the prior failure was classified FLAKY/transient, not established as caused by
SSE. Verified import isolation prevents false baseline comparisons, while
repeated runs prevent one transient result from being labelled a regression.

## Verify feature enablement and reachable execution paths before implementation, testing, or optimization

The native tool-call incident review initially treated tool-shaped messages appearing in a non-native request as evidence that non-native execution could produce them, but source tracing showed that only native mode creates new `tool_calls` and `tool_call_id` values; non-native mode can only replay structures inherited from earlier native history after persistence, restart, or a mode transition. This distinction also exposed that BDD scenarios running with native mode disabled were valid cross-mode compatibility tests but were not faithful reproductions of the original native incident.

Lessons:
1. Before developing a feature, write down its complete enablement predicate: configuration flags, model/provider capabilities, startup-time auto-detection, runtime overrides, and lifecycle transitions.
2. Separate producers from carriers and consumers. A structure observed on a path may have been inherited from an earlier enabled path rather than created under the current configuration.
3. Build a reachability matrix covering enabled, disabled, transition, persisted-history, and restart cases before selecting implementation points or test configurations.
4. Match at least one regression test to the exact production enablement state that caused the incident; label transition and compatibility scenarios separately instead of presenting them as faithful reproductions.
5. Before optimizing disabled-mode work, verify whether the boundary also protects data created while the feature was previously enabled; this prevents a locally reasonable gate from removing the final compatibility safeguard.
6. In this project, `build_parameters_for_chat()` in `ai_base/llm_control/base_class.py` must keep its request-boundary calls to `normalize_message_tool_calls` and `drop_orphaned_tool_messages` mode-independent: the earlier cleanup sites in `workspace/context/agent.py` and `ai_base/llm_hooks/hook_before_chat/tool_call_pairing.py` are already gated by `TOPSAILAI_USE_TOOL_CALLS`, so adding the same gate at the request boundary removes the final safeguard for inherited native history and reopens the provider 400 `No tool call found for function call output with call_id ...`.

## Abandoned User2Agent turns must bypass completion side effects and restore turn accounting

When `LLMBackToChatError` abandons a failed User2Agent turn, reading a replacement message is not sufficient: falling through normal completion handling can run success/final hooks, persist a fake answer, reset session state, or consume the finite-turn budget. Handle Back with explicit local state, invoke the failure hook once, normalize and revalidate fresh input, guard all completion-only effects, and restore `curr_count` before naturally starting the next iteration. This prevents old-message replay, false completion records, and premature finite-run termination without confusing Back with the request-level retry that remains inside `LLMModel.chat()`.

## A broad OpenAPI union does not prove each discriminated variant accepts every union member

The deployed JEV schema described `Question.criteria` as either an object or array for all question types, but live validation required score criteria to be an ordered array of 2–10 string, object, or array levels. The Tool incorrectly reused choice's object criteria rule for score, so locally accepted score requests always failed upstream.

Lessons:
1. When one schema field is shared by discriminated variants, verify each variant's semantic constraints instead of applying the broad union uniformly.
2. For a newly supported remote variant, pair contract inspection with one minimal live boundary probe when the published schema omits runtime validators.
3. Encode the confirmed variant-specific shape in the LLM-facing Tool contract and assert both local rejection boundaries and the exact HTTP wire payload so an apparently schema-valid but unusable request cannot regress.

## Cleanup retries must settle independent resources despite process uncertainty

Trigger: a cleanup-debt retry returned immediately when process inspection or termination failed, leaving owned channels open. Action: while holding the exact cleanup lease, capture the process outcome, always attempt channel closure, retain unresolved process debt, and propagate host interruption only after independent cleanup. This prevents one uncertain cleanup domain from leaking resources owned by another domain without weakening process-signal authorization.

## Exception aggregation must distinguish shared ancestry from cycles

In Hooks cleanup, independently raised failures can share an outer `__context__` or an existing cause descendant. Whole-graph intersection therefore cannot decide whether attaching a diagnostic is safe: preserve shared DAG ancestors, reject only the specific edge whose target can already reach its source, and retain an independent diagnostic through an acyclic aggregate at another attachment point instead of dropping it. Verify retention by exception-object identity plus recursion-stack cycle detection across causes, contexts, and exception-group members. This prevents legitimate cleanup diagnostics from being discarded while retaining the primary host interruption.

## Cleanup ownership must be armed before every fallible handoff and mutation

Trigger: U04 review found that temporary storage created before allocation completion, backend construction, or cleanup could lose its recovery owner, and that one successful debt retry could be mistaken for complete settlement.

Action: arm a stable cleanup debt before deletion, retain storage-only ownership before backend construction, preserve the primary interruption while attaching recovery authority, and report success only after every process, channel, and storage obligation is confirmed settled; treat confirmed path absence as idempotent cleanup and keep best-effort logging outside cleanup state transitions.

Why this prevents recurrence: every failure window retains an exact owner and tests cover partial allocation, handoff interruption, multiple debts, cleanup interruption, missing paths, and logging failure instead of validating only the normal cleanup path.

## Cooperative deadlines and security validation require checks at every authority boundary

Trigger: U07 review found that a late low-level I/O result could permit later non-cleanup I/O, malformed nested policy values could raise before stable error mapping, and interpreter validation did not fully repeat identity, metadata, named-path, and ancestry checks after reading.

Action: place cooperative checkpoints immediately before and after each relevant low-level operation and composite validation call; perform exact resource-free structural validation before locks or filesystem access; and route Python and shebang interpreters through one post-read revalidation path covering complete identity, security metadata, named path, and ancestors.

Why this prevents recurrence: every late result is observed before another non-cleanup side effect starts, malformed public inputs fail with stable tokens and zero I/O, and interpreter authority cannot survive byte, metadata, path, or ancestry replacement races.

## Nonretryable uncertainty must be enforced at every cleanup entry point

The artifact descriptor ledger originally rejected an uncertain close only during bulk cleanup, while direct `close()` and its `close_descriptor()` alias could re-enter first from the public exception handler and retry a historical descriptor integer. When an operation records an ambiguous outcome, every public and internal entry point capable of repeating that operation must reject the uncertain state before authority mutation or I/O; tests must cover each individual alias plus the real composed recovery order with actual identifier reuse, not only the final bulk-cleanup path. This prevents an earlier cleanup stage from bypassing a safeguard implemented only in a later stage.

## A per-file test runner must preserve both import roots, isolate temporary trees, and bound process concurrency

Trigger: the repository-mandated `tests/run_tests.py` passed focused tests but failed 25 files when each file ran from `tests/unit`, privilege-dropping children traversed a shared pytest temporary tree, and ten concurrent process-heavy files exhausted deadline budgets.

Action: construct each child `PYTHONPATH` from both the project root (for `tests.*`) and source root (for `topsailai`), assign each file a task-scoped basetemp below a minimally traversable `0755` root, and use bounded worker concurrency that the deadline-sensitive process tests can sustain.

Why this prevents recurrence: the runner now preserves isolated per-file imports, lets unprivileged children reach only their owned temporary hierarchy without widening source permissions, and avoids turning host contention into false deadline regressions.

## A shared test harness fixture change can break sibling tests that build their own synthetic fixture

When the LLM first-byte exhaustion harness's `expected_body` was corrected to include `parallel_tool_calls` (matching production `build_parameters_for_chat()`), a sibling unit test in `tests/unit/test_topsailai_u5_exhaustion_acceptance.py` that constructs its own synthetic request body and compares it against the same `expected_body` started failing. Per-file verification of the changed harness did not catch it; only the full runner did.

Lessons:
1. When changing a shared test fixture or expected-value constant, grep for every consumer that builds its own copy of that value, not just the harness that owns it.
2. Verify a shared-fixture change with the full suite (or at least every file that imports the fixture), because per-file verification only covers the owning harness.
3. Treat a new failure that appears after a test-infra fix as a coupling signal, not as an unrelated flake.

## A presentation update must be triggered where the value is produced, not only where it is consumed

Trigger: the terminal title kept showing `host:session_id` after the agent auto-generated a session name. Three defects combined: the title was refreshed at session start, before the asynchronous naming thread could produce a name; the end-of-turn refresh sat *after* `if reached_times_limit: break`, so every `times=1` entry never applied the name at all; and `_async_update_session_name()` never notified `terminal_title` when the name was actually stored.

Action: notify the presentation layer from the producer (`_refresh_terminal_title_after_rename()` right after a successful `update_session_name()`), move the consumer-side refresh before the loop-exit check, and add `force` plus `reset_terminal_title_cache()` so a cached title cannot suppress a later write after the terminal overwrote it on its own.

Why this prevents recurrence: a value produced asynchronously has two distinct moments — when it is stored and when it is displayed. Refreshing only at fixed checkpoints silently misses the value whenever the checkpoint precedes production, and a cache keyed on the rendered string then makes the miss permanent. Tests must assert the ordering (refresh happens before the exit check) and the producer-side notification, because a test that only checks "the title module works" passes while the title never updates.

## A prompt that no terminal can display must be echoed at the lowest shared layer

Trigger: with `TOPSAILAI_INPUT_PIPE_ENABLED=1` and stdin not a TTY, `input_from_pipe()` never spawned a terminal helper, so the prompt was never written anywhere. The session turn prompt, the project-workspace lock prompt, and the tool-approval prompt were all silently invisible, and the operator could only see the answer appear out of nowhere in the tee log.

Action: echo the prompt with a plain `print(prompt, flush=True)` in the `elif prompt:` branch of `input_from_pipe()` (after the helper-spawn block), and echo it in the `ask_decision` degradation guards after moving `_build_prompt()` above them. Never use `print_info()` for this: it routes through `print_with_time` and returns early when `env_tool.is_print_enabled()` is false, which is exactly the non-interactive case being fixed.

Why this prevents recurrence: fixing only `workspace/input_tool.py` would have left the lock and approval prompts invisible, because all three callers funnel through `utils/input_tool.input_from_pipe()`. The echo belongs at that shared layer so every caller inherits it, and the `print_info()` gate is the trap that makes an apparently correct fix produce no output at all.

## A control-plane handler must deliver intent, never block on a human answer

Trigger: the pause feature was first considered as a handler that waits for the operator's continue answer. The control transport requires a correlated response frame within a short default budget, the handler runs on the shared control thread, and the protocol has no channel to return a human answer, so a blocking handler would time out the CLI, starve `heartbeat` and `hard_interrupt`, and lose the answer.

Action: split delivery from execution. The handler atomically writes a session-scoped JSON marker and returns `pause_requested`; the agent main thread consumes the marker at a safe point and blocks on the existing runtime input channel. Keep the same contract as `hard_interrupt`: acceptance never means the agent has already reacted.

Why this prevents recurrence: any future control action that needs a human decision must follow the same two-stage shape, and the marker must carry the prompt, wait budget and timeout policy because those values cannot travel back through the response frame.

## A new session-scoped file must be registered in the ownership whitelist

Trigger: the pause marker `{session_id}.{pid}.session.agent2llm_pause.flag` would have been treated as malformed evidence by `context/session_activity.py::_OWNER_SUFFIXES`, making `can_clean()` return UNKNOWN and blocking session cleanup permanently.

Action: register every new `*.session.*` suffix in `_OWNER_SUFFIXES` in the same logical unit that introduces the file, and extend `workspace/agent_shell.py::_cleanup_stale_interrupt_flag` so a restarted process never inherits the leftover state.

Why this prevents recurrence: the whitelist is a regex of known suffixes, so an unregistered file is not merely ignored — it actively prevents cleanup of the whole session. Adding the file and its ownership registration together keeps the two lists from drifting.

## A step list must be normalized at the parse boundary, not skipped at each consumer

Trigger: the LLM answered with a JSON array of bare scalars, `["fix: wait for the channel before the first inventory publish"]`. `format_response_finally()` called `update_response_item(item)` on that `str`, raising `AttributeError: 'str' object has no attribute 'get'` and killing the whole User2Agent turn after the work was already finished.

Action: add `_normalize_response_items()` in `ai_base/llm_control/message.py` and call it at every exit of `format_response()` plus at the top of `format_response_finally()`, converting each non-dict item into `{"step_name": "thought", "raw_text": <text>}`. Keep a defensive `isinstance` guard in `update_response_item()` and in the single-element branch of `fix_llm_mistakes()`.

Why this prevents recurrence: the guard asymmetry was the real defect — the multi-element branch skipped non-dicts while the single-element branch did not, so the same malformed payload crashed or survived depending only on array length. Skipping is also the wrong repair: it moves the crash downstream into `pre_execute()` (`step["step_name"]` raises `TypeError`) and silently discards the model's text. Normalizing once at the parse boundary establishes the invariant "every step is a dict" for all consumers, and the negative control (removing the normalization re-introduces the original `AttributeError`) proves the tests actually guard it.

## A workspace value read at import time must be re-applied, not just assigned

Trigger: the session agent driver never exported the target session's `project_workspace` into its own process, so the analysis agent ran with an empty `TOPSAILAI_PROJECT_WORKSPACE`. Assigning the variable alone was still not enough: `topsailai/tools/skill_tool.py` calls `reload()` at module import time and scans `{TOPSAILAI_PROJECT_WORKSPACE}/.topsailai/skills`, and the driver imports `topsailai.workspace.agent_shell` at module level, which pulls that module in before any assignment can happen. A probe with a unique skill token showed `before set: False / after set no reload: False / after reload: True`.

Action: add `apply_project_workspace()` / `restore_project_workspace()` in `scripts/session_agent_driver/session_agent_driver.py`, resolve the workspace as stored session value -> `TOPSAILAI_PWD` -> `os.getcwd()`, write both `TOPSAILAI_PROJECT_WORKSPACE` and its `TOPSAILAI_PROJECT_FOLDER` alias, and call `topsailai.tools.skill_tool.reload()` only when the value actually changes. Apply it at driver startup and again before each analysis round, restoring the previous values on every exit path.

Why this prevents recurrence: any module that reads an environment variable at import time freezes that value for the process lifetime, so mutating the variable later silently leaves the derived state stale. The fix must pair the assignment with an explicit refresh of the derived state, and the refresh must be conditional so repeated rounds do not rescan the skill folders. A test that only asserts the variable value passes while the agent still sees the old skill prompt, so the test must observe the derived state, not just the variable.

## A default argument that reads the environment freezes the value at import time

Trigger: `tools/cmd_tool.py::exec_cmd` declared `cwd:str=EnvReaderInstance.project_folder`. Python evaluates default arguments once, when the `def` statement executes, so the folder was captured during `import topsailai.tools.cmd_tool` and never refreshed. A probe that set `TOPSAILAI_PROJECT_WORKSPACE=/tmp` after import still ran the command in the import-time folder. The same expression also produced `''` when all three source variables were unset, because `EnvironmentReader.get()` returns the `default` (`None`) only for a missing key while `project_folder` chains three `or` reads that end in `''`; `subprocess.Popen(cwd='')` raises `FileNotFoundError: [Errno 2] No such file or directory: ''`, whereas `cwd=None` legitimately inherits the process working directory.

Action: declare `cwd:str=None` and resolve inside the body with `if not cwd: cwd = EnvReaderInstance.project_folder or None`. The `or None` tail is required because the resolved folder can itself be empty. Cover the signature default, both empty spellings (`None` and `''`), the omitted argument, a post-import folder change, an empty resolved folder, and an explicit value that must win.

Why this prevents recurrence: a default argument is evaluated at definition time, so any environment read placed there silently becomes a process-lifetime constant and no later configuration change can reach it. `if not cwd` alone is also insufficient when the fallback source can return `''`, because the guard re-assigns the same fatal empty string. The negative control matters here: reverting only the signature and the body guard made 4 of the 6 new tests fail, which proves they observe the resolution behavior rather than merely the parameter name.

## A bare `git commit` commits the whole index, so staged foreign work gets swept in

Trigger: `git add <4 own paths>` followed by a bare `git commit -m "..."` produced commit `c8e93276` containing 6 unrelated `topsailai_connector` files that another agent had already staged. The intent was to commit only the 4 file-tool files, and `git add` did limit what was newly staged, but `git commit` without a pathspec commits every entry already in the index.

Action: always commit with an explicit pathspec, `git commit -m "<message>" -- <path1> <path2>`, and note that `-m` must precede `--` because everything after `--` is parsed as a path. Verify immediately with `git show --name-only --format="" HEAD` and assert the file list matches the intended set exactly.

Why this prevents recurrence: in a workspace shared by several agents, the index is shared mutable state that any agent can populate at any time, so "I only added my files" is not evidence that "only my files will be committed". The pathspec form makes the commit's file set explicit and independent of what else happens to be staged. A post-commit `--name-only` check is the only reliable proof, because the commit succeeds silently either way and the contamination is invisible in the message.
