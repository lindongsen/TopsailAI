---
maintainer: AI
author: DawsonLin
status: verified
created: 2026-11-12
---

# CLI Environment Behaviour

Feature: operator CLI settings use the CLI prefix across process and per-user configuration

Background:

- Given the process is `agent-cluster-cli`
- And the CLI reads process environment and its supported per-user env files at the existing precedence boundaries

## Scenario Outline: each CLI primary name configures its concern

Given `<variable>` is set to `<value>`
When CLI configuration is loaded
Then `<concern>` uses `<value>`

Examples:

| variable | value | concern |
|---|---|---|
| `AGENT_CLUSTER_CLI_SERVER_URL` | `https://cluster.example.test` | Server URL |
| `AGENT_CLUSTER_CLI_SERVER_TOKEN` | `operator-token` | Server bearer token |
| `AGENT_CLUSTER_CLI_ENDPOINT_TOKENS` | `endpoint-a=token-a` | Endpoint token map |
| `AGENT_CLUSTER_CLI_HISTORY_FILE` | `/tmp/history.jsonl` | history path |
| `AGENT_CLUSTER_CLI_HISTORY_MAX_ENTRIES` | `200` | in-memory recall bound |
| `AGENT_CLUSTER_CLI_HISTORY_MAX_SIZE_MB` | `2` | active history file bound |
| `AGENT_CLUSTER_CLI_HISTORY_MAX_BACKUPS` | `4` | retained backup bound |

Automation: CLI config and history table tests.

## Scenario Outline: each old CLI name is a warned fallback

Given the primary name for `<deprecated>` is absent
And `<deprecated>` is set to `<value>`
When CLI configuration is loaded
Then the corresponding CLI concern uses `<value>`
And one deprecation event names `<deprecated>` and its primary replacement

Examples:

| deprecated | value |
|---|---|
| `AGENT_CLUSTER_SERVER_URL` | `https://legacy.example.test` |
| `AGENT_CLUSTER_CLI_TOKEN` | `transitional-token` |
| `AGENT_CLUSTER_TOKEN` | `legacy-token` |
| `AGENT_CLUSTER_ENDPOINT_TOKENS` | `endpoint-a=legacy-endpoint-token` |
| `AGENT_CLUSTER_HISTORY_FILE` | `/tmp/legacy-history.jsonl` |
| `AGENT_CLUSTER_HISTORY_MAX_ENTRIES` | `150` |
| `AGENT_CLUSTER_HISTORY_MAX_SIZE_MB` | `3` |
| `AGENT_CLUSTER_HISTORY_MAX_BACKUPS` | `5` |

Automation: CLI compatibility table test.

## Scenario: the transitional Server token name outranks the legacy generic name

Given `AGENT_CLUSTER_CLI_SERVER_TOKEN` is absent
And `AGENT_CLUSTER_CLI_TOKEN` is `transitional-token`
And `AGENT_CLUSTER_TOKEN` is `legacy-token`
When CLI configuration is loaded
Then the Server bearer token is `transitional-token`
And one deprecation event replaces `AGENT_CLUSTER_CLI_TOKEN` with `AGENT_CLUSTER_CLI_SERVER_TOKEN`

Automation: CLI Server-token compatibility unit test.

## Scenario: process primary names outrank deprecated and file values

Given process environment contains a CLI primary value
And the deprecated process name contains a different value
And a supported env file contains a third value
When CLI configuration is loaded
Then the established process-over-file precedence is preserved
And the primary process name wins within the process source
And deprecation evidence identifies the ignored old process spelling

Automation: precedence matrix test using temporary env files below `.tmp/`.

## Scenario: generated CLI env files emit only primary names

Given node installation writes the operator's per-user CLI env file
When the file is read
Then it contains `AGENT_CLUSTER_CLI_SERVER_URL`
And it contains `AGENT_CLUSTER_CLI_SERVER_TOKEN`
And it supports `AGENT_CLUSTER_CLI_ENDPOINT_TOKENS`
And it emits none of the deprecated CLI names

Automation: installer and `scripts/lib/cli-env.sh` packaging tests.

## Scenario: Endpoint token distribution stays local to the CLI

Given the CLI addresses `endpoint-a`
And its local Endpoint token map contains `endpoint-a=token-a`
When it prepares an Endpoint operation
Then it places `token-a` in the request's Endpoint-token field
And the Server configuration does not store or distribute that token map

Automation: existing Endpoint-token resolution unit tests updated to the primary name.

## Scenario: history defaults and retention behaviour survive the rename

Given no CLI history variables are supplied
When history is initialized
Then the existing default file, entry, size and backup limits are unchanged
And accepted interactive input is still written as bounded JSONL
And retention failure still prevents the append

Automation: existing history unit tests plus primary/deprecated name cases.

## Scenario: CLI diagnostics name the primary setting

Given Server URL, Server token or Endpoint token configuration is missing
When the CLI refuses locally
Then its diagnostic names the corresponding `AGENT_CLUSTER_CLI_*` setting
And it does not instruct the operator to create a deprecated name

Automation: CLI error-message unit tests.

## Execution evidence

```bash
make test-unit-cli
make test-packaging
```

- Result: PASS / PASS.
- Elapsed time: 91.31 seconds / 48.37 seconds.
- Automated coverage: CLI configuration, precedence, deprecation diagnostics, token-map and history tests plus generated env-file packaging tests.
- Skips or unavailable environments: none reported by these runs.
- Evidence logs: `.tmp/env-prefix-*.log`; timing records: `.tmp/env-prefix-*.time`.

The Markdown scenarios are acceptance-design records rather than executable Godog files. Their
assertions are implemented in the owning Go test packages and exercised through the Makefile targets
above.
