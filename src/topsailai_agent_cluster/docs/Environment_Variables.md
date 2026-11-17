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
| Bundle | `conf/<role>/node.conf`, read by `scripts/agent-clusterctl` and passed as flags | the selected role conffile is authoritative for every key the launcher forwards |
| Debian package | `/opt/agent-cluster/conf/<role>/node.conf` and role-scoped TLS material, installed by the role config package and registered as conffiles | an upgrade does not replace the operator's file or certificate |
| Container image | `ENV` in `docker/Dockerfile` plus `-e` at run time | no conffile exists, so the environment is the only source |

Node deployments use `conf/<role>/node.conf`; `conf/node.server.conf.example` and
`conf/node.endpoint.conf.example` are the role templates the config package copies into place. The
binary packages carry no configuration, so `agent-cluster-config-server-<site>` and
`agent-cluster-config-endpoint-<site>` are the only artifacts that differ between machines. The site
suffix is part of the package name because two sites build packages with the same role and version
but different contents, so an unsuffixed name would let dpkg accept the wrong site's package
silently.

The launcher forwards a fixed set of keys, so a key present in `node.conf` but absent from that set is
silently ignored rather than passed to the process. `CONTROL_ACTION_FILE` was such a key until it was
added to the set: the template shipped it and the binary accepted it, but the launcher never read it,
so a packaged node advertised no `ctl.` action. That key has since been removed entirely, because the
`ctl.` family is now advertised from the adapter document instead of an Endpoint-local catalog, so the
launcher no longer resolves or forwards it. A key that must reach the process regardless of the
launcher can be exported directly, because the binary reads the environment as well.

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
| `AGENT_CLUSTER_DATABASE_PATH` | `--database-path` | `.tmp/server.sqlite` for the Server, `.tmp/endpoint.sqlite` for the Endpoint | SQLite database file |
| `AGENT_CLUSTER_CHANNEL_DIRECTION` | `--channel-direction` | `endpoint-initiated` | Which side dials the channel: `endpoint-initiated`, `server-initiated` or `bidirectional`; read by both the Server and the Endpoint |
| `AGENT_CLUSTER_TLS_CA_FILE` | `--tls-ca-file` | empty | CA bundle used to verify peers |
| `AGENT_CLUSTER_TLS_CERTIFICATE_FILE` | `--tls-certificate-file` | empty | Node certificate |
| `AGENT_CLUSTER_TLS_KEY_FILE` | `--tls-key-file` | empty | Node private key |
| `AGENT_CLUSTER_TLS_REVOKED_SERIALS_FILE` | `--tls-revoked-serials-file` | empty | Revoked certificate serial list |
| `AGENT_CLUSTER_TLS_SERVER_NAME` | `--server-name` | `agent-cluster-server` | Server certificate identity verified by the Endpoint and by the Server in shared-certificate mode |
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
| `AGENT_CLUSTER_SERVER_ENDPOINT_DIAL_ADDRESSES` | `--endpoint-dial-addresses` | empty | Comma-separated `endpoint_id=wss://address` pairs the Server dials in the `server-initiated` and `bidirectional` directions |
| `AGENT_CLUSTER_SERVER_TLS_SHARED_CERTIFICATE` | `--tls-shared-certificate` | `false` | Every Endpoint presents the Server certificate; the certificate no longer proves Endpoint identity |
| `AGENT_CLUSTER_SERVER_AUTH_TOKEN` | `--auth-token` | `development-token` | Bearer token the API validates |
| `AGENT_CLUSTER_SERVER_ENDPOINT_EXPIRY` | `--endpoint-expiry` | `24h` | Positive offline-retention duration after which the Server removes Endpoint inventory; Endpoint metadata is also removed when no retained command references it |
| `AGENT_CLUSTER_SERVER_COMMAND_RETENTION` | `--command-retention` | `720h` | Positive retention duration for terminal command records; purging them is what lets an expired Endpoint metadata row be removed |

### `AGENT_CLUSTER_SERVER_ENDPOINT_EXPIRY`

