---
maintainer: AI
author: DawsonLin
status: specification
---

# Feature: Live environment is real, isolated, and observable

## Background

Given the operator has read [the suite rules](README.md)
And the test uses deployed `agent-cluster-server`, `agent-cluster-endpoint`, and `agent-cluster-cli` processes
And the provider is the real configured provider rather than a fixture binary
And all writable paths and resources are dedicated to this run
And evidence is written under the workspace temporary directory

## Scenario ENV-LIVE-001: Record exact component versions

Given the Server, every Endpoint, the CLI, and provider CLI are installed
When the operator records each executable version and build identity
Then every component has a non-empty version or immutable build reference
And the report associates each version with its machine or container
And no credential appears in the transcript

## Scenario ENV-LIVE-002: Prove the CLI reaches the real Server API

Given the operator workstation is configured with the live Server URL
When the CLI requests Server health and readiness
Then the request crosses the real network boundary
And the Server reports healthy storage and a ready API
And the response is not supplied by a local fixture or loopback test harness

## Scenario ENV-LIVE-003: Prove each Endpoint has one usable channel

Given each Endpoint is configured for its deployed channel direction
When the operator lists Endpoint connection state
Then every required Endpoint is online
And each Endpoint has one active usable connection generation
And the configured direction is recorded as endpoint-initiated, server-initiated, or bidirectional
And a failed extra dial does not evict a healthy link

## Scenario ENV-LIVE-004: Verify Server and Endpoint clocks are usable

Given command expiry and observation freshness depend on wall-clock timestamps
When the operator compares Server, Endpoint, and operator timestamps
Then their skew is within the deployment's accepted command-skew limit
And elapsed durations are measured with a monotonic-capable local timer
And an unacceptable skew blocks mutating-command scenarios

## Scenario ENV-LIVE-005: Establish test-owned resources

Given the provider can create or identify test sessions
When the operator records the running and stopped test session IDs and generations
Then every destructive scenario targets only those resources
And each resource is visibly marked or documented as test-owned
And at least one unrelated session is recorded as a cleanup sentinel

## Scenario ENV-LIVE-006: Establish protected policy and allowlist workspaces

Given Endpoint policy and command allowlist changes are needed
When the operator prepares the test policy directory and test allowlist
Then both are readable only by the intended Endpoint service identity and approved administrators
And the original configuration is backed up to an approved protected location
And the rollback procedure is recorded before the first reload
And no token secret appears in a filename

## Scenario ENV-LIVE-007: Establish baseline provider invocation evidence

Given later negative scenarios must prove the provider was not invoked
When the operator records the provider's current bounded invocation or audit marker
Then a later invocation can be correlated to a case ID without logging prompt content
And the evidence distinguishes no invocation, invoked once, and uncertain invocation count
And the collection method does not modify the Agent or provider state
