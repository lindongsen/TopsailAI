---
maintainer: AI
author: DawsonLin
status: active
created: 2026-11-07
---

# Environment Variables

Every variable below is read once at the process boundary and converted into typed
configuration. The Server and Endpoint read theirs through
`internal/config/config.go`; the operator CLI reads its own configuration in
`src/main/agent-cluster-cli/main.go` and
`src/main/agent-cluster-cli/input_history.go`. Business logic receives explicit parameters and never
reads the environment directly.

Almost every variable also has a command-line flag. The flag takes precedence over
the environment variable, and the environment variable takes precedence over the
built-in default. `AGENT_CLUSTER_ENDPOINT_ADAPTERS` is the exception: it carries a JSON array
and has no flag, so the launcher exports it. The launcher
`scripts/agent-clusterctl` reads a shell configuration file and passes values as
flags, so a bundle deployment does not depend on inherited environment variables.

## Configuration sources

The same variables reach a process through three different deployment paths, and the path decides
which of them is authoritative:

| Deployment | Configuration source | Consequence |
|---|---|---|
| Bundle | `conf/node.conf`, read by `scripts/agent-clusterctl` and passed as flags | the conffile is authoritative for every key the launcher forwards, and the environment is not consulted for those keys |
| Debian package | `/opt/agent-cluster/conf/node.conf` and the TLS material, installed by the role's config package and registered as conffiles | an upgrade does not replace the operator's file or certificate |
| Container image | `ENV` in `docker/Dockerfile` plus `-e` at run time | no conffile exists, so the environment is the only source |

Both node deployments use the same file name, `conf/node.conf`; `conf/node.server.conf.example` and
`conf/node.endpoint.conf.example` are the role templates the config package copies into place. The
binary packages carry no configuration, so `agent-cluster-config-server-<site>` and
`agent-cluster-config-endpoint-<site>` are the only artifacts that differ between machines. The site
suffix is part of the package name because two sites build packages with the same role and version
but different contents, so an unsuffixed name would let dpkg accept the wrong site's package
silently.

The launcher forwards a fixed set of keys, so a key present in `node.conf` but absent from that set is
silently ignored rather than passed to the process. `CONTROL_ACTION_FILE` was such a key until it was
added to the set: the template shipped it and the binary accepted it, but the launcher never read it,
so a packaged node advertised no `ctl.` action. The launcher now resolves it, prints it in `doctor` and
passes `--control-action-file`, and `TestLauncherForwardsTheControlActionCatalog` guards all three
sites. See `AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE` below and
`issues/agent-clusterctl-drops-control-action-file.md`. A key that must reach the process regardless of
the launcher can be exported directly, because the binary reads the environment as well.

A container image carries no `conf/` directory at all. `internal/config/config.go` reads only the
process environment, so a `node.conf` placed in the image would be inert, and the image fixes the
database path and the three TLS paths in `ENV` rather than shipping a file. A variable set with `-e`
overrides the image default, which is the same precedence the flag has over the environment in a
package deployment. See `docs/agent-cluster-architecture.md` for the container directory tree and the
mount points.

The CLI is unaffected by the deployment form: it resolves its configuration from the sources
listed under "CLI configuration file precedence" regardless of whether the Server runs as a package or
a container.

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
| `AGENT_CLUSTER_SERVER_API_LISTEN_ADDR` | `--api-listen-addr` | `:8080` | Bearer-authenticated operator API address |
| `AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR` | `--channel-listen-addr` | `:8443` | mTLS Endpoint channel address; unused in the `server-initiated` direction |
| `AGENT_CLUSTER_CHANNEL_DIRECTION` | `--channel-direction` | `endpoint-initiated` | Which side dials the channel: `endpoint-initiated`, `server-initiated` or `bidirectional` |
| `AGENT_CLUSTER_SERVER_ENDPOINT_DIAL_ADDRESSES` | `--endpoint-dial-addresses` | empty | Comma-separated `endpoint_id=wss://address` pairs the Server dials in the `server-initiated` and `bidirectional` directions |
| `AGENT_CLUSTER_SERVER_TLS_SHARED_CERTIFICATE` | `--tls-shared-certificate` | `false` | Every Endpoint presents the Server certificate; the certificate no longer proves Endpoint identity |
| `AGENT_CLUSTER_SERVER_AUTH_TOKEN` | `--auth-token` | `development-token` | Bearer token the API validates |

