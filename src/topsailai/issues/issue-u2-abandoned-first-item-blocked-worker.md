# U2 abandoned first-item blocked worker

## Symptom

When an abandoned first-item stream is blocked in a provider read, initiating close on the exact old raw response does not deterministically make the client fetch worker exit promptly. The worker can later report an `LLMProviderReadError` such as `Bad file descriptor` after the response is released.

## Reproduction

Run the real loopback cleanup BDD scenarios for `first_item` in `tests/bdd/features/llm_first_byte_timeout_cleanup.feature`. Request 1 times out, request 2 succeeds, and the test releases request 1 while the shared-pool sibling remains held. Observe the exact request-1 raw close initiation, then the late read error and the still-running request-1 fetch worker.

## Impact

The abandoned worker may remain blocked longer than the test-side settlement window and retain temporary worker/custody state. The retry remains protected from stale publication, and the late disposal read error is observable and classified as benign/expected by the acceptance harness.

## Accepted limitation

The Human-approved U2 design v3 drops the requirement for prompt request-1 fetch-worker exit because closing an abandoned response cannot deterministically unblock a blocked read without a production-side mechanism. No production wait, forced termination, cancellation mechanism, or behavior change is authorized for U2. The harness therefore asserts exact raw close initiation and the expected late-read classification, while reporting unresolved blocked-worker state honestly rather than treating it as full settlement.
