---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: proposed
---

# JEV Decision Tool Design

## Scope

Design only. This proposal defines a read-only decision tool backed by the deployed TypeSafe JEV-compatible `POST /v1/systemone` API. It does not implement source code, modify environment-variable files, or call the live evaluation endpoint.

## Research findings

Sources reviewed:

- Deployed service OpenAPI: `http://139.198.176.112:30622/openapi.json`, retrieved on 2026-09-21.
- Deployed interactive documentation: `http://139.198.176.112:30622/docs`.
- Public compatible implementation: `exfly/laya-jev-compatible-server`, including its `README.md` and `docs/server.md`.
- TypeSafe SDK documentation linked by that implementation: `https://docs.typesafe.ai/sdk/python`.
- This repository's tool registration and runtime-context code.

The deployed service accepts one `state` plus one to 32 named typed questions and returns named structured answers. `state` may be a string, object, or array. Each question requires `type` and `instructions`; unknown fields are rejected. The deployed OpenAPI is authoritative where it differs from a compatible implementation's prose documentation.

Supported decision types:

| Type | Intended use | Required request fields | Response |
|---|---|---|---|
| `noul` | Binary semantic judgement such as yes/no | `type`, `instructions`; no criteria needed | `type`, numeric `noul` |
| `choice` | Select one option | `type`, `instructions`, option criteria | `type`, selected `choice`, `confidence`, per-option `probabilities` |
| `score` | Place input on an ordered semantic scale | `type`, `instructions`, ordered criteria/legend | `type`, numeric `score`, `legend`, `confidence`, `probabilities` |

`noul` is a numeric decision value, not a JSON boolean. The tool must preserve this raw value and must not silently convert it into yes/no using an invented threshold. A caller that requires a boolean should specify its interpretation in the question or consume the numeric result explicitly.

The response also includes the resolved model and token usage (`input_tokens`, `output_tokens`). The supplied deployment advertises `jev-latest`, which selects English or multilingual Laya automatically.

## Design decisions

- Expose one public tool function, `evaluate`, supporting a batch of up to 32 questions in one request. Batching retains the native JEV contract and avoids redundant context transmission.
- Use the deployed HTTP contract directly through the project's existing `httpx` dependency. Support configured `http://` and `https://` service origins without hard-coding either protocol. Do not add `typesafe-sdk` only for this wrapper; direct JSON transport keeps the boundary small and exposes the exact compatible response. This can be revisited if SDK-specific compatibility becomes a product requirement.
- Capture Agent2LLM messages inside the tool through `get_agent_object()`. Include eligible `user`, `assistant`, and paired `tool` messages; exclude `system` messages. The caller cannot supply or override historical context.
- Treat the new inquiry as typed `questions`, not as another chat message embedded in `state`. This preserves JEV's separation between evidence (`state`) and decisions (`questions`).
- Read configuration once into a typed immutable configuration object at the tool boundary. Internal client functions receive explicit configuration parameters and do not repeatedly read environment variables.
- Fail closed if runtime Agent2LLM context or credentials are unavailable. Never send a context-free request while claiming it represents the current agent state.
- Return structured machine-readable data; do not reduce choice probabilities, score legends, confidence, usage, or raw noul values to prose.

## Public tool interface

Proposed module: `tools/jev_tool.py`.

Proposed registration:

```text
TOOLS = {"evaluate": evaluate}
```

The existing automatic tool discovery exposes it as `jev_tool-evaluate` with the default connection character.

Proposed Python signature:

```text
def evaluate(questions: str) -> dict
```

`questions` is string-first JSON representing an object keyed by caller-chosen question IDs:

```json
{
  "refund": {
    "type": "noul",
    "instructions": "Does the user request a refund?"
  },
  "priority": {
    "type": "choice",
    "instructions": "Choose the handling priority.",
    "criteria": {
      "low": "Can wait",
      "normal": "Handle normally",
      "urgent": "Requires immediate action"
    }
  }
}
```

Validation before any network I/O:

- Parse `questions` with `json.loads`; require a JSON object with 1–32 entries.
- Require each key to be a non-empty string and each value to be an object.
- Permit only `type`, `instructions`, and `criteria` in each question.
- Require `type` to be exactly `choice`, `score`, or `noul`.
- Require non-empty `instructions` in the first version even though the wire schema only requires a string.
- Require non-empty `criteria` for `choice` and `score`; omit `criteria` for `noul` unless deployed-service behavior proves a useful contract.
- Bound configured/request content before transport; see Context safety.