### `AGENT_CLUSTER_SERVER_AUTH_TOKEN`

The built-in default `development-token` is a development convenience, not a
deployment value. A Server started without an explicit token accepts that known
string from any reachable client. Always set a real token, and restrict the API
listener to a trusted address.

## Endpoint

| Variable | Flag | Default | Purpose |
|---|---|---|---|
| `AGENT_CLUSTER_ENDPOINT_ID` | `--endpoint-id` | empty | Endpoint identity announced to the Server |
| `AGENT_CLUSTER_ENDPOINT_INSTANCE_ID` | `--instance-id` | `default` | Endpoint instance identity |
| `AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS` | `--channel-address` | empty | Server WSS address the Endpoint dials; unused in the `server-initiated` direction |
| `AGENT_CLUSTER_CHANNEL_DIRECTION` | `--channel-direction` | `endpoint-initiated` | Which side dials the channel: `endpoint-initiated`, `server-initiated` or `bidirectional` |
| `AGENT_CLUSTER_ENDPOINT_CHANNEL_LISTEN_ADDR` | `--endpoint-channel-listen-addr` | empty | mTLS listen address the Endpoint accepts the Server on in the `server-initiated` and `bidirectional` directions |
| `AGENT_CLUSTER_TLS_SERVER_NAME` | `--server-name` | `agent-cluster-server` | Server certificate identity the Endpoint verifies in the `server-initiated` direction |
| `AGENT_CLUSTER_ENDPOINT_ADAPTERS` | none | empty | JSON array of adapter bindings |
| `AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE` | `--command-allowlist-file` | empty | Endpoint-global command allowlist file |
| `AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE` | `--control-action-file` | empty | Endpoint-local `ctl.<action>` catalog; the only source of control actions |
| `AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR` | `--endpoint-access-policy-dir` | empty | Endpoint-local directory holding one access policy file per caller token; empty means every caller is permitted |
| `AGENT_CLUSTER_ENDPOINT_COLLECTION_DELAY_MS` | none | `5000` | Positive post-collection delay in milliseconds; launcher value is `COLLECTION_DELAY_MS` |

### `AGENT_CLUSTER_ENDPOINT_ADAPTERS`

A JSON array. Each element carries `adapter_id`, `provider_type`, `command`,
optional `args`, `timeout_ms` and optional `capabilities`. The `command` must be an
absolute path that exists on the node. Parsing rejects an empty array, duplicate
adapter IDs, a relative command path and a non-positive timeout.

Adapters are supplied through the environment because no flag exists for them. The
launcher exports this variable from the `ADAPTERS` configuration entry.

### Deprecated Endpoint environment names

The names below remain fallback aliases for one compatibility cycle. The component-prefixed name
always wins when both are present. New deployments and maintained tests must use only the primary
name.

| Deprecated name | Primary name |
|---|---|
| `AGENT_CLUSTER_INSTANCE_ID` | `AGENT_CLUSTER_ENDPOINT_INSTANCE_ID` |
| `AGENT_CLUSTER_CHANNEL_ADDRESS` | `AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS` |
| `AGENT_CLUSTER_ADAPTERS` | `AGENT_CLUSTER_ENDPOINT_ADAPTERS` |
| `AGENT_CLUSTER_COMMAND_ALLOWLIST_FILE` | `AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE` |
| `AGENT_CLUSTER_CONTROL_ACTION_FILE` | `AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE` |
| `AGENT_CLUSTER_COLLECTION_DELAY_MS` | `AGENT_CLUSTER_ENDPOINT_COLLECTION_DELAY_MS` |

### `AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE`

Gates the `command.exec` operation, which backs the operator `!` command. Paths are
resolved relative to the bundle root by the launcher.

The file is line-based. Each line is one entry matched as a prefix of the argv
array, so `git status` permits `git status --short` but not `git commit`. Blank lines
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

