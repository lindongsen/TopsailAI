---
maintainer: AI
author: DawsonLin
status: verified
created: 2026-11-12
---

# Server Environment Behaviour

Feature: Server-only configuration uses the Server prefix and cannot be controlled by Endpoint or CLI names

Background:

- Given the process role is `agent-cluster-server`
- And shared TLS, database and log settings keep their shared names

## Scenario Outline: each Server primary name configures its field

Given `<variable>` is set to `<value>`
When Server configuration is loaded
Then `<field>` equals `<value>`

Examples:

| variable | value | field |
|---|---|---|
| `AGENT_CLUSTER_SERVER_API_LISTEN_ADDR` | `127.0.0.1:53680` | API listen address |
| `AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR` | `127.0.0.1:53943` | channel listen address |
| `AGENT_CLUSTER_SERVER_ENDPOINT_DIAL_ADDRESSES` | `ep-a=wss://127.0.0.1:53944` | Endpoint dial address map |
| `AGENT_CLUSTER_SERVER_TLS_SHARED_CERTIFICATE` | `true` | shared-certificate mode |
| `AGENT_CLUSTER_SERVER_AUTH_TOKEN` | `server-secret` | API bearer token |

Automation: Server-role config table test.

## Scenario Outline: each removed Server name is ignored

Given the primary name for `<removed>` is absent
And `<removed>` is set to `<value>`
When Server configuration is loaded
Then the corresponding Server field keeps its documented default
And no warning is printed, because the name is not read at all

Examples:

| removed | value |
|---|---|
| `AGENT_CLUSTER_API_LISTEN_ADDR` | `127.0.0.1:53680` |
| `AGENT_CLUSTER_CHANNEL_LISTEN_ADDR` | `127.0.0.1:53943` |
| `AGENT_CLUSTER_ENDPOINT_DIAL_ADDRESSES` | `ep-a=wss://127.0.0.1:53944` |
| `AGENT_CLUSTER_TLS_SHARED_CERTIFICATE` | `true` |
| `AGENT_CLUSTER_AUTH_TOKEN` | `legacy-secret` |
| `AGENT_CLUSTER_SERVER_NAME` | `legacy-name` |

Automation: Server removed-name table test.

## Scenario: Endpoint and CLI names do not alter Server configuration

Given malformed Endpoint adapter JSON is present
And malformed CLI history limits are present
When Server configuration is loaded
Then loading succeeds
And Server fields retain their defaults or Server-owned values

Automation: foreign-role isolation test.

## Scenario: the removed generic listen alias cannot define the API address

Given only `AGENT_CLUSTER_LISTEN_ADDRESS` is set
When Server configuration is loaded
Then the primary Server API address does not take that value
And the removed `--listen-address` flag is not registered

Automation: config surface test.

## Scenario: the Server template contains no removed scope setting

Given the shipped Server template is read
Then it does not contain `AUTH_SCOPES`
And it contains no key that the launcher silently ignores

Automation: packaging/template contract test.

## Scenario: the Server container emits primary names only

Given `docker/Dockerfile` is inspected
Then its Server-only `ENV` entries use `AGENT_CLUSTER_SERVER_`
And no deprecated Server environment name is emitted
And shared database, TLS and log names remain unchanged

Automation: packaging Dockerfile test.

## Scenario: the Server launcher maps its conffile to primary settings

Given a Server `node.conf` uses the existing unprefixed conffile vocabulary
When `agent-clusterctl` starts the Server
Then the binary receives the primary Server flags or environment names
And no Endpoint-only flag is passed

Automation: launcher packaging test with a temporary bundle below `.tmp/`.

## Execution evidence

```bash
make test-unit-server
make test-packaging
```

- Result: PASS / PASS.
- Elapsed time: 5.04 seconds / 48.37 seconds.
- Automated coverage: Server config tests plus launcher, template and Dockerfile packaging contract tests.
- Skips or unavailable environments: none reported by these runs.
- Evidence logs: `.tmp/env-prefix-*.log`; timing records: `.tmp/env-prefix-*.time`.

The Markdown scenarios are acceptance-design records rather than executable Godog files. Their
assertions are implemented in the owning Go test packages and exercised through the Makefile targets
above.
