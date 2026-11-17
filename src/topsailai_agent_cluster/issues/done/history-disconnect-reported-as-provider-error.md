---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# A disconnected endpoint was reported as a provider failure

## Trigger

Found while reviewing the committed `history` feature. A throwaway probe test drove the real
HTTP handler with the channel's disconnect result and observed `502 provider_error`.

## Symptom

A lost endpoint returned `502 provider_error` with the message `provider history read failed`.
The operator was told to investigate a provider that was never reached.

## Cause

The channel reports a disconnect in two different shapes, and only one was classified:

1. `internal/channel/history.go` `failPendingHistory` returns
   `protocol.HistoryResult{ErrorCode: "endpoint_unavailable"}` with a **nil** error.
2. `internal/server/history.go` sees the non-empty `ErrorCode` and calls
   `writeHistoryResultFailure`.
3. That switch handled `history_unsupported` and `history_response_too_large` only, so
   `endpoint_unavailable` fell through to the provider default and became `502 provider_error`.

The transport-error shape (`err != nil`) was already correct: `writeHistoryFailure` returns
`503 endpoint_unavailable`. So the two disconnect paths disagreed.

## Why the tests missed it

`internal/server/history_test.go` covered only the `err != nil` path, using
`errors.New("endpoint is offline")`. The real disconnect path carries a nil error, so no test
exercised the branch that was wrong.

## Fix

Added an explicit `endpoint_unavailable` case to `writeHistoryResultFailure` returning
`503 endpoint_unavailable`. Both disconnect shapes now agree.

Added `TestHistoryDisconnectIsNotReportedAsProviderError`, which drives the handler with a nil
error and the disconnect code. Verified red before the fix (`status=502`) and green after.

## Lesson

A failure can arrive as a Go error or as a structured error code. Classifying only one shape
leaves the other to a default branch, and a default branch usually means "the other thing".
Every error-code switch needs a case for each code the producer can actually emit, and the
producer's own source is the only reliable inventory of those codes.