Both deployment paths install a default policy, so a fresh node starts with the
shipped allowlist in force rather than refusing to start. The bundle installs
`conf/command-allowlist.conf.example` as `conf/command-allowlist.conf`; the Debian
package installs it as `/opt/agent-cluster/conf/command-allowlist.conf` and registers it
as a conffile, so an upgrade does not replace the operator's policy.

The shipped default is the common operational set an operator needs to inspect a
node and prepare a workspace, grouped by purpose:

| Group | Entries |
|---|---|
| Read-only inspection | `ls`, `pwd`, `cat`, `head`, `tail`, `wc`, `grep`, `stat`, `file`, `du`, `df`, `free`, `ps`, `uptime`, `uname`, `whoami`, `id`, `date`, `nproc`, `lscpu`, `lsblk`, `hostname` |
| Network diagnostics | `ping`, `nc`, `ss`, `netstat` |
| Filesystem mutation | `mkdir`, `touch` |
| Git | `git status`, `git log`, `git diff`, `git show`, `git push`, `git pull`, `git fetch` |

Destructive entries are deliberately absent: `rm`, `mv`, `cp`, `dd`, `kill`,
`truncate` and the package managers are not listed, so this surface cannot delete or
overwrite. Add them only as an explicit local decision, because prefix matching cannot
restrict what they act on.

Arguments are confined to the session working directory: an absolute path or a `..`
element is rejected before the program runs. `df -h` and `du -sh .` are therefore
usable, while `df /` and `cat /etc/passwd` are refused. Confinement is not a sandbox: a
program that reads a fixed location without an operand, such as `df` with no argument,
still reports the whole machine.

The default is not a sandbox. `git push` accepts `--receive-pack` and
`git fetch`/`git pull` accept `--upload-pack`, both of which run a local command;
`git pull` also runs the repository's `post-merge` hook and any configured merge
driver; `git show` honours `--output` and textconv filters declared in
`.gitattributes`; `hostname NAME` renames the machine when the Endpoint runs as root;
`nc` can listen, connect and transfer arbitrary data; `ping -f` floods a target; and
`mkdir`/`touch` create entries in the session directory. Prefix matching cannot
distinguish those forms, so an entry is only as narrow as its first tokens and every
entry is reachable by anyone holding the `control` scope.

The file is reloaded on `SIGHUP`. A reload parses the whole file before replacing
the active set, so a malformed edit keeps the previous entries in force and is
logged. A reload that would remove every entry is refused unless the file contains
the explicit empty directive. Each successful reload logs the entry count.

### `AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE`

Defines the `ctl.<action>` surface. This file is the only source of control
actions: the action name, its permission, its payload schema and the provider
command each action runs all come from here, so changing the action surface never
requires a code change.

The launcher forwards this key. `scripts/agent-clusterctl` resolves
`CONTROL_ACTION_FILE`, prints it in `doctor` and passes `--control-action-file`, so a
node started through the launcher loads the catalog its `node.conf` names. It
previously forwarded only `COMMAND_ALLOWLIST_FILE`, so a packaged node advertised no
`ctl.` action even when `node.conf` named one; that gap is recorded in
`issues/agent-clusterctl-drops-control-action-file.md` and is guarded by
`TestLauncherForwardsTheControlActionCatalog`. A direct launch can still supply the
path with `--control-action-file` or `AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE`.

The file is one JSON document. Whole-line `#` comments are ignored, so the shipped
example can explain itself; trailing comments are not supported. Each entry carries:

| Field | Meaning |
|---|---|
| `name` | Action name after the `ctl.` prefix. Required, no whitespace, must not repeat the prefix. A dotted name stays one action. |
| `permission` | Scope required to invoke it. Must be one of `view`, `read_output`, `send_message`, `control`, `endpoint_admin`. |
| `payload_schema` | JSON Schema object describing the payload. Descriptive only: the Server stores and returns it verbatim and never interprets it. |
| `command` | Provider argv template. Required, no empty tokens. |
| `payload_session_field` | Optional payload field filled from the revalidated target, so the operator is not asked for a selector the Endpoint already holds. Requires a `{payload}` placeholder. |

The `command` array is executed directly, never through a shell. Two placeholders
are substituted per token, so a placeholder never splits into several arguments:
`{session}` becomes the provider session key and `{payload}` becomes the JSON
payload. Each may appear at most once, and an unknown or unterminated placeholder
is rejected when the file is loaded.

