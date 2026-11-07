---
maintainer: AI
author: DawsonLin
status: active
created: 2026-11-07
---

# Environment Variables

Every variable below is read once at the process boundary by
`internal/config/config.go` and converted into typed configuration. Business logic
receives explicit parameters and never reads the environment directly.

Each variable also has a command-line flag. The flag takes precedence over the
environment variable, and the environment variable takes precedence over the
built-in default. The launcher `scripts/agent-clusterctl` reads a shell
configuration file and passes values as flags, so a bundle deployment does not
depend on inherited environment variables.

## Shared

| Variable | Flag | Default | Purpose |
|---|---|---|---|
| `AGENT_CLUSTER_DATABASE_PATH` | `--database-path` | `.tmp/server.sqlite` | SQLite database file |
| `AGENT_CLUSTER_TLS_CA_FILE` | `--tls-ca-file` | empty | CA bundle used to verify peers |
| `AGENT_CLUSTER_TLS_CERTIFICATE_FILE` | `--tls-certificate-file` | empty | Node certificate |
| `AGENT_CLUSTER_TLS_KEY_FILE` | `--tls-key-file` | empty | Node private key |
| `AGENT_CLUSTER_TLS_REVOKED_SERIALS_FILE` | `--tls-revoked-serials-file` | empty | Revoked certificate serial list |
| `AGENT_CLUSTER_LOG_OUTPUT` | `--log-output` | `stderr` | Log destination: `stderr` or `file` |
| `AGENT_CLUSTER_LOG_PATH` | `--log-path` | empty | Log file path when `file` output is selected |
| `AGENT_CLUSTER_LOG_MAX_SIZE_MB` | `--log-max-size-mb` | `100` | Maximum log file size before rotation |
| `AGENT_CLUSTER_LOG_MAX_BACKUPS` | `--log-max-backups` | `10` | Maximum retained log backups |
| `AGENT_CLUSTER_LOG_MAX_AGE_DAYS` | `--log-max-age-days` | `30` | Maximum log backup age |

## Server

| Variable | Flag | Default | Purpose |
|---|---|---|---|
| `AGENT_CLUSTER_API_LISTEN_ADDR` | `--api-listen-addr` | `:8080` | Bearer-authenticated operator API address |
| `AGENT_CLUSTER_CHANNEL_LISTEN_ADDR` | `--channel-listen-addr` | `:8443` | mTLS Endpoint channel address |
| `AGENT_CLUSTER_LISTEN_ADDRESS` | `--listen-address` | `:8080` | Deprecated alias for the API address |
| `AGENT_CLUSTER_AUTH_TOKEN` | `--auth-token` | `development-token` | Bearer token the API validates |
| `AGENT_CLUSTER_AUTH_SCOPES` | `--auth-scopes` | empty | Comma-separated operator scopes granted to that token |

### `AGENT_CLUSTER_AUTH_SCOPES`

Recognised values: `view`, `read_output`, `send_message`, `control`,
`endpoint_admin`. An unknown value is rejected at startup rather than ignored, so
a typo cannot silently widen or narrow access.

An empty value grants every scope. This is the single-administrator deployment and
preserves the behaviour of earlier releases.

A command whose advertised capability declares a permission is rejected with
`403 permission_denied` when the credential does not hold it. Every `ctl.*`
operation must declare a permission, so a sensitive provider action cannot become
reachable merely because an Endpoint omitted the declaration.

### `AGENT_CLUSTER_AUTH_TOKEN`

The built-in default `development-token` is a development convenience, not a
deployment value. A Server started without an explicit token accepts that known
string from any reachable client. Always set a real token, and restrict the API
listener to a trusted address.

## Endpoint

| Variable | Flag | Default | Purpose |
|---|---|---|---|
| `AGENT_CLUSTER_ENDPOINT_ID` | `--endpoint-id` | empty | Endpoint identity announced to the Server |
| `AGENT_CLUSTER_INSTANCE_ID` | `--instance-id` | `default` | Endpoint instance identity |
| `AGENT_CLUSTER_CHANNEL_ADDRESS` | `--channel-address` | empty | Server WSS address the Endpoint dials |
| `AGENT_CLUSTER_ADAPTERS` | none | empty | JSON array of adapter bindings |
| `AGENT_CLUSTER_COMMAND_ALLOWLIST_FILE` | `--command-allowlist-file` | empty | Endpoint-global command allowlist file |

### `AGENT_CLUSTER_ADAPTERS`

A JSON array. Each element carries `adapter_id`, `provider_type`, `command`,
optional `args`, `timeout_ms` and optional `capabilities`. The `command` must be an
absolute path that exists on the node. Parsing rejects an empty array, duplicate
adapter IDs, a relative command path and a non-positive timeout.

Adapters are supplied through the environment because no flag exists for them. The
launcher exports this variable from the `ADAPTERS` configuration entry.

### `AGENT_CLUSTER_COMMAND_ALLOWLIST_FILE`

Gates the `command.exec` operation, which backs the operator `!` command. Paths are
resolved relative to the bundle root by the launcher.

The file is line-based. Each line is one entry matched as a prefix of the argv
array, so `git status` permits `git status --short` but not `git push`. Blank lines
and `#` comments are ignored.

Programs that can execute other programs require at least two tokens, because a
single-token entry would authorise the whole program. The rejected set is `git`,
`find`, `awk`, `sed`, `xargs`, `env`, `make`, `docker`, `kubectl`, `sh`, `bash`,
`python`, `python3`, `perl`, `ruby` and `node`. Such an entry is rejected when the
file is loaded, so a configuration mistake fails at startup rather than at the first
execution.

An unset value disables command execution entirely. The Endpoint refuses
`command.exec` with an explicit error rather than falling back to an unrestricted
shell.

The file is reloaded on `SIGHUP`. A reload parses the whole file before replacing
the active set, so a malformed edit keeps the previous entries in force and is
logged. A reload that would remove every entry is refused unless the file contains
the explicit empty directive. Each successful reload logs the entry count.

## Security consequences of leaving a value unset

| Variable | Consequence |
|---|---|
| `AGENT_CLUSTER_AUTH_TOKEN` | The known development token is accepted |
| `AGENT_CLUSTER_AUTH_SCOPES` | The token holds every scope |
| `AGENT_CLUSTER_COMMAND_ALLOWLIST_FILE` | `command.exec` is unavailable |
| `AGENT_CLUSTER_TLS_*` | Remote listeners cannot verify peers |
| `AGENT_CLUSTER_ADAPTERS` | The Endpoint has no provider to collect from |

## Related documents

- `docs/agent-cluster-architecture.md`: security baseline and authority model.
- `docs/agent-cluster-protocol.md`: `ctl.<action>` and `command.exec` operations.
- `conf/node.server.conf.example` and `conf/node.endpoint.conf.example`: launcher
  configuration examples.
