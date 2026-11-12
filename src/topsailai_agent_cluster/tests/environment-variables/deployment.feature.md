---
maintainer: AI
author: DawsonLin
status: verified
created: 2026-11-12
---

# Deployment Environment Contract

Feature: every maintained deployment surface emits the component-owned environment names

Background:

- Given compatibility aliases are accepted by binaries but are not primary deployment output
- And trigger-script payload variables are a separate published contract

## Scenario: every old configuration name is classified

Given source, scripts, templates, Dockerfile, Makefile, documents and tests are searched for every deprecated name
When the migration audit is completed
Then every remaining occurrence is one of:

- a compatibility alias definition;
- a compatibility test;
- a migration explanation;

And no launcher, template, container or generated env file emits a deprecated name
And no unclassified occurrence remains

Automation: a bounded repository contract test or explicit audit command recorded in this document.

## Scenario: trigger payload names are unchanged

Given the watch-trigger child environment contract is inspected
When the component configuration names are migrated
Then its published `AGENT_CLUSTER_*` payload keys remain byte-for-byte unchanged
And no `AGENT_CLUSTER_SERVER_`, `AGENT_CLUSTER_ENDPOINT_` or `AGENT_CLUSTER_CLI_` replacement is introduced for those payload keys

Automation: existing trigger environment golden/contract test.

## Scenario: package templates contain only meaningful keys

Given the Server and Endpoint example conffiles are inspected
Then each key is consumed or intentionally translated by `agent-clusterctl`
And `AUTH_SCOPES` is absent
And no dead Endpoint channel-address key remains
And comments describe which process owns each translated value

Automation: packaging template inventory test.

## Scenario: direct binaries and launcher select the same effective values

Given equivalent primary settings are supplied directly to a binary and through `agent-clusterctl`
When Server configuration is loaded by both paths
Then the effective Server configuration is equivalent
When Endpoint configuration is loaded by both paths
Then the effective Endpoint configuration is equivalent

Automation: startup argument/environment comparison test using temporary bundle state below `.tmp/`.

## Scenario: package upgrade accepts old deployed environment names

Given a direct-launch deployment still supplies only deprecated environment names
When the upgraded matching component starts during the compatibility period
Then startup succeeds
And the old values are applied
And deprecation evidence names the primary replacements
And no unrelated component consumes those values

Automation: real-process harness or component-level startup test.

## Scenario: full component verification uses Makefile entry points

Given all logical units are implemented
When tests are executed
Then component checks run through the Makefile in this order:

```bash
make test-unit
make test-bdd
make test-integration
make test-packaging
make test-harness
make test-all
```

And every command, elapsed time, failure, skip and limitation is recorded
And a failed prerequisite stops dependent progression until repaired and rerun

Automation: execution procedure and evidence checklist.

## Scenario: maintained documentation agrees with executable ownership

Given `docs/Environment_Variables.md`, templates, scripts and source are compared
Then every primary setting appears under the component that reads it
And every default equals the code default
And both production-only settings previously missing from documentation are covered under their new names
And the migration alias policy is stated once without presenting old names as preferred

Automation: documentation contract review plus focused string assertions where stable.

## Execution evidence

```bash
make test-unit
make test-bdd
make test-integration
make test-packaging
make test-harness
make test-all
```

- Result: PASS for every command.
- Elapsed time: 88.66 / 563.20 / 138.06 / 48.37 / 9.47 / 870.68 seconds.
- Automated coverage: Makefile unit, BDD, integration, packaging, harness and aggregate suites; repository old-name audit was also completed.
- Skips or unavailable environments: none reported by these runs.
- Evidence logs: `.tmp/env-prefix-*.log`; timing records: `.tmp/env-prefix-*.time`.

The Markdown scenarios are acceptance-design records rather than executable Godog files. Their
assertions are implemented in the owning Go test packages and exercised through the Makefile targets
above.
