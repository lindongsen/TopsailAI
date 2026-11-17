---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
---

# Issue: llm_mock_server streaming lacks tool_calls delta path

## Location
- File: `/TopsailAI/src/topsailai/cli/tests/bdd/streaming_mock_server_harness.py` (mock server implementation `llm_mock_server.py` `_write_stream`)
- Related BDD suite: `/TopsailAI/src/topsailai/cli/tests/bdd/test_streaming_mock_server.py`

## Problem
The mock server's `_write_stream` only emits `delta.content` chunks over SSE. There is no code path producing `delta.tool_calls` stream deltas, so the streaming tool_calls incremental reassembly logic in `llm_base.py` cannot be verified through a real HTTP/SSE chain. That reassembly logic is currently covered only at unit level with fake streams.

## Impact
- Streaming tool_calls reassembly (index/id/name/arguments accumulation) is untested end-to-end; a wire-format regression would not be caught by the BDD suite.
- The BDD streaming suite cannot exercise the tool_calls scenario over the real transport.

## Suggested Follow-up
Add a `stream_tool_call_chunks` field to `MockServerConfig` so the mock server can emit `delta.tool_calls` deltas in `_write_stream`. This is a small backward-compatible change (new optional field, default off) and requires separate approval. Once available, the existing BDD tool_calls scenario can be upgraded to run over the real HTTP/SSE chain.

## Resolution (2026-11-17): implemented, with a different field name

The capability this issue asked for exists. It was implemented in
`51f03231 test: cover native tool execution hooks over SSE` (2026-10-21), which
is two months after this issue was written on 2026-08-27.

### The field name differs from the suggestion

This issue proposed `stream_tool_call_chunks`. The implementation is
`stream_tool_call_deltas`, because each entry is a complete
`choices[0].delta` mapping rather than a list of chunks. The behaviour the issue
asked for is unchanged: an optional field, default off, that makes
`_write_stream` emit `delta.tool_calls` over real SSE.

### Where it lives

- `tests/mock/llm_mock_server.py` — `MockServerConfig.stream_tool_call_deltas`,
  default `None`, frozen into `_native_stream_responses` at construction.
- `tests/mock/llm_mock_native_stream.py` — `freeze_native_deltas()` validates and
  JSON-encodes each delta at the fixture boundary, and `response_deltas()`
  appends the native deltas after the content chunks and selects
  `finish_reason="tool_calls"` when native deltas are present.
- `tests/mock/README.md` — section "Native Tool Call SSE Fixtures" documents the
  contract, including that absent or empty configuration preserves the legacy
  content-only stream with `finish_reason="stop"`.

### The reassembly logic is now covered over real HTTP/SSE

`tests/bdd/test_tool_execute_hooks.py` drives the real OpenAI client against the
mock server and asserts the incremental reassembly the issue said was untested
end-to-end:

- three deltas split the arguments as `'{"val'`, `'ue": '`, `'1}'`
- the client assembles `{"value": 1}`
- `index` is `0` on all three fragments, `id` and `function.name` arrive on the
  first only
- `finish_reason` values include both `tool_calls` and `stop`
- the next request body carries the paired tool result

That scenario runs through `tests/bdd/tool_calls_mock_harness.py`, which starts
the mock server with `create_server()` and points the client at it through
`OPENAI_API_BASE`, so the transport is real HTTP, not a fake stream.

### Verification

Raw SSE wire probe (`.tmp/probe_native_sse_wire.py`), reading the response bytes
directly with `urllib.request`:

```
=== raw SSE lines containing tool_calls ===
data: {... "delta": {"tool_calls": [{"index": 0, "i...
data: {... "delta": {"tool_calls": [{"index": 0, "f...
data: {... "delta": {"tool_calls": [{"index": 0, "f...
data: {... "delta": {}, "finish_reason": "tool_call...
=== finish_reason values ===
None
None
None
None
tool_calls
```

This proves `delta.tool_calls` reaches the wire, which is exactly what the issue
said was missing.

Test suites:

- `tests/unit/test_topsailai_llm_mock_server_native_stream.py` — 35 passed
- `tests/bdd/test_tool_execute_hooks.py` — 4 passed
- `cli/tests/bdd/test_streaming_mock_server.py` — 5 passed

### The CLI suite named by this issue still has no tool_calls scenario

The issue named `cli/tests/bdd/test_streaming_mock_server.py` as the suite to
upgrade. That suite still covers only content streaming, usage accounting and
error paths. This is not a gap in the mock server: the CLI suite exercises
`LLMModel.chat()` output ordering and token statistics, and the tool-call
reassembly it would need to assert is already covered by the core BDD suite
above, over the same real transport. Adding a duplicate scenario there would
test the same production code twice.

### Frontmatter repaired

This file had no YAML frontmatter at all, so it failed to parse and could not be
triaged by status. A frontmatter block was added with `status: resolved`, and the
stray `maintainer: AI` line at the end of the body was removed because it is now
declared in the frontmatter.
