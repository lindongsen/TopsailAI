---
maintainer: AI
author: DawsonLin
status: implementation-ahead-specification
---

# Provider CLI BDD specifications

## Purpose

This directory defines the acceptance contract for the Endpoint Adapter and independent provider CLI seam. The files use executable Gherkin syntax, but the production seam and its step definitions do not exist yet.

The current Godog suite runs every registered file under `features/` and has a guard that rejects unregistered feature files in that directory. These implementation-ahead specifications therefore remain under `tests/bdd/specifications/provider-cli/` until the corresponding production behavior and step definitions are delivered in the same logical unit.

A scenario in this directory is **planned acceptance**, not evidence that the behavior currently passes.

## Activation workflow

For each implementation logical unit:

1. Select the matching specification file and acceptance scenarios.
2. Implement the production behavior first; this project does not use test-first red-green TDD unless the human explicitly requests it.
3. Add Godog step definitions under `tests/bdd/`.
4. Move or copy the accepted executable feature into `features/` and register it in `tests/bdd/suite_test.go` in the same change.
5. Run `make test-bdd` and the relevant component, integration, packaging, or live target.
6. Confirm the feature registry guards pass, so no feature is silently omitted.
7. Record limitations instead of marking an unexecuted scenario as passed.

## Specification modules

| File | Contract area | Primary verification layer |
|---|---|---|
| `protocol.feature` | Bootstrap, compatibility, JSON framing, request correlation, stdout/stderr bounds and error classification | Conformance and Endpoint integration |
| `function-contract.feature` | Closed function inventory and function-specific semantics | Conformance |
| `resource-identity.feature` | Resource mapping tuple, key stability, Adapter/profile/resource identity and collection outcomes | Endpoint integration and upgrade tests |
| `capability-query.feature` | Descriptor intersection, effective revision, refresh lifecycle, query registry and control approval | Unit, conformance and integration |
| `execution-generation.feature` | Minimal mutation request, same-path generation validation, invocation identity and receipt authority | Conformance and Endpoint integration |
| `output-stream.feature` | Snapshot bounds, JSONL follow framing, terminal outcomes, cancellation and backpressure | Conformance, BDD and integration |
| `scheduling-custody.feature` | Per-adapter capacity, queue bounds, helper ownership and durable resource handoff | Integration and provider live tests |
| `packaging-upgrade.feature` | Independent packages, immutable versions, activation, rollback and Endpoint independence | Packaging and integration |
| `trust-configuration.feature` | Local trust without sandbox claims, fixed invocation configuration and secret boundaries | Conformance, integration and security review |
| `mock-conformance.feature` | Reference Mock behavior, local fault fixtures and executable conformance | Conformance |
| `replacement-acceptance.feature` | Contract-based replacement, old-path removal and Provider CLI version rollback | Integration, BDD and live verification |

## Requirement traceability

| Confirmed rule | Covered by |
|---|---|
| Adapter is part of Endpoint and Endpoint starts the provider CLI directly | `execution-generation.feature`, `trust-configuration.feature` |
| Internal process invocation is not public `command.exec` | `execution-generation.feature` |
| Provider backend implementation is outside the Cluster contract | `trust-configuration.feature` |
| Provider CLI is locally trusted without malicious-code sandboxing | `trust-configuration.feature` |
| Provider projects are independent and do not import Cluster internals | `mock-conformance.feature`, `packaging-upgrade.feature` |
| Endpoint package has no concrete provider dependency | `packaging-upgrade.feature` |
| Mock is test-only and absent from production installation | `packaging-upgrade.feature`, `mock-conformance.feature` |
| Resource identity is `(adapter_id, resource_kind, provider_resource_key)` | `resource-identity.feature` |
| Provider keys remain stable across compatible upgrades | `resource-identity.feature`, `mock-conformance.feature` |
| Adapter, launch profile, provider profile and Cluster resource identities are distinct | `resource-identity.feature` |
| Provider never owns Cluster IDs, journal phase or complete receipts | `resource-identity.feature`, `execution-generation.feature` |
| Standard reads use closed Cluster-defined `query` names and schemas | `capability-query.feature`, `function-contract.feature` |
| Mutation revalidates expected generation in the execution path | `execution-generation.feature`, `mock-conformance.feature` |
| Each Adapter instance has independent bounded concurrency | `scheduling-custody.feature`, `output-stream.feature` |
| Endpoint, Adapter instance and provider limits combine by the strictest value | `scheduling-custody.feature` |
| Provider helper ownership differs from durable business-resource custody | `scheduling-custody.feature`, `mock-conformance.feature` |
| Provider package installation and Adapter activation are separate | `packaging-upgrade.feature` |
| Provider activation is versioned, validated and rollback-safe | `packaging-upgrade.feature`, `replacement-acceptance.feature` |
| The replacement removes the old Adapter paths without a dual implementation phase | `replacement-acceptance.feature` |

## Test data and cleanup rules

- Use provider-private fixture keys that are stable and non-sensitive.
- Create unique adapter IDs, invocation IDs and request IDs per scenario unless reuse is the behavior under test.
- Fault modes come only from local test process configuration or fixture files, never from a protocol request.
- Every process-based scenario records the exact process it starts and cleans up only that process and its owned children.
- Durable-resource scenarios must distinguish the resource lifecycle from the provider invocation helper lifecycle.
- Packaging scenarios use temporary package roots under the configured test temporary directory and must not alter a live node installation.
- Secrets and credentials must not appear in examples, captured output or committed fixtures.

## Expected test entry points

The implementation plan adds dedicated Makefile targets rather than ad-hoc component commands:

```text
make test-conformance
make test-bdd
make test-integration
make test-packaging
make test-all
```

`test-conformance` is a planned target and must not be reported as executed until it exists. Component-level and larger test runs continue to use Makefile targets as required by project memory.
