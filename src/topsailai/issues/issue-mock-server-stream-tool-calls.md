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

maintainer: AI