The Server owns expiry because it owns the persisted fleet projection. The value is a positive Go duration such as `1h`, `24h`, or `168h`; zero and negative values are rejected. A cleanup runs once at Server startup and then at a bounded interval of at most one minute.

When an Endpoint has remained offline beyond the configured duration, measured from its dedicated `offline_since_at_ms`, the Server removes its `endpoint_session_state` row so stale sessions no longer appear in `list`. The Server also removes the Endpoint metadata row when no retained command references it. If command evidence exists, the metadata row remains so historical command lookup retains its Endpoint identity. Online and recently disconnected Endpoints are never selected. This retention setting is independent of the connection heartbeat timeout and is not an Endpoint retirement or credential-revocation operation.

### `AGENT_CLUSTER_SERVER_COMMAND_RETENTION`

The Server owns command retention because it owns the command journal. The value is a positive Go
duration such as `24h`, `720h`, or `8760h`; zero and negative values are rejected. The same sweep that
expires offline Endpoints purges terminal command records older than this window, and it runs once at
Server startup and then at a bounded interval of at most one minute.

Only terminal statuses whose effect is known are purged: `finished`, `rejected`, `failed`, `expired`
and `cancelled_before_execution`. The list is an allowlist rather than a denylist, so a status added
later is retained until someone decides it is safe to delete. `unconfirmed` is deliberately excluded
even though it is terminal for polling: delivery happened and the exit was never confirmed, so an
operator investigating an unknown effect still needs the row, and it is retained until an explicit
reconciliation resolves it. In-flight statuses are never purged by age.

The purge runs before Endpoint expiry in the same sweep, so a metadata row blocked only by a
now-purgeable command is removed in that sweep instead of surviving one extra cycle. A failed purge
aborts the sweep and is logged, because reporting a partial sweep as a complete one would hide the
failure. Deleting a command row does not weaken duplicate detection: the immutable deadline, not the
stored row, is what prevents a replayed expired command from executing, because admission re-inserts
the row and immediately expires it once its deadline has passed.

### `AGENT_CLUSTER_SERVER_AUTH_TOKEN`

The built-in default `development-token` is a development convenience, not a
deployment value. A Server started without an explicit token accepts that known
string from any reachable client. Always set a real token, and restrict the API
listener to a trusted address.

### Removed Server environment names

The names below are no longer read. They were fallback aliases for one compatibility cycle, and that
cycle is over. A process that still exports one of them starts with the documented default instead of
the exported value, and no warning is printed, because the name is not read at all.

| Removed name | Replacement |
|---|---|
| `AGENT_CLUSTER_API_LISTEN_ADDR` | `AGENT_CLUSTER_SERVER_API_LISTEN_ADDR` |
| `AGENT_CLUSTER_CHANNEL_LISTEN_ADDR` | `AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR` |
| `AGENT_CLUSTER_ENDPOINT_DIAL_ADDRESSES` | `AGENT_CLUSTER_SERVER_ENDPOINT_DIAL_ADDRESSES` |
| `AGENT_CLUSTER_TLS_SHARED_CERTIFICATE` | `AGENT_CLUSTER_SERVER_TLS_SHARED_CERTIFICATE` |
| `AGENT_CLUSTER_AUTH_TOKEN` | `AGENT_CLUSTER_SERVER_AUTH_TOKEN` |
| `AGENT_CLUSTER_SERVER_NAME` | `AGENT_CLUSTER_TLS_SERVER_NAME` |

## Endpoint

