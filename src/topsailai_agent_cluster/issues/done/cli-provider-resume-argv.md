---
maintainer: AI
author: DawsonLin
---
# Provider resume selector mismatch

Official provider help requires workspace resume -s SESSION_ID, but adapter emitted a positional session. Real resume is rejected before launch. Existing tests omitted exact resume argv. Repair selector and assert opaque resource maps to provider identity in the exact argument vector. Verified: adapter tests74.6% statement coverage, adapter race/vet PASS, full module PASS152.62s. Exact provider help confirms selector syntax. Real resumed-agent readiness remains separate, not claimed here.
