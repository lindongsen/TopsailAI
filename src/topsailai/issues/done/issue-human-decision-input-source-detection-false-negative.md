---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Human decision reports false input-source unavailability for malformed native tool arguments

## Status

Confirmed. The observed team-manager incident is not a false negative from `_has_usable_input_source()`. It is an argument-validation failure incorrectly classified as input-channel unavailability.

## Trigger

During a live top-level team-manager session on 2026-08-27, the human could send normal conversation messages, but `human_tool-ask_decision` immediately returned:

- `status: unavailable`
- `answer`: the caller-provided default
- `option_index: -1`
- `elapsed: 0`

The apparent contradiction suggested that input-source detection had rejected a usable session channel.

## Evidence

The authoritative event record is:

`/root/.topsailai/workspace/task/20260827T163051.2229768.session.events`

Two live native calls reached `human_tool-ask_decision` with malformed argument types.

The first `llm.response.raw` event at `2026-08-27T16:56:20.075479+08:00` contains:

- `question`: a valid non-empty string;
- `options`: a JSON-looking string instead of a list;
- `allow_free_text`: the string `"True"` instead of a boolean.

A second call was intended by the manager to pass a real list, boolean, and number. However, the authoritative events at `2026-08-27T17:09:59` prove that the provider's original native tool call and the subsequent `tool_call.start` both contained:

- `options`: a string containing the four-item JSON array, not `list[str]`;
- `allow_free_text`: the string `"True"`, not `bool`;
- `timeout_seconds`: the string `"300"`, not a number.

The second `tool_call.end` occurred after approximately `0.037` milliseconds and returned `status="unavailable"`, `elapsed=0`, and the caller-provided default. The manager's statement that the retry used correct runtime types was therefore an intention, not the value received by the tool boundary.

In `tools/human_tool.py::ask_decision`, the relevant evaluation order is:

- lines 266–267 validate `question`;
- lines 269–271 return `unavailable` when `options` is not a list;
- lines 281–284 check nested-agent depth;
- lines 287–290 resolve and check input sources.

Both calls returned at lines 269–271. Neither call executed `_is_sub_agent_context()`, `_resolve_input_funcs()`, or `_has_usable_input_source()`, and neither attempted an input read. These incidents therefore do not establish a P3 nested-agent false positive or a P4 input-source false negative.

The native execution path preserves the provider-produced nested types:

- `ai_base/tool_call.py::get_tool_call_info()` lines 130–145 parses the outer arguments JSON without coercing nested values to function annotations;
- `ai_base/agent_types/tool.py::StepCallTool.execute_step_action()` forwards `func_args` to `exec_tool_func()`;
- `ai_base/agent_types/tool.py::exec_tool_func()` lines 169–172 invokes `tool_func(**args)` directly.

The framework did not transform a list or boolean into strings after parsing: the strings are already present in the provider's `llm.response.raw` payload. This evidence does not justify a separate general framework-stringification issue.

`tools/human_tool.py` exports `TOOLS` at lines 426–428 but does not export `TOOLS_INFO`. Consequently, `tools/base/common.py::generate_tool_info()` lines 108–119 emits only an object schema with no properties, required fields, or parameter types. The provider has no native schema requiring `options` to be an array, `allow_free_text` to be a boolean, or `timeout_seconds` to be numeric.

The team-manager input path is demonstrably available independently of these malformed calls:

- `cli/ai_team.py::main()` constructs one `AgentChat` and calls `agent_chat.run()`;
- `workspace/agent/agent_shell_base.py::AgentChat._run()` calls `call_hooks_pre_run()` at line 279 before entering the conversation loop;
- `workspace/agent/hooks/pre_run_input.py::pre_run_set_agent_runtime_input()` lines 22–76 has no registration guard based on interactive mode, pipe enablement, or TTY and always installs both runtime input callbacks;
- the live session metadata names `20260827T163051.2229768.session.pipe` and records `TOPSAILAI_INPUT_PIPE_ENABLED: true`, while the pipe exists and ordinary human turns succeed;
- the live manager process has `TOPSAILAI_INTERACTIVE_MODE=1`.

