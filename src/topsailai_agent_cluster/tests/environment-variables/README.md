---
maintainer: AI
author: DawsonLin
status: verified
created: 2026-11-12
---

# Component Environment Variable Test Plan

## Purpose

This directory specifies acceptance behaviour for assigning Agent Cluster environment variables to
the process that owns them. The scenarios use BDD language so each test states the operator-visible
contract before implementation and execution.

These files are test design documents, not registered Godog feature files. Executable product feature
files remain under `features/`, as required by `tests/bdd/suite_registry_test.go`. Automation for this
plan belongs in the owning Go test package and is run through the Makefile component and test-kind
targets.

## Convention under test

| Owner | Primary prefix |
|---|---|
| Shared Server and Endpoint configuration | `AGENT_CLUSTER_` |
| Server only | `AGENT_CLUSTER_SERVER_` |
| Endpoint only | `AGENT_CLUSTER_ENDPOINT_` |
| Operator CLI only | `AGENT_CLUSTER_CLI_` |

Trigger-script payload variables are excluded. They remain the published `AGENT_CLUSTER_*` child
process payload until a separate compatibility plan changes them.

## Documents

| File | Scope | Status |
|---|---|---|
| `shared.feature.md` | role-aware parsing, shared settings, aliases and defaults | verified |
| `server.feature.md` | Server-owned settings and foreign-role isolation | verified |
| `endpoint.feature.md` | Endpoint-owned settings, launcher mapping and dead surfaces | verified |
| `cli.feature.md` | CLI process/env-file configuration and history | verified |
| `deployment.feature.md` | launcher, templates, packages, container and inventory audit | verified |

## Execution order

1. Focused unit target for the logical unit.
2. `make test-packaging` when scripts, templates, Dockerfile or package payloads change.
3. `make test-bdd` after all three component surfaces converge.
4. `make test-integration` after BDD passes.
5. `make test-harness` for real-process startup coverage.
6. `make test-all` as the final aggregate verification.

Tests must run without colour. Go's test output is colourless by default. Test-only artifacts, logs,
coverage and generated fixtures must be written below `.tmp/`.

## General pass criteria

- The primary name configures exactly one owning component unless it is explicitly shared.
- The deprecated name works only as a fallback and produces deprecation evidence.
- When both names are set, the primary name wins.
- A malformed foreign-role variable cannot prevent the current role from starting.
- A malformed own-role variable fails visibly.
- Generated configuration emits only primary names.
- Every remaining old name is an intentional compatibility alias or migration explanation.
- Trigger payload names are unchanged.

## Evidence format

Update each scenario after execution with:

- exact Makefile command;
- pass/fail status;
- elapsed time;
- affected automated test name;
- any unavailable environment or skipped case.

## Execution evidence

| Command | Result | Elapsed time |
|---|---:|---:|
| `make test-unit-common` | PASS | 3.67 seconds |
| `make test-unit-server` | PASS | 5.04 seconds |
| `make test-unit-endpoint` | PASS | 8.89 seconds |
| `make test-unit-cli` | PASS | 91.31 seconds |
| `make test-unit` | PASS | 88.66 seconds |
| `make test-bdd` | PASS | 563.20 seconds |
| `make test-integration` | PASS | 138.06 seconds |
| `make test-packaging` | PASS | 48.37 seconds |
| `make test-harness` | PASS | 9.47 seconds |
| `make test-all` | PASS | 870.68 seconds |

No skipped or unavailable environment was reported by these runs. Command output is retained under
`.tmp/env-prefix-*.log`, with elapsed-time records under `.tmp/env-prefix-*.time`. These are temporary
verification artifacts and are not project deliverables.