No public `state`, API URL, API key, model, timeout, context toggle, or retry parameter is proposed. Those are deployment policy rather than per-call model choices, and allowing the LLM caller to override them would weaken the trusted boundary. This is an intentional application of parameter priority: there is currently no lower-level function parameter competing with environment values. The internal transport must accept explicit config and payload parameters for testability.

### Success return

```json
{
  "status": "ok",
  "model": "jev-latest",
  "answers": {
    "refund": {"type": "noul", "noul": 0.97}
  },
  "usage": {"input_tokens": 123, "output_tokens": 5}
}
```

All upstream answer fields are preserved after schema validation.

### Error return

```json
{
  "status": "invalid_request|unavailable|timeout|upstream_error|invalid_response",
  "reason": "stable_machine_readable_reason",
  "message": "bounded safe diagnostic",
  "retryable": false
}
```

The return must never include the API key, Authorization header, full URL credentials, full Agent2LLM state, or an unbounded upstream body.

## Environment variables

The implementation phase must update both `env_template` and `docs/Environment_Variables.md` in the same logical change.

| Variable | Default | Required | Meaning |
|---|---:|---:|---|
| `TOPSAILAI_JEV_BASE_URL` | `""` | yes | Trusted service origin using either `http://` or `https://`, without a hard-coded deployment address or protocol. The client validates the configured URL scheme and appends `/v1/systemone`. |
| `TOPSAILAI_JEV_API_KEY` | `""` | yes | Bearer credential. Never log or return it. |
| `TOPSAILAI_JEV_MODEL` | `"jev-latest"` | no | Model sent in each request. |
| `TOPSAILAI_JEV_TIMEOUT_SECONDS` | `10` | no | Positive finite total HTTP timeout in seconds. Invalid values fail configuration validation rather than silently becoming unbounded. |
| `TOPSAILAI_JEV_MAX_RETRIES` | `1` | no | Non-negative retry count for retryable failures only. |
| `TOPSAILAI_JEV_MAX_CONTEXT_MESSAGES` | `50` | no | Maximum number of recent eligible Agent2LLM messages included. Positive integer. |
| `TOPSAILAI_JEV_MAX_CONTEXT_CHARS` | `60000` | no | Maximum serialized context characters after normalization. Positive integer. |

The concrete endpoint, key, and model supplied for the current deployment belong in protected runtime configuration, not source, documentation examples, test fixtures, or committed environment templates. Because this design document may be committed, it deliberately does not reproduce the credential.

`BASE_URL` and `API_KEY` have no usable defaults so a missing configuration fails closed and cannot accidentally send context to a guessed host. The client selects HTTP or HTTPS from the configured URL scheme; there is no separate insecure-HTTP opt-in and no implicit protocol conversion. Transport accepts an injected `JevConfig` so tests do not mutate process-wide environment.

## Agent2LLM context injection

At tool execution time:

1. Call `get_agent_object()` from `utils/thread_local_tool.py`.
2. If no active agent exists or `agent.messages` is unavailable, return `unavailable/no_runtime_context` before network I/O.
3. Snapshot messages; never mutate `agent.messages` or nested message objects.
4. Exclude every `system` message. System prompts may contain tool catalogs, memory/skill content, environment details, and secrets that are unnecessary for the JEV decision.
5. Include chronological `user`, ordinary `assistant`, and historical `tool` messages. Preserve each historical assistant tool-call declaration together with the `role=tool` result messages whose `tool_call_id` it declares as one atomic group. Drop an orphaned tool result, and drop an assistant tool-call declaration if its declared results are absent or incomplete, so JEV never receives a structurally misleading partial interaction.
6. Exclude the final assistant message when it declares the currently executing JEV tool call. In native tool-call mode, `PromptBase.add_assistant_message()` appends that declaration before tool execution, while its result does not yet exist. Excluding this one active declaration prevents a guaranteed orphan, avoids duplicating the new inquiry, and does not remove completed historical tool interactions.
7. Normalize supported text and structured content to a JSON-safe representation, retaining tool name and tool-call ID where available so declarations and results remain attributable. Skip unsupported binary/multimodal payloads with a bounded omission marker.
8. Tool results can contain command output, file content, credentials, tokens, or other sensitive data. Before export, redact the configured JEV API key and recognizable authorization/credential fields from all eligible message content. This is defense in depth, not a guarantee that arbitrary secrets can be detected; enabling the tool explicitly authorizes bounded eligible Agent2LLM tool output to be sent to the configured external JEV service.
9. Apply `TOPSAILAI_JEV_MAX_CONTEXT_MESSAGES` to the most recent eligible content while retaining chronological order and treating each assistant-declaration/tool-result group atomically. Never retain only part of a group to satisfy the limit.
10. Serialize an explicit envelope as JEV `state`, for example:

