# Memory Of Project

Rules, constraints, and decisions the human explicitly required or approved.
Agent-discovered technical lessons live in [LEARN.md](./LEARN.md).

## Respect existing control flow and obtain explicit approval before behavioral changes

When implementing a display-only feature (cache hit rate), a previous change moved the summary block outside the `while` loop and deleted `self.last_message = answer`, altering behavior beyond the user's request and was committed without explicit approval. The user rejected it with "改动太多了".

Lessons:
1. A "small display change" must not silently restructure control flow or remove state mutations.
2. Before committing any change that affects when/how output is produced or mutates object state, obtain the user's explicit approval.
3. When the user says a change is too large, stop and revert to the minimal version rather than iterating on top of the rejected approach.

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

## Keep utility-layer classes free of business-layer dependencies

When the LLM request-statistics feature caused `utils.StateVisualizer` to import, instantiate, and invoke `context.LLMRequestStat`, the trigger was a review request to keep utility methods generic. The correction moved statistics coordination into `context.LLMStateVisualizer`, a subclass of the generic utility visualizer, and moved the LLM model-specific decorator into the context layer. This prevents recurrence by requiring dependency direction to remain business/context to utility and by keeping both runtime dependencies and examples in utility modules free of domain-specific concepts.

## Retry policy implementations must use the approved explicit status allowlist

During JEV client review, treating every HTTP 5xx response as retryable conflicted with the approved policy that permits retries only for transport failures and HTTP 408, 429, 502, 503, and 504. Implement retryability from one explicit allowlist shared by response mapping and tests, and add a negative regression for an unlisted status such as HTTP 500; this prevents broad status families from silently consuming extra requests and service capacity.

## Hook configuration convenience must preserve the Human-approved execution architecture

Trigger: the request to simplify Hook-name plus scripts/folder configuration was misinterpreted as permission to introduce a standalone scripts-only registration path, and compliance was assessed against documents rewritten to match that path. Action: restore the Human's per-Hook-Point Module/default-terminal-Hook model, `main(*args, **kwargs)` entry and both name-order contracts in the design/API, and track the actual Runtime divergence separately. U06A–U06D subsequently connected unified synchronous execution, the configured adapter (`17d9e9ac`) and ordinary registration/dispatch (`14d61522`); lifecycle and migration acceptance remains in U07–U11. Prevention: compare convenience-layer proposals and runtime call graphs against the original architectural invariants and decision history before updating documents or claiming compliance; tests of isolated planners and separate Script APIs cannot prove one unified end-to-end plan.

## Hook Point wrappers require explicit Human approval before implementation

Trigger: an implementer added an `observe_*` wrapper (`observe_tool_execute`) around Hook Points without Human approval, despite the earlier rejection of `observe_before_input` and the documented direct-call architecture; the Human explicitly expressed dissatisfaction.

Action: call the named Hook Point function directly, keep payload builders data-only and never dispatch Hooks from them, and obtain explicit Human approval before adding any wrapper, adapter, or indirection. Do not reinterpret implementation convenience as authorization.

Why this prevents recurrence: the mandatory rule and Human decision provenance are now explicit in `features/feature-unified-hooks-design.md` and `docs/Hooks_API.md`, so future implementers cannot claim the constraint was undocumented or infer permission from historical adapter descriptions.

## Minor behavior additions belong only in source code and unit tests

Trigger: after implementing the Agent2LLM injection log, an "Injection Log" section was added to `MEMO.AgentCore.md` and a behavior bullet was added to `docs/Environment_Variables.md`. The Human rejected both: "这种功能就不用记到 MEMO 里面了" and "docs/Environment_Variables.md 这里也不需要，环境变量只需要关注自身的功能、运行机制就可以了".

Action: keep a small behavior addition in the source code and its unit tests only. Do not add a new section to `MEMO.md` / `MEMO.*.md` for a minor feature, log format, or display tweak, and do not add feature-behavior notes to `docs/Environment_Variables.md` — that document describes only each variable's own purpose, default, valid values, and runtime mechanism.

Additional constraint stated by the Human on 2026-11-10: "不要有代码，也不要阐述太多实现细节和设计细节". `docs/Environment_Variables.md` MUST NOT contain code blocks, shell examples, source file paths, function or class names, internal error codes, or implementation narratives. Describe only what the variable does, its default, its valid values, and the observable behavior it controls.

Why this prevents recurrence: MEMO documents are injected into the agent context and are meant for architecture-level conclusions and pitfalls, so recording every small feature there dilutes the signal and costs tokens on every turn. The environment-variable reference is a configuration contract, not a changelog, so feature behavior written there goes stale and misleads readers looking for how a variable works. Implementation detail in that document also rots fastest, because internal names change while the variable contract does not. Reserve MEMO entries for structural decisions, cross-module contracts, and non-obvious traps.


