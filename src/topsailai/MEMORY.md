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