| Variable | Flag | Default | Purpose |
|---|---|---|---|
| `AGENT_CLUSTER_ENDPOINT_ID` | `--endpoint-id` | empty | Endpoint identity announced to the Server |
| `AGENT_CLUSTER_ENDPOINT_INSTANCE_ID` | `--instance-id` | `default` | Endpoint instance identity |
| `AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS` | `--channel-address` | empty | Server WSS address the Endpoint dials; unused in the `server-initiated` direction |
| `AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESSES` | `--channel-addresses` | empty | Ordered comma-separated Server WSS addresses the Endpoint tries in turn; the first reachable one wins, and it takes precedence over `AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS` when both are set |
| `AGENT_CLUSTER_ENDPOINT_CHANNEL_LISTEN_ADDR` | `--endpoint-channel-listen-addr` | empty | mTLS listen address the Endpoint accepts the Server on in the `server-initiated` and `bidirectional` directions |
| `AGENT_CLUSTER_ENDPOINT_HEARTBEAT_ACK_TIMEOUT` | `--heartbeat-ack-timeout` | `3s` | Positive duration one heartbeat waits for the Server's acknowledgement; a heartbeat that is not acknowledged within this bound counts as one failure |
| `AGENT_CLUSTER_ENDPOINT_UNHEALTHY_WINDOW` | `--unhealthy-window` | `30s` | Positive duration of consecutive unacknowledged heartbeats after which the Endpoint declares the Server unhealthy and closes the connection so the ordered address list is walked again |
| `AGENT_CLUSTER_ENDPOINT_ADAPTERS` | none | empty | JSON array of adapter bindings |
| `AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE` | `--command-allowlist-file` | empty | Endpoint-global command allowlist file |
| `AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR` | `--endpoint-access-policy-dir` | empty | Endpoint-local directory holding one access policy file per caller token; empty means every caller is permitted |
| `AGENT_CLUSTER_ENDPOINT_REPLACE_REQUEST_FILE` | `--replace-request-file` | empty | Endpoint-local request document that activates one Provider CLI version for one adapter; empty disables activation entirely |
| `AGENT_CLUSTER_ENDPOINT_COLLECTION_DELAY_MS` | none | `5000` | Positive post-collection delay in milliseconds; launcher value is `COLLECTION_DELAY_MS` |
| `AGENT_CLUSTER_ENDPOINT_SOURCE_CACHE_EXPIRY` | none | `10m` | Positive duration retaining each Adapter's last successful source snapshot; older source cache is deleted before collection, while resource mappings and command evidence are preserved; launcher value is `SOURCE_CACHE_EXPIRY` |

### `AGENT_CLUSTER_ENDPOINT_HEARTBEAT_ACK_TIMEOUT` and `AGENT_CLUSTER_ENDPOINT_UNHEALTHY_WINDOW`

These two values are the Endpoint's only bounded judgement of whether the Server it
is attached to is still alive. Before they existed the Endpoint had no such
judgement at all: the channel read had no deadline, so a Server whose process stayed
up but whose application stopped answering produced no error, and the Endpoint
stayed attached to it forever. A Server that exits or is killed is a different
failure, because the closed socket makes the read fail immediately.

The rule is consecutive failures, not a single one. Every heartbeat must be
acknowledged within `AGENT_CLUSTER_ENDPOINT_HEARTBEAT_ACK_TIMEOUT`; an
unacknowledged heartbeat counts as one failure and resets on the next acknowledged
one. When the accumulated unacknowledged time reaches
`AGENT_CLUSTER_ENDPOINT_UNHEALTHY_WINDOW`, the Endpoint declares the Server
unhealthy, logs `heartbeat acknowledgement timed out`, and closes the connection.
Closing is the whole mechanism: the channel loop already treats a read error as
transport loss and reconnects through the ordered address list, so the Endpoint
walks back to the first reachable Server without any additional switch-back logic.

The acknowledgement timeout is deliberately shorter than the heartbeat interval, so
one slow acknowledgement is attributed to that beat instead of being confused with
the next one. The unhealthy window is deliberately longer than one beat, so a single
lost acknowledgement does not move a healthy Endpoint off a working Server.

Both values must be positive. A zero or negative value is rejected at startup rather
than silently disabling the rule, because a disabled rule is indistinguishable from
a healthy Server.

### `AGENT_CLUSTER_ENDPOINT_REPLACE_REQUEST_FILE`

Names the Endpoint-local document that asks the running Endpoint to activate one
Provider CLI version for one `adapter_id`. An empty value is fail-closed: an
Endpoint that names no file cannot be asked to swap the program it runs, so
activation is unavailable rather than silently permitted.

Activation is reachable only from this local file, never from a Server payload.
A Provider CLI version is an Endpoint deployment detail, and the Cluster contract
deliberately does not model it, so no remote request can change which executable
an Endpoint runs.