An unset value advertises no `ctl.` action at all and refuses every `ctl.`
operation. That is the fail-closed default, not an error: an Endpoint without a
catalog cannot be talked into running an action nobody configured.

Both deployment paths install the shipped catalog, so a fresh node keeps the
feature. The bundle installs `conf/control-actions.conf.example` as
`conf/control-actions.conf`; the Debian package installs it as
`/opt/agent-cluster/conf/control-actions.conf` and registers it as a conffile, so an
upgrade does not replace the operator's action surface.

The file is reloaded on `SIGHUP`. A reload parses the whole document before
replacing the active set, so a malformed edit keeps the previous actions in force
and is logged. An empty `actions` list is accepted and disables the whole family.
Each successful reload logs the action count.

Because the catalog decides which provider command runs, it is an authorization
surface and must not be remotely writable. The Endpoint validates the configured
capability list before its policy hook runs, so an action absent from the catalog is
rejected before any allowlist or policy check.

## Client

The operator CLI reads these variables at its own process boundary. They are not
read by the Server or the Endpoint, so a bundle deployment configures them per
operator rather than per node. History settings have no flags; the environment or
CLI configuration files override their built-in defaults.

| Variable | Flag | Default | Purpose |
|---|---|---|---|
| `AGENT_CLUSTER_CLI_SERVER_URL` | `--server-url` | `http://127.0.0.1:8080` | Server API URL the CLI connects to |
| `AGENT_CLUSTER_CLI_TOKEN` | `--token` | empty | Bearer token the CLI presents to the Server |
| `AGENT_CLUSTER_CLI_ENDPOINT_TOKENS` | `--endpoint-token` for one selected Endpoint | empty | Comma-separated `endpoint_id=token` map used for Endpoint authorization |
| `AGENT_CLUSTER_CLI_HISTORY_FILE` | none | `${HOME}/.topsailai/.topsailai_agent_cluster.history.jsonl` | Persistent JSONL file for accepted interactive input |
| `AGENT_CLUSTER_CLI_HISTORY_MAX_ENTRIES` | none | `100` | Maximum trailing history records read at startup and maximum commands retained for Up/Down recall |
| `AGENT_CLUSTER_CLI_HISTORY_MAX_SIZE_MB` | none | `1` | Maximum active history-file size before rotation |
| `AGENT_CLUSTER_CLI_HISTORY_MAX_BACKUPS` | none | `1` | Maximum retained rotated history files |

`AGENT_CLUSTER_CLI_TOKEN` has no built-in default, unlike the Server's development
token. A CLI started without it omits the `Authorization` header entirely, so the
Server rejects the request instead of the client silently using a known development
value.

Interactive history stores every accepted nonblank submission as one JSON object per
line. REPL commands use `kind=command`; confirmation, guided-choice and wizard answers
use `kind=answer`. Only commands enter Up/Down recall. The file is created with mode
`0600`, startup reads only a bounded tail, and a missing, unreadable or malformed file
is reported without preventing the interactive CLI from starting. A configured numeric
bound must be a non-negative integer; zero uses the built-in default.

### CLI configuration file precedence

The CLI resolves its configuration from five sources. `prepareExecutableEnv` runs
in `main` before flag parsing, so the files are loaded first. The Server URL and token
flags are then parsed with the resolved values as their defaults; history settings have
no flags and are resolved once from the resulting environment.

| Rank | Source | Mechanism |
|---|---|---|
| 1 | Explicit flag | `--server-url`, `--token`; no history flags |
| 2 | Process environment | `os.LookupEnv` before the CLI starts |
| 3 | Executable-local file | `/opt/agent-cluster/bin/.env.local` |
| 4 | Per-user file | `${HOME}/.topsailai/.topsailai_agent_cluster.env` |
| 5 | Built-in default | `http://127.0.0.1:8080` for the URL, empty for the token |

Prefer the per-user file. It is written at install time by
`agent-cluster-node-setup` and is the intended configuration source. Use the
executable-local file only when the per-user file cannot be used, because it is
read first and therefore overrides the per-user file.