```json
{
  "agent2llm_messages": [
    {"role": "user", "content": "..."},
    {
      "role": "assistant",
      "content": "...",
      "tool_calls": [{"id": "call_1", "name": "example_tool", "arguments": "..."}]
    },
    {"role": "tool", "tool_call_id": "call_1", "name": "example_tool", "content": "..."}
  ]
}
```

11. Enforce `TOPSAILAI_JEV_MAX_CONTEXT_CHARS` by removing the oldest eligible message or complete tool-call group, never by cutting JSON bytes in the middle or separating a declaration from its result. If one newest ordinary message or one newest complete tool-call group alone exceeds the bound, replace content fields with deterministic head/tail-safe truncated representations, mark them `truncated: true`, and preserve pairing metadata.
12. Send this state together with the validated new `questions` object and configured model.

This model gives JEV conversational and completed tool evidence plus a fresh, explicit decision request without copying hidden system instructions, sending an orphaned tool interaction, or allowing the LLM caller to forge history.

## Internal structure

Proposed files for the implementation logical change:

- `tools/jev_tool.py` — LLM-facing function, docstring, `TOOLS`, config-bound orchestration.
- `tools/jev_tool_utils/models.py` — immutable `JevConfig` and stable result/error structures.
- `tools/jev_tool_utils/config.py` — centralized environment parsing and validation.
- `tools/jev_tool_utils/context.py` — non-mutating Agent2LLM snapshot, filtering, normalization, and bounds.
- `tools/jev_tool_utils/client.py` — injected synchronous `httpx.Client` transport and response validation.
- `tests/unit/test_topsailai_tools_jev_tool/` — focused tests split by config, context, validation, transport, and public tool contract.
- `tests/bdd/features/jev_decision_tool.feature` and matching steps/harness — user-visible execution through a loopback mock HTTP service.
- `env_template` and `docs/Environment_Variables.md` — synchronized configuration reference.
- `tools/readme.md` — add the tool to the available-tools table and document only project-level behavior not already expressed by source/docstrings.

`tools/jev_tool.py` is discovered automatically by `tools/base/init.py`; no manual central registry change is expected. Do not define `TOOLS_INFO` unless native schema generation cannot express the string-first contract. The registered function docstring must state input JSON shape, supported types, context behavior, and return statuses, and receive direct unit-test coverage as required by `tools/readme.md`.

## Transport and security

- Construct the endpoint by validating `TOPSAILAI_JEV_BASE_URL`, accepting exactly the `http` and `https` schemes, and appending exactly `/v1/systemone`; reject URL user-info and every other scheme. Select the transport from the configured scheme without hard-coding or rewriting it.
- Send `Authorization: Bearer <key>` and `Content-Type: application/json`.
- Use the existing `httpx` package. Use a short-lived client initially; add pooling only if measured call volume justifies lifecycle management.
- Do not log request bodies at INFO or above. Debug logging should contain only request ID/correlation ID, question IDs/types, selected model, elapsed time, HTTP status, retry count, and response usage.
- Never log headers or secrets. Sanitize upstream diagnostics before returning them.
- This tool exports conversation and completed tool content to an external service. It should be disabled by default until both base URL and API key are explicitly configured; tool discovery may keep the function registered, but invocation must fail before I/O when configuration is absent so startup configuration changes can take effect without import-time environment caching.
- Both HTTP and HTTPS are supported without an extra opt-in. Operators should use HTTPS whenever transport encryption is required; when HTTP is configured, the tool honors that operator choice and sends the same authenticated request without silently upgrading, downgrading, or rejecting the scheme.

## Errors, timeout, and retry