The file is watched while the Endpoint runs. A consumed request logs
`consumed replace request`; a successful activation logs
`activated provider cli version` with the adapter, request ID, previous and
effective version, effective revision, in-flight count and whether the change was
reverted; a failed activation logs `activate provider cli version` with the
adapter, request ID and error. A file that cannot be watched stops the Endpoint at
startup instead of leaving activation silently unavailable.

On the launcher side the matching `node.conf` entry is `REPLACE_REQUEST_FILE`,
which `agent-clusterctl` forwards as `--replace-request-file`.
`agent-clusterctl replace --adapter <id> --executable <path>` writes the request
and signals the Endpoint, and `agent-clusterctl doctor` prints the configured path
or `<disabled>`. The activation and rollback procedure itself is described in
`docs/agent-cluster-adapters.md` under Adapter implementations and is not repeated
here.

### `AGENT_CLUSTER_ENDPOINT_ADAPTERS`

A JSON array. Each element carries `adapter_id`, `provider_type`, `command`,
optional `args`, `timeout_ms` and optional `capabilities`. The `command` must be an
absolute path that exists on the node. An empty array is accepted: it configures the
Endpoint with no Adapter, which is the state a fresh install and a Provider CLI
rollout both pass through. Parsing rejects duplicate adapter IDs, a relative command
path and a non-positive timeout.

Adapters are supplied through the environment because no flag exists for them. The
launcher exports this variable from the `ADAPTERS` configuration entry.

`provider_type` must name a registered Adapter implementation. Exactly one is registered:
`genericcli`, the Generic CLI Adapter. Any other value, including the removed `topsailai`, `fixture`
and `command` names, is refused at Endpoint startup rather than falling back to a removed adapter.

`command` is the installed Provider CLI payload, not a business CLI. The provider package installs one
immutable directory per version under `/opt/agent-cluster/providers/<provider-type>/<package-version>/`,
so the path carries the version and cannot be derived from this document. List the installed versions
on the node and use the newest:

```text
ls -1dt /opt/agent-cluster/providers/topsailai/*/
```

The Endpoint package neither depends on nor recommends any Provider package, so a node may run with
zero Adapters and a Provider may be installed, upgraded or removed without touching the Endpoint. A
Provider is activated or rolled back per `adapter_id` through `agent-clusterctl replace`, which selects
a previously verified immutable version without restarting the Endpoint.

### Removed Endpoint environment names

The names below are no longer read. They were fallback aliases for one compatibility cycle, and that
cycle is over. A process that still exports one of them starts with the documented default instead of
the exported value, and no warning is printed, because the name is not read at all.

| Removed name | Replacement |
|---|---|
| `AGENT_CLUSTER_INSTANCE_ID` | `AGENT_CLUSTER_ENDPOINT_INSTANCE_ID` |
| `AGENT_CLUSTER_CHANNEL_ADDRESS` | `AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS` |
| `AGENT_CLUSTER_ADAPTERS` | `AGENT_CLUSTER_ENDPOINT_ADAPTERS` |
| `AGENT_CLUSTER_COMMAND_ALLOWLIST_FILE` | `AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE` |
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

### Control actions

The `ctl.<action>` family is advertised from the adapter document, not from an
Endpoint-local catalog. Each `ctl.` capability listed in `ADAPTERS` is one action
this node serves, and the Provider CLI that implements it owns the argv, the
payload schema and the safety class. The Endpoint keeps the operator decision: the
`required_permission` in the adapter document is what a caller must hold, and a
provider-declared permission is ignored rather than trusted.

An adapter document that names no `ctl.` capability advertises none and refuses
every `ctl.` operation. That is the fail-closed default, not an error: an Endpoint
cannot be talked into running an action nobody configured.

The former key `AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE` and its flag
`--control-action-file` are no longer read. A `node.conf` that still carries
`CONTROL_ACTION_FILE` is harmless rather than an error, and the shipped template no
longer sets it. The catalog file itself is now Provider-side configuration: the
TopsailAI Provider CLI reads `AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS` at its own
process boundary, so the action surface stays an operational decision without the
Endpoint parsing a provider argv template.

`AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS` is resolved by the packaged launcher
before the Endpoint starts, so a relative value in `node.conf` is read relative to
the role configuration directory rather than to whatever directory the controller
was invoked from. The launcher then exports the resolved value, because the Provider
CLI inherits the Endpoint process environment and no flag carries this setting.
`agent-clusterctl doctor` prints the resolved value as `catalog`, so an operator can
see it before starting the node. A value that names a file the Provider cannot read
is a failed launch rather than a lost capability: the Provider exits, and the
Endpoint refuses to start when the Provider cannot describe itself.

`AGENT_CLUSTER_TOPSAILAI_EXECUTABLE` names the TopsailAI business CLI the Provider
invokes. It must be an absolute path. The Provider falls back to the bare name
`topsailai` and resolves it from `PATH`, and `PATH` belongs to the shell that
launched the controller rather than to the node configuration. The same package set
therefore collected on one node and failed on another with
`exec: "topsailai": executable file not found in $PATH`, and the only symptom was a
stale inventory: the Endpoint stayed online, the adapter stayed `healthy`, and the
collection status was `failed`. The launcher does not resolve this value, because it
is a Provider setting rather than a path inside the product root; it is exported
from `node.conf` unchanged, so write it as an absolute path.

## Provider package

The Provider CLI package is optional and independent of every role package. Its
maintainer script bounds how many superseded versions stay on disk, so an upgrade
does not fill the node and a rollback still has a version to select. These two
settings are read by `scripts/deb/postinst.provider` at install time, not by the
Endpoint process, so they are not part of the Endpoint table above.

| Variable | Default | Purpose |
|---|---|---|
| `AGENT_CLUSTER_PROVIDER_RETENTION_COUNT` | `2` | Total versions kept on disk, including the installed one; the default keeps the installed version plus one previous version for a rollback |
| `AGENT_CLUSTER_PROVIDER_RETENTION_DAYS` | `30` | Age in days at which a superseded version is removed even when the count limit still has room |

Both are overridable at install time, because a site that rolls back often needs
more history and a small disk needs less. A value that is not a positive integer
warns and falls back to the default rather than deleting anything, so a typo cannot
turn into an unbounded delete.

The version the package just installed is never removed: removing it would leave the
package installed with no payload. Superseded versions are visited newest-first, so
the count limit keeps the most recent ones, and each removal is logged with the
version name, its age and how many newer versions were kept.

Installing a Provider CLI is not the same as activating it. The script never selects
a version for an Adapter: activation is a per-adapter decision made through
`agent-clusterctl replace`, described in `docs/agent-cluster-adapters.md` under
Adapter implementations.

## Client

The operator CLI reads these variables at its own process boundary. They are not
read by the Server or the Endpoint, so a bundle deployment configures them per
operator rather than per node. History settings have no flags; the environment or
CLI configuration files override their built-in defaults.

| Variable | Flag | Default | Purpose |
|---|---|---|---|
| `AGENT_CLUSTER_CLI_SERVER_URL` | `--server-url` | `http://127.0.0.1:8080` | Server API URL the CLI connects to |
| `AGENT_CLUSTER_CLI_SERVER_TOKEN` | `--token` | empty | Bearer token the CLI presents to the Server |
| `AGENT_CLUSTER_CLI_SERVER_PROFILES` | none | empty | Comma-separated `name=url` map defining named Server profiles |
| `AGENT_CLUSTER_CLI_SERVER_PROFILE_TOKENS` | none | empty | Comma-separated `name=token` map giving each profile its bearer token |
| `AGENT_CLUSTER_CLI_SERVER_PROFILE` | `--server-profile` | empty | Profile name to select when no flag is given |
| `AGENT_CLUSTER_CLI_ENDPOINT_TOKENS` | `--endpoint-token` for one selected Endpoint | empty | Comma-separated `endpoint_id=token` map used for Endpoint authorization |
| `AGENT_CLUSTER_CLI_HISTORY_FILE` | none | `${HOME}/.topsailai/.topsailai_agent_cluster.history.jsonl` | Persistent JSONL file for accepted interactive input |
| `AGENT_CLUSTER_CLI_HISTORY_MAX_ENTRIES` | none | `100` | Maximum trailing history records read at startup and maximum commands retained for Up/Down recall |
| `AGENT_CLUSTER_CLI_HISTORY_MAX_SIZE_MB` | none | `1` | Maximum active history-file size before rotation |
| `AGENT_CLUSTER_CLI_HISTORY_MAX_BACKUPS` | none | `1` | Maximum retained rotated history files |

