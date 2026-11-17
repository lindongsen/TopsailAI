---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
---

# U2 abandoned first-item blocked worker

## Symptom

When an abandoned first-item stream is blocked in a provider read, initiating close on the exact old raw response does not deterministically make the client fetch worker exit promptly. The worker can later report an `LLMProviderReadError` such as `Bad file descriptor` after the response is released.

## Reproduction

Run the real loopback cleanup BDD scenarios for `first_item` in `tests/bdd/features/llm_first_byte_timeout_cleanup.feature`. Request 1 times out, request 2 succeeds, and the test releases request 1 while the shared-pool sibling remains held. Observe the exact request-1 raw close initiation, then the late read error and the still-running request-1 fetch worker.

## Impact

The abandoned worker may remain blocked longer than the test-side settlement window and retain temporary worker/custody state. The retry remains protected from stale publication, and the late disposal read error is observable and classified as benign/expected by the acceptance harness.

## Accepted limitation

The Human-approved U2 design v3 drops the requirement for prompt request-1 fetch-worker exit because closing an abandoned response cannot deterministically unblock a blocked read without a production-side mechanism. No production wait, forced termination, cancellation mechanism, or behavior change is authorized for U2. The harness therefore asserts exact raw close initiation and the expected late-read classification, while reporting unresolved blocked-worker state honestly rather than treating it as full settlement.

## Closure verification (2026-11-17)

Closed as an accepted limitation, not as a fixed defect. No code change is required or authorized.

The Human-approved U2 design v3 explicitly drops the requirement for prompt request-1 fetch-worker
exit, because closing an abandoned response cannot deterministically unblock a blocked provider
read without a production-side wait, forced termination or cancellation mechanism, none of which
is authorized for U2.

The harness therefore asserts exact raw close initiation and classifies the late read error as
benign/expected, while reporting unresolved blocked-worker state honestly instead of treating it
as full settlement. That is the intended contract, so there is nothing left to repair here.

This record is closed to keep the open-issue list meaningful. If a future design authorizes a
production-side cancellation mechanism, this scenario must be reopened as a new issue with that
authorization attached.
