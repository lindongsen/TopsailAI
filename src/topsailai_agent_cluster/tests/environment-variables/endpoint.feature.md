---
maintainer: AI
author: DawsonLin
status: verified
created: 2026-11-12
---

# Endpoint Environment Behaviour

Feature: Endpoint-only configuration uses the Endpoint prefix and remains isolated from Server and CLI settings

Background:

- Given the process role is `agent-cluster-endpoint`
- And shared TLS, database and log settings keep their shared names

## Scenario Outline: each Endpoint primary name configures its field

Given `<variable>` is set to `<value>`
When Endpoint configuration is loaded
Then `<field>` equals `<value>`

Examples:

| variable | value | field |
|---|---|---|
| `AGENT_CLUSTER_ENDPOINT_ID` | `endpoint-a` | Endpoint identity |
| `AGENT_CLUSTER_ENDPOINT_INSTANCE_ID` | `instance-a` | process instance identity |
| `AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS` | `wss://127.0.0.1:53943` | Server channel address |
| `AGENT_CLUSTER_ENDPOINT_CHANNEL_LISTEN_ADDR` | `127.0.0.1:53944` | Endpoint channel listener |
| `AGENT_CLUSTER_ENDPOINT_ADAPTERS` | `[{"adapter_id":"default","provider_type":"topsailai","command":"/opt/agent-cluster/providers/topsailai","timeout_ms":120000}]` | adapter configuration |
| `AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE` | `/tmp/allowlist.conf` | command allowlist path |
| `AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE` | `/tmp/actions.json` | control action catalog path |
| `AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR` | `/tmp/policies` | access policy directory |
| `AGENT_CLUSTER_ENDPOINT_COLLECTION_DELAY_MS` | `250` | post-start collection delay |

Automation: Endpoint-role config table test and runtime-hook setting test.

## Scenario Outline: each removed Endpoint name is ignored

Given the primary name for `<removed>` is absent
And `<removed>` is set to `<value>`
When Endpoint configuration is loaded
Then the corresponding Endpoint field keeps its documented default
And no warning is printed, because the name is not read at all

Examples:

| removed | value |
|---|---|
| `AGENT_CLUSTER_INSTANCE_ID` | `legacy-instance` |
| `AGENT_CLUSTER_CHANNEL_ADDRESS` | `wss://127.0.0.1:53943` |
| `AGENT_CLUSTER_ADAPTERS` | `[{"adapter_id":"default","provider_type":"topsailai","command":"/opt/agent-cluster/providers/topsailai","timeout_ms":120000}]` |
| `AGENT_CLUSTER_COMMAND_ALLOWLIST_FILE` | `/tmp/allowlist.conf` |
| `AGENT_CLUSTER_CONTROL_ACTION_FILE` | `/tmp/actions.json` |
| `AGENT_CLUSTER_COLLECTION_DELAY_MS` | `250` |

Automation: Endpoint removed-name table test.

## Scenario: the real Endpoint channel address has one owner

Given the primary Endpoint channel address is configured
When Endpoint startup arguments are built
Then that address is used for the Endpoint-to-Server channel
And no unused duplicate field or `--endpoint-channel-address` flag exists
And Server configuration does not consume the value

Automation: config field/flag surface test plus Endpoint startup test.

## Scenario: Server-only malformed settings do not stop Endpoint startup

Given `AGENT_CLUSTER_SERVER_ENDPOINT_DIAL_ADDRESSES` is malformed
And `AGENT_CLUSTER_SERVER_TLS_SHARED_CERTIFICATE` is malformed
When Endpoint configuration is loaded
Then loading succeeds
And Endpoint fields retain their defaults or Endpoint-owned values

Automation: foreign-role isolation test.

## Scenario: Endpoint startup receives no unused Server authentication token

Given a node conffile contains the Server token required by the installed CLI
When `agent-clusterctl` starts the Endpoint role
Then it does not pass `--auth-token` to the Endpoint binary
And it does not export `AGENT_CLUSTER_SERVER_AUTH_TOKEN` to the Endpoint process
And the CLI token remains available only through the CLI configuration file

Automation: launcher packaging test with captured Endpoint argv and environment.

## Scenario: Endpoint launcher preserves the conffile vocabulary

Given an existing Endpoint `node.conf` uses `INSTANCE_ID`, `CHANNEL_ADDRESS`, `ADAPTERS`, `COMMAND_ALLOWLIST_FILE` and `CONTROL_ACTION_FILE`
When `agent-clusterctl` starts the Endpoint
Then it translates those keys to the primary Endpoint process settings
And the deployed conffile does not need simultaneous key renaming

Automation: launcher compatibility test.

## Scenario: Endpoint collection delay is documented and bounded

Given `AGENT_CLUSTER_ENDPOINT_COLLECTION_DELAY_MS` is unset
When post-start collection is scheduled
Then the existing default delay is used

Given it is malformed or outside the accepted range
When Endpoint startup parses it
Then startup fails visibly or applies the documented bound according to the established parser contract

Automation: runtime-hook unit test; the exact current bound must be read from implementation before coding.

## Execution evidence

```bash
make test-unit-endpoint
make test-packaging
```

- Result: PASS / PASS.
- Elapsed time: 8.89 seconds / 48.37 seconds.
- Automated coverage: Endpoint config/runtime-hook tests plus launcher and package contract tests.
- Skips or unavailable environments: none reported by these runs.
- Evidence logs: `.tmp/env-prefix-*.log`; timing records: `.tmp/env-prefix-*.time`.

The Markdown scenarios are acceptance-design records rather than executable Godog files. Their
assertions are implemented in the owning Go test packages and exercised through the Makefile targets
above.