| Condition | Status | Retry |
|---|---|---|
| Invalid JSON/question schema/config | `invalid_request` | no |
| No active Agent2LLM context | `unavailable` | no |
| Connect/read/write/pool timeout | `timeout` | yes, within configured budget |
| Network disconnect or HTTP `408`, `429`, `502`, `503`, `504` | `upstream_error` | yes |
| HTTP `401` or `403` | `upstream_error` | no; use reason `authentication_failed` |
| HTTP `400` or `422` | `upstream_error` | no; return bounded validation summary |
| Other HTTP `4xx` | `upstream_error` | no |
| Other HTTP `5xx` | `upstream_error` | no, unless explicitly allowlisted above |
| Malformed JSON or response-schema mismatch | `invalid_response` | no |

Use exponential backoff with small bounded jitter. The total operation must remain bounded: the configured timeout applies to each HTTP attempt, while retry count places an absolute cap on attempts. Retry only before a valid response is accepted. Since evaluation is read-only, retry does not mutate external state, but retries still consume service capacity and potentially token usage; keep the default at one retry.

Validate that response `answers` has exactly the requested question IDs and that each answer type matches its corresponding request. Reject missing, extra, or mismatched answers as `invalid_response` rather than passing ambiguous data to the agent.

## Test plan

### Unit tests

- Parse valid single and mixed `noul`/`choice`/`score` batches.
- Reject malformed JSON, non-object roots, empty or over-32 batches, unknown fields/types, missing instructions, and missing required criteria before network I/O.
- Verify environment parsing, finite positive timeout, non-negative retries, absent secret behavior, endpoint construction, acceptance of both configured HTTP and HTTPS origins, rejection of every other scheme, and no hard-coded address/key/protocol.
- Verify internal explicit config overrides make tests independent from environment variables.
- Snapshot Agent2LLM context without mutation.
- Exclude every system message and the active JEV tool-call declaration while including ordinary user/assistant content and completed historical tool interactions.
- Preserve assistant tool-call declarations and matching tool results as atomic groups; drop orphaned tool results and incomplete declaration groups before export.
- Preserve chronological order and apply message/character limits deterministically without splitting tool-call groups.
- Redact the configured JEV API key and recognizable authorization/credential fields; verify logs and errors do not contain exported content or secrets.
- Handle dict and object-like message representations used by the runtime.
- Verify no context causes zero transport calls.
- Verify Authorization is sent but never present in logs or returned errors.
- Map every timeout/network/HTTP/error category and retry only allowlisted transient failures.
- Validate all three answer schemas, exact answer-key parity, answer-type parity, and usage.
- Assert raw `noul` numeric values are preserved without undocumented thresholding.
- Test the registered function docstring contract and `TOOLS` registration.

### BDD/integration tests

Because this feature is tightly coupled to Agent2LLM context and tool execution, add Gherkin coverage. Use local loopback mock JEV servers, not the public service and not internal transport stubs. Scenarios should prove:

- A current conversation plus a new noul inquiry reaches `/v1/systemone` with sanitized ordered state and returns the numeric judgement.
- One request evaluates mixed question types and preserves structured answers.
- System messages and the active native JEV tool-call declaration are not exported, while a completed historical assistant/tool interaction is exported with intact pairing.
- Orphaned or incomplete tool-call groups are omitted, and context limits never separate a declaration from its result.
- Configured HTTP and HTTPS endpoints are both accepted and used without protocol rewriting; HTTPS uses a test certificate configuration appropriate to the loopback harness.
- A timeout produces a bounded machine-readable error and exact retry count.
- An invalid response is rejected.
- A missing API key sends no request.

Run focused tests colorlessly. For full unit verification use `tests/run_tests.py`, not `pytest tests/unit`, per project instructions. Test artifacts and captured request bodies must be written under `.tmp` and cleaned without broad process termination.

### Optional live smoke test

Only after explicit approval, run one minimal request against the configured deployment and assert response shape, not a fixed model judgement probability. Never persist the live API key or exported conversation. Live testing is not required for the design phase.

## Approved decisions

- Include eligible `user`, `assistant`, and completed paired `tool` messages in JEV state; exclude all `system` messages and the currently executing JEV tool-call declaration.
- Accept both configured HTTP and HTTPS origins without a separate insecure-HTTP opt-in or protocol rewriting.
- Provide one generic batch function to preserve native JEV batching and minimize tool-prompt size.
- Preserve raw numeric `noul` values without boolean conversion until an authoritative threshold is documented.

## Implementation sequence after approval

- Add synchronized environment configuration documentation.
- Implement typed config, context builder, and transport with unit tests.
- Register the public tool and docstring contract.
- Add loopback BDD coverage.
- Run focused tests, then `tests/run_tests.py`.
- Review every changed file with `git diff` before requesting commit approval.
