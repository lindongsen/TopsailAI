---
maintainer: AI
workspace: /TopsailAI/src/topsailai
status: resolved
---

# JEV Retry Status Was Too Broad

## Trigger

Focused branch-coverage work showed that the JEV client marked every HTTP 5xx response retryable, while the approved implementation request allows retries only for HTTP 408, 429, 502, 503, and 504 plus transport timeouts or network errors.

## Impact

Responses such as HTTP 500 could consume an extra request and service capacity contrary to the approved retry policy.

## Resolution

Use the explicit retryable-status allowlist only and add a regression proving HTTP 500 is not retried. The adjacent response-validation and context-bound findings were also resolved by validating complete answer/model/usage shapes, normalizing unsupported runtime values to bounded markers, and failing closed when the configured context cap cannot contain the irreducible envelope.

## Verification

Focused JEV unit and BDD verification passed with 68 tests and 96% aggregate new-source coverage. The project unit runner passed all 229 test files.