## Runtime Data must remain Agent-scoped, extensible, bounded, and separate from conversation context

Trigger: the Human approved a general Runtime Data mechanism while requesting an LLM fault-retry marker, a threshold that activates when failed attempts reach 3, removal when that request ends, bounded history, read-only Instruction exposure, and documentation in MEMO and project memory.

Action: keep one lease-protected Runtime Data Store under each `AgentRuntime`; producers publish namespaced operational states, active state is settled on operation exit, and retained history has a fixed maximum count. Runtime Data must not enter `ContextRuntimeData`, User2Agent or Agent2LLM messages, session persistence, or summaries. `/runtime`, `/runtime.get`, and `/runtime.history` are inspection-only and expose public bounded fields rather than raw payloads or ownership data.

Why this prevents recurrence: Agent isolation and generation leases stop one request from overwriting or clearing another, bounded retention prevents memory growth, and separating operational state from conversation data prevents observability metadata from changing prompts, persisted sessions, or summarization behavior.

## The `topsailai` CLI must never query the database directly

Trigger: the Human required that the `topsailai` command (`topsailai_cli.py`) never queries the database on its own initiative, and that every piece of information it needs is obtained by invoking a command line.

Action: `topsailai_cli.py` and the `cli_topsailai/` package it dispatches into MUST NOT import or call `SessionSQLAlchemy`, `ctx_manager.get_session_manager`, or any other storage client, and MUST NOT open `memory.db` or any other database file. Session, task, model and history information is obtained by running the dedicated query command and parsing its `--json` output, for example `topsailai_session_info --json <session_id>` or `topsailai_sessions_info --json <id>...`. The query commands themselves (`topsailai_session_info.py`, `topsailai_sessions_info.py`, `ai_list_sessions.py`, `ai_retrieve_messages.py`, `ai_clean_sessions.py`, `ai_stream_sessions.py`) remain the only components that read storage, because reading storage is their entire purpose.

Why this prevents recurrence: the interactive CLI is a navigation and control surface, not a data-access layer. Letting it open the database directly duplicates the storage schema in a second place, makes the CLI depend on a connection string that resolves against the process working directory, and lets a display path silently create an empty database. Routing every read through the query command keeps one storage contract, keeps the CLI free of schema knowledge, and makes the JSON output the single machine-readable interface.

## Out-of-scope commits are recorded, not reverted, when the code itself is correct

Trigger: session `wa-bbe51ff8246b` declared `/TopsailAI/src/topsailai/cli` as its workspace, but four of its commits (`dd399ebc`, `b0f69781`, `feedbbca`, `8088a60c`) also changed agent-core files under `workspace/` and `tests/unit/`. The Human reviewed the situation and decided: keep the current state, do not revert.

Action: when a commit exceeds its declared workspace but the resulting code is verified correct, record the scope violation and leave history untouched. Do not rewrite history, do not revert, and do not treat the violation as authorization to keep crossing the boundary in future work. `git reset` remains prohibited.

Why this prevents recurrence: the boundary violation and the code correctness are separate findings. Reverting correct code to punish a process mistake destroys working behavior, while silently ignoring the violation teaches that the boundary is optional. Recording it keeps both facts visible: the code stays, and the next session is expected to stay inside its own workspace.

## Abnormal exits must preserve the on-disk scene instead of rewriting state

Trigger: the non-interactive database I/O fallback called `update_session_meta_status("error", session_id)` before `os._exit(1)`. The Human rejected it: "兜底逻辑为什么还要去设置meta里面的状态？" and required that an abnormal exit preserve the scene, keep the meta file, and keep the stdout file, without deliberately modifying files.

Action: a last-resort abnormal exit MUST NOT write, rewrite, or delete any state file. `os._exit` is an abnormal termination, so the recorded state is the evidence: `status: running` with `end_ts: null` proves the process died without finalizing, and rewriting it to `error` fabricates a finalized record and erases that proof. Flushing `sys.stdout` / `sys.stderr` before exiting is allowed and required, because flushing only delivers bytes already produced and never invents state. Remove the session identity from the fallback signature so the contract is structural rather than a convention, and assert `update_session_meta_status` is never called in both unit and BDD tests.

Why this prevents recurrence: an abnormal exit is a fault, and a fault must leave its own trace. Writing a tidy `error` status makes a crash indistinguishable from a handled failure, destroys the only signal that the process skipped its finalization path, and hides the same defect class that produced the stale `running` sessions. Flushing keeps the stdout artifact truthful up to the exit instant, while rewriting metadata turns the record into a claim about what the program intended rather than a record of what happened.
