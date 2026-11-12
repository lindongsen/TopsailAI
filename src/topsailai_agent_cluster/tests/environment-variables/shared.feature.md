---
maintainer: AI
author: DawsonLin
status: verified
created: 2026-11-12
---

# Shared and Compatibility Behaviour

Feature: shared configuration and compatibility aliases remain deterministic

Background:

- Given the Server and Endpoint use the same configuration package
- And each process declares its role before environment parsing
- And a renamed variable has exactly one spelling, because the compatibility cycle is over

## Scenario: a shared setting reaches both daemons

Given `AGENT_CLUSTER_DATABASE_PATH` names a temporary database below `.tmp/`
When Server configuration is loaded
And Endpoint configuration is loaded
Then both configurations use the supplied path
And neither role-specific prefix is required for that shared setting

Automation: config package table test.

## Scenario: direct launches receive role-specific database defaults

Given no database path is supplied
When Server configuration is loaded
Then its database path is `.tmp/server.sqlite`
When Endpoint configuration is loaded
Then its database path is `.tmp/endpoint.sqlite`

Automation: config defaults unit test.

## Scenario: a removed spelling cannot configure anything

Given a renamed variable is set under both its primary and removed names
And the values differ
When the owning process loads configuration
Then the primary value is selected
And the removed value cannot override it
And no warning is printed, because the removed name is not read at all

Given only the removed spelling is set
When the owning process loads configuration
Then the documented default is applied
And the removed value is never read

Automation: removed-name table test for every migrated owner group.

## Scenario: an invalid own-role value fails visibly

Given a role-owned structured or numeric setting is malformed
When the owning process loads configuration
Then loading fails
And the error names the primary setting
And no service initialization begins

Automation: role-specific config unit test.

## Scenario: an invalid foreign-role value is ignored

Given Server configuration is being loaded
And an Endpoint-only JSON setting is malformed
When configuration is loaded
Then the Server load succeeds
And the foreign value does not alter a Server field

Given Endpoint configuration is being loaded
And a Server-only address map is malformed
When configuration is loaded
Then the Endpoint load succeeds
And the foreign value does not alter an Endpoint field

Automation: role isolation table test.

## Scenario: the shared TLS identity has a neutral name

Given `AGENT_CLUSTER_TLS_SERVER_NAME` is set
When Endpoint configuration is loaded for a Server-initiated connection
Then the Endpoint uses it as the expected Server certificate identity
When Server configuration is loaded with a shared Endpoint certificate
Then the Server uses it as the expected shared certificate identity

Automation: config load unit test plus existing Server dial tests.

## Execution evidence

```bash
make test-unit-common
```

- Result: PASS.
- Elapsed time: 3.67 seconds.
- Automated coverage: Configuration role isolation, defaults and removed-name tests in the common/unit suite.
- Skips or unavailable environments: none reported by these runs.
- Evidence logs: `.tmp/env-prefix-*.log`; timing records: `.tmp/env-prefix-*.time`.

The Markdown scenarios are acceptance-design records rather than executable Godog files. Their
assertions are implemented in the owning Go test packages and exercised through the Makefile targets
above.
