---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# LLM Mock Server

`llm_mock_server.py` provides a reusable OpenAI-compatible non-streaming chat-completions service for deterministic prompt-cache tests. It uses only the Python standard library.

## Cache Model

The server canonicalizes each message and compares complete messages from the beginning of the current request with every retained historical request. `usage.prompt_tokens_details.cached_tokens` is the token estimate for the best exact common message prefix. The estimate uses `ceil(canonical_message_characters / chars_per_token)` per message.

This is an intentionally idealized KV-cache model. The cache key includes only the canonicalized `messages`; request fields such as `model`, `tools`, and `tool_choice` are intentionally ignored. Real providers can impose token-block minimums, TTLs, routing constraints, model-specific cache policies, and broader cache-key scopes.

## Start

From the project folder:

```text
tests/mock/llm_mock_server.py --host 127.0.0.1 --port 8000
```

Available startup arguments:

- `--host` — bind host; default `127.0.0.1`
- `--port` — bind port; default `8000`; use `0` to select an available port
- `--model` — health endpoint model name
- `--reply` — canned assistant response
- `--chars-per-token` — positive deterministic token-estimation divisor
- `--cache-capacity` — positive number of retained prompts and request records

Arguments are explicit and therefore take precedence over process configuration. No new environment variables are required by the server.

## Connect TopsailAI

Set the existing OpenAI-compatible client configuration:

```text
OPENAI_API_BASE=http://127.0.0.1:8000/v1
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_API_KEY=mock
OPENAI_MODEL=topsailai-mock
LLM_RESPONSE_STREAM=0
```

`ai_base/llm_base.py` reads `OPENAI_API_BASE` when it constructs the OpenAI client. `OPENAI_BASE_URL` is included because model-selection commands keep both aliases synchronized, but the direct client currently uses `OPENAI_API_BASE`.

## Endpoints

- `POST /v1/chat/completions` — OpenAI-compatible non-streaming completion
- `GET /health` — readiness and configured model
- `GET /debug/state` — cache capacity, retained prompt count, total request count, and bounded per-request cache results
- `DELETE /debug/state` — clear retained prompts and counters

Requests with `stream=true` return an explicit `400` error because this mock server intentionally supports only the non-streaming mode required by the cached-token BDD tests.

## Verify Cache Reuse

Send one request, then send another request with the same leading messages and an appended suffix. The second response reports non-zero `cached_tokens`. Change or insert a message before the previously matching prefix to observe a reduced or zero hit. Query `/debug/state` to inspect `cached_messages`, `cached_tokens`, and `prompt_tokens` for every retained request.