Because P2 short-circuited both calls, the actual manager-thread values of `KEY_AGENT_DEEP` and the registered runtime-input callbacks were not observed by `ask_decision` during either incident. Static control flow suggests a top-level depth of 1 and same-thread execution, but that is not needed to explain these results and must not be presented as runtime proof.

## Root cause

The immediate root cause is semantic misclassification in `tools/human_tool.py::ask_decision`: invalid request arguments and genuine channel unavailability both return the same `unavailable` status.

The upstream contributing cause is the absence of a complete native tool schema for `ask_decision`, allowing the provider/model to emit stringified list, boolean, and numeric arguments.

The live manager did use native tool calls. Although `env_template` defaults `TOPSAILAI_USE_TOOL_CALLS=0`, `/root/.topsailai/.env.local` sets it to `1`; `topsailai.__init__::__load_env()` loads `.env.local` before `.env`, and dotenv does not override the first value by default. Runtime stdout records ten `[effective_tools]`, and the authoritative event contains native `tool_calls`. Reading `/proc/<pid>/environ` alone cannot reveal environment values added inside Python by dotenv, so its unset value is not evidence that native calls were disabled.

## Impact

- A valid human input channel is falsely reported as unavailable even though channel detection never ran.
- The caller consumes the default answer as if infrastructure were unavailable.
- Operators and agents are directed toward TTY, pipe, sub-agent, and timeout investigation instead of the malformed request.
- Dynamically hiding the tool based on this ambiguous result would create a more severe silent failure by removing a usable human-decision capability.
- If `options` were valid or omitted, `allow_free_text="True"` would be treated as truthy instead of rejected as an invalid boolean.
- If P2 did not return first, `timeout_seconds="300"` would reach the numeric comparison at line 277 and raise `TypeError` instead of producing a structured degradation result.

## Test gap

`tests/unit/test_topsailai_tools_human_tool.py` tests malformed `options` and expects `unavailable`, thereby preserving the misleading status contract. Separate tests mock input availability, but there is no regression case covering a real native tool call in a top-level team-manager session with pipe-backed input and correctly typed arguments.

## Proposed minimal correction

- Add explicit `TOOLS_INFO` for `human_tool-ask_decision`, including:
  - non-empty string `question`;
  - array-of-strings `options` or null;
  - boolean `allow_free_text` or null;
  - numeric `timeout_seconds` or null;
  - string `default` or null.
- Classify malformed arguments as `invalid_request` with a machine-readable reason, or raise a dedicated argument error at the invocation boundary.
- Validate every parameter type before numeric comparisons or truth-value use, including `allow_free_text`, `timeout_seconds`, and `default`.
- Reserve `unavailable` for genuine nested-agent or no-input-source conditions.
- Add native-call and team-manager regression coverage proving that typed arguments reach the registered runtime input function.
- Retain `_has_usable_input_source()` as a fallback runtime check; do not infer channel absence from malformed arguments.

## Prevention

Trigger: any human-decision call returns `unavailable` while ordinary session input remains operational.

Action: inspect the recorded native tool arguments and identify which early-return branch executed before investigating TTY or pipe state; enforce argument types through explicit tool schemas and distinct validation statuses.

Why this prevents recurrence: it separates request-contract failures from transport availability failures, preserving accurate diagnostics and preventing usable tools from being hidden because of malformed model output.

## Relationship to the conditional-registration proposal

The proposal in `.tmp/plan_20260827T163100_human-tool-conditional-registration.md` must not use this incident as evidence that the session lacked an input channel. Implementing automatic hiding from the current ambiguous `unavailable` result would turn a visible argument-schema defect into silent capability loss. Conditional registration should be reconsidered only after argument validation and genuine channel detection produce distinct outcomes.

## Resolution

Resolved on 2026-08-27.

`tools/human_tool.py` now publishes a complete native `TOOLS_INFO` schema, validates all request arguments before comparisons or truth-value use, and returns `status="invalid_request"` with a machine-readable `reason` for malformed requests. `status="unavailable"` is now reserved for nested-agent and genuinely absent-input-source conditions.

