---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---
# Null-response recovery could append duplicate temporary messages

## Symptom

A single LLM chat request could retain multiple identical recovery messages when qualifying null-response streaks were separated by another retryable error.

## Root cause

The non-null error path reset both the consecutive-null counter and the flag recording that the request already held a temporary recovery message. The earlier injected message remained live, so a later streak appended another one.

## Resolution

Only reset the consecutive-null counter. Once recovery guidance is injected for a request, reuse that live message until request-final cleanup removes it. Real HTTP/SSE BDD covers continuous streaks, separated streaks, configuration, disabling, successful cleanup, and exhausted cleanup.