`AGENT_CLUSTER_CLI_SERVER_TOKEN` has no built-in default, unlike the Server's development
token. A CLI started without it omits the `Authorization` header entirely, so the
Server rejects the request instead of the client silently using a known development
value.

A Server profile is one URL and one token under one name, because the two are a single
credential pair rather than two independent settings. An operator who moves an Endpoint
to a different Server has to change both at once, and changing them separately is how
one Server's token ends up being presented to another Server.

```shell
AGENT_CLUSTER_CLI_SERVER_PROFILES='primary=http://127.0.0.1:8080,secondary=https://other.example.test'
AGENT_CLUSTER_CLI_SERVER_PROFILE_TOKENS='primary=token-a,secondary=token-b'
AGENT_CLUSTER_CLI_SERVER_PROFILE=secondary
```

The selection may come from `AGENT_CLUSTER_CLI_SERVER_PROFILE` or from
`--server-profile`; the flag wins, so one invocation can override a script's choice
without editing the environment. A profile cannot be combined with an explicit
`--server-url` or `--token`: that combination is refused rather than merged, because a
stale flag in a shell alias would silently redirect the profile's token to a different
machine and nothing in the output would show that the pair had been split. The
environment defaults for those two settings are not a conflict, because they are the
fallback for an invocation that selects no profile.

A token configured for a profile that has no URL is rejected at load time. The
alternative is a later "unknown profile" failure that describes the symptom while the
configured token sits unused. A profile with no token is valid and yields an empty
token, which means the CLI omits the `Authorization` header rather than inventing a
default.

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
blank component-owned name as unset and uses the built-in default. An empty
`AGENT_CLUSTER_CLI_SERVER_URL` therefore suppresses that key in later files and
selects the built-in URL. An empty `AGENT_CLUSTER_CLI_SERVER_TOKEN` selects no token,
so the CLI sends no `Authorization` header.

The built-in URL default is `http://127.0.0.1:8080`, while the shipped Server
configuration listens on `127.0.0.1:53680`. An unconfigured CLI therefore fails to
connect rather than reporting that it is unconfigured.

The following names are no longer read. They were fallback aliases for one compatibility cycle, and
that cycle is over. A CLI that still exports one of them uses the built-in default instead, and no
warning is printed, because the name is not read at all.

| Removed name | Component-owned name |
|---|---|
| `AGENT_CLUSTER_SERVER_URL` | `AGENT_CLUSTER_CLI_SERVER_URL` |
| `AGENT_CLUSTER_CLI_TOKEN` | `AGENT_CLUSTER_CLI_SERVER_TOKEN` |
| `AGENT_CLUSTER_TOKEN` | `AGENT_CLUSTER_CLI_SERVER_TOKEN` |
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
| `AGENT_CLUSTER_CLI_SERVER_TOKEN` | The CLI omits the `Authorization` header and every request is rejected |
| `AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE` | `command.exec` is unavailable |
| `AGENT_CLUSTER_ENDPOINT_ADAPTERS` with no `ctl.` capability | No `ctl.` action is advertised and every `ctl.` operation is refused |
| `AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR` | Every caller is permitted, so the Endpoint has no authorization boundary |
| `AGENT_CLUSTER_TLS_*` | Remote listeners cannot verify peers |
| `AGENT_CLUSTER_ENDPOINT_ADAPTERS` | The Endpoint has no provider to collect from |

## Related documents

- `docs/agent-cluster-architecture.md`: security baseline, authority model and the implemented
  container deployment.
- `docs/agent-cluster-protocol.md`: `ctl.<action>` and `command.exec` operations.
- `conf/node.server.conf.example` and `conf/node.endpoint.conf.example`: launcher
  configuration examples.