`tests/unit/test_topsailai_tools_human_tool.py` now covers schema types, invalid questions, invalid option containers and elements, string and boolean timeout values, string boolean values, invalid defaults, genuine unavailable paths, and runtime input availability without a TTY.

Verification results:

- Focused human-tool tests: 57 passed.
- Related tool infrastructure tests, executed as separate files to preserve process isolation: 30 passed, 37 passed, and 16 passed.
- A combined related-test invocation produced 3 failures because `test_topsailai_tools_base_init.py` mutates imported tool registry state before `test_topsailai_tools_base.py`; every affected file passes independently, showing a pre-existing cross-file test isolation issue rather than a product regression.

Full project unit regression was also executed through `tests/run_tests.py` as required by `project.yaml`: 202 test files passed, 0 failed, in 104.413 seconds. The structured report is stored at `.tmp/test_results.txt`.

## Follow-up: model-compatible scalar normalization

On 2026-08-27, the human explicitly reversed the original strict scalar-type policy after noting that models may emit numeric and boolean-like arguments as strings. The native schema now presents `allow_free_text` as a string-or-null field, while the runtime remains backward compatible with Python booleans. Recognized truthy and falsy strings are normalized before use; empty values use the environment default; unknown values remain `invalid_request`.

`timeout_seconds` continues to advertise a numeric schema but now actively parses finite numeric strings, including decimal and scientific notation. Empty, nonnumeric, boolean, NaN, and infinite values remain `invalid_request`; zero and negative values preserve the existing infinite-wait behavior. This D4-to-N1/N2 policy reversal is intentional and scoped to `human_tool.ask_decision`, not a framework-wide coercion rule.

Verification after the follow-up: focused human-tool tests passed with 62 tests. Related and full-suite results are recorded in the implementation report for this follow-up.

## Follow-up: integer free-text flag (final policy)

On 2026-08-27 the human simplified the follow-up policy again: `allow_free_text` is an integer flag (`1` = true, `0` = false), and a string value is converted with `int()`. The previously implemented truthy/falsy string vocabulary (`true`/`yes`/`on`/`no`/`off`) was removed as unnecessary complexity.

Policy evolution for these two scalar arguments:

| Stage | `allow_free_text` | `timeout_seconds` |
|-------|-------------------|-------------------|
| D4 (initial fix) | strict types; any string rejected | strict types; any string rejected |
| N1/N2 (first follow-up) | schema `string`, truthy/falsy vocabulary | finite numeric strings parsed |
| Final (this change) | schema `integer`; `int()` conversion for strings | finite numeric strings parsed (unchanged) |

Final accepted and rejected values:

| Argument | Schema | Accepted | Rejected (`reason`) |
|----------|--------|----------|---------------------|
| `allow_free_text` | `integer` or `null` | `1`, `2`, `0`, `"1"`, `"0"`, `" 1 "`, `"00"`, Python `True`/`False`; `None`/blank uses the environment default | `"maybe"`, `"true"`, `"yes"`, `"1.3"`, `1.0`, `0.0`, containers (`invalid_allow_free_text`) |
| `timeout_seconds` | `number` or `null` | `1.3`, `"1.3"`, `"300"`, `" 42 "`, `"1e2"`; `0`/negative = infinite wait | `"abc"`, `""`, `NaN`, `±inf`, Python `True`/`False` (`invalid_timeout_seconds`) |

The environment default path is intentionally unchanged: `TOPSAILAI_HUMAN_DECISION_ALLOW_FREE_TEXT` is still resolved through `env_tool.is_true()`, so it keeps accepting `1`/`true`/`yes`/`on`. The parameter contract is integer-only while the environment contract keeps the project-wide boolean convention.

No helper was reused for the conversion. `utils/format_tool.py::to_int()` also converts floats (so `1.0` would be silently accepted), `utils/env_tool.py::get_int()` reads environment variables only, and `env_tool.is_true()` implements the rejected truthy vocabulary. The conversion therefore stays a private function in `tools/human_tool.py`.

Verification after this change: focused human-tool tests 63 passed; related infrastructure files in separate processes 30, 37, and 16 passed.