Each file only fills keys that are still unset, so the first source to define a key
wins and a later source cannot override it. The executable-local file is read
before the per-user file, so its presence makes the per-user file inert for any key
it defines. Neither file reports which source supplied a value, and no diagnostic
command prints the resolved origin, so a stale executable-local file is not
visible from the CLI output.

An empty assignment still occupies the key while the files are loaded, because
`os.LookupEnv` reports an empty value as present. CLI value resolution then treats a
blank component-owned name as unset: it first checks the deprecated name for the
compatibility cycle and otherwise uses the built-in default. An empty
`AGENT_CLUSTER_CLI_SERVER_URL` therefore suppresses that key in later files but may
still select a nonblank `AGENT_CLUSTER_SERVER_URL`; without the deprecated value it
selects the built-in URL. An empty `AGENT_CLUSTER_CLI_TOKEN` similarly falls back to
`AGENT_CLUSTER_TOKEN` when present and otherwise sends no `Authorization` header.

The built-in URL default is `http://127.0.0.1:8080`, while the shipped Server
configuration listens on `127.0.0.1:53680`. An unconfigured CLI therefore fails to
connect rather than reporting that it is unconfigured.

The following names are accepted only as deprecated fallbacks. A nonblank
component-owned name always wins when both are set.

| Deprecated name | Component-owned name |
|---|---|
| `AGENT_CLUSTER_SERVER_URL` | `AGENT_CLUSTER_CLI_SERVER_URL` |
| `AGENT_CLUSTER_TOKEN` | `AGENT_CLUSTER_CLI_TOKEN` |
| `AGENT_CLUSTER_ENDPOINT_TOKENS` | `AGENT_CLUSTER_CLI_ENDPOINT_TOKENS` |
| `AGENT_CLUSTER_HISTORY_FILE` | `AGENT_CLUSTER_CLI_HISTORY_FILE` |
| `AGENT_CLUSTER_HISTORY_MAX_ENTRIES` | `AGENT_CLUSTER_CLI_HISTORY_MAX_ENTRIES` |
| `AGENT_CLUSTER_HISTORY_MAX_SIZE_MB` | `AGENT_CLUSTER_CLI_HISTORY_MAX_SIZE_MB` |
| `AGENT_CLUSTER_HISTORY_MAX_BACKUPS` | `AGENT_CLUSTER_CLI_HISTORY_MAX_BACKUPS` |


File format constraints:

- Values are literals. Variable expansion and command substitution are not
  supported, so `$HOST` stays the four characters `$HOST`.
- A leading `export ` is accepted, and a value may be single-quoted, double-quoted
  or unquoted. A quoted value must close on the same line and may only be followed
  by whitespace or a `#` comment.
- An unquoted value ends at the first ` #` sequence.
- Blank lines and lines starting with `#` are ignored.
- A file larger than 1 MiB is rejected rather than truncated.
- A syntax error aborts the CLI with exit status 2 before any command runs, so one
  malformed file prevents every command even when the other file is correct.
- A read error is always labelled `read .env.local`, including when the failing
  file is the per-user file, so that message does not identify the real source.
  Assignment errors instead carry the correct file label and line number.
- An unresolvable home directory is not an error. The per-user file is skipped
  silently and resolution continues to the built-in default.

## Security consequences of leaving a value unset

| Variable | Consequence |
|---|---|
| `AGENT_CLUSTER_SERVER_AUTH_TOKEN` | The known development token is accepted |
| `AGENT_CLUSTER_CLI_TOKEN` | The CLI omits the `Authorization` header and every request is rejected |
| `AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE` | `command.exec` is unavailable |
| `AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE` | No `ctl.` action is advertised and every `ctl.` operation is refused |
| `AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR` | Every caller is permitted, so the Endpoint has no authorization boundary |
| `AGENT_CLUSTER_TLS_*` | Remote listeners cannot verify peers |
| `AGENT_CLUSTER_ENDPOINT_ADAPTERS` | The Endpoint has no provider to collect from |

## Related documents

- `docs/agent-cluster-architecture.md`: security baseline, authority model and the implemented
  container deployment.
- `docs/agent-cluster-protocol.md`: `ctl.<action>` and `command.exec` operations.
- `conf/node.server.conf.example` and `conf/node.endpoint.conf.example`: launcher
  configuration examples.
