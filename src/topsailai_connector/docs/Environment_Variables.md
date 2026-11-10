---
maintainer: AI
author: DawsonLin
status: decided
created: 2026-11-10
updated: 2026-11-10
---

# Environment Variables

## Status

Both binaries read their configuration from the environment. The Server validates
its two secrets and its listen address; the Node validates its server URL and its
tunnel token, then loads the policy file and opens every scope the policy defines.
Neither binary opens a socket yet, so the variables that configure the listener,
the CLI and the log are decided but unread. Each such section says so.

The sections below separate what is implemented from what is decided. A decided
variable is a decision, not a promise that the name is final; it is listed so a
later change has a name to argue against instead of inventing a second one.

## Configuration precedence

Configuration is resolved in one place, at startup, in this order:

1. Environment variable.
2. Built-in default.

There is no command-line flag for a configuration value and no configuration
file, because a second source of the same value is a second place for the two to
disagree. The flags that exist select a subcommand; they do not override a
variable. A value that has no default is required, and an absent required value
fails startup instead of falling back.

A value is read once at the boundary and converted into a typed field, then passed
downward as a parameter. No package below the entry point reads the environment,
because a function that reads a global variable hides its own dependencies and
cannot be tested without mutating process state. `LoadConfig` therefore takes a
`lookup func(string) string` rather than calling `os.Getenv` itself, so a test
supplies a fixed environment without touching the process.

## Secrets in the environment: an accepted trade-off

The Server's two secrets, `CONNECTOR_SERVER_TUNNEL_TOKEN` and
`CONNECTOR_SERVER_CLIENT_TOKEN`, are read from the environment. That is a
deliberate decision by the human, and it is recorded here with its cost rather
than presented as a best practice.

An environment variable is a weak place for a secret, for four concrete reasons:

- It is visible in `/proc/<pid>/environ` to the same user and to root, for the
  whole life of the process.
- It is inherited by every child process, so a helper that has no business holding
  a secret receives one anyway.
- It appears in `docker inspect`, in a systemd unit file, in a CI log and in a
  crash dump, all of which are copied and archived far more casually than a file
  with restrictive permissions.
- It cannot be rotated without restarting the process, so the practical response
  to a suspected leak is to keep using the old value.

The trade-off is accepted because the alternative is worse for this deployment: a
Server that reads its secrets from files needs a provisioning step, a file
permission audit and a path configuration for every deployment, and the most
likely failure is a missing file that the operator works around by disabling
authentication. An environment variable that is absent fails startup loudly, which
is the behaviour that matters most.

What the decision does **not** change:

- The secrets are still never logged, never written to a config file, never echoed
  by a configuration dump and never placed in a URL.
- The Node's `node-token` is **not** an environment variable on the Server. It is
  never configured there at all, because the Server must never learn it.
- The Node's own `node-id.node-token` lives in the Node's config directory with
  `0600` on POSIX and an owner-only ACL on Windows, because it is per-Node and
  long-lived and there is no reason to put it in the environment.

A deployment that must not use environment variables for secrets can pass them
through a systemd `EnvironmentFile=` with `0600` permissions, which is a file with
restrictive permissions that the process manager reads. That is a deployment
choice, not a change to the contract.

## Implemented

Both binaries now read their configuration from the environment. The flags below
are the only command-line options, and they select a subcommand rather than
override a variable:

| Binary | Subcommand | Meaning |
|---|---|---|
| `connector-server` | `run` (default) | Load and validate the configuration, then wait for a signal |
| `connector-node` | `run` (default) | Load the configuration, the policy and the identity, then wait for a signal |
| `connector-node` | `id` | Print the `node-id.node-token` pair and nothing else |
| `connector-node` | `regenerate` | Replace the pair; `--keep-id` keeps the node id |
| `connector-server` | `cli` | Call one operation on one Node and print the result |

The Server validates `CONNECTOR_SERVER_TUNNEL_TOKEN` and
`CONNECTOR_SERVER_CLIENT_TOKEN` at startup and refuses to run when either is
missing, empty, padded with whitespace or shorter than 16 bytes. The Node
validates `CONNECTOR_NODE_SERVER_URL` and `CONNECTOR_NODE_TUNNEL_TOKEN` the same
way, then loads the policy file and opens every scope it defines.

Neither binary listens on a socket yet. The Server reports that it is not
listening rather than pretending to serve, because a process that prints
"starting" and then accepts nothing is a process an operator will believe.

## Reference

Every name carries the `CONNECTOR_` prefix, which is the project code from
`project.yaml`. A variable is named for what it holds rather than for where it is
used, so a reader can guess the meaning without opening the code.

The Server, Node and CLI sections below are implemented. The "Shared" section is
not: those variables are named but read by nothing, and the section says so.

### Server

| Variable | Default | Purpose |
|---|---|---|
| `CONNECTOR_SERVER_LISTEN` | `:8443` | Address the Server listens on. One listener serves both the channel at `/channel` and the CLI API at `/v1/`, so there is no second port to configure |
| `CONNECTOR_SERVER_TLS_CERT` | none | Path to the TLS certificate. Required unless TLS is terminated in front of the Server |
| `CONNECTOR_SERVER_TLS_KEY` | none | Path to the TLS private key. A path, not the key itself |
| `CONNECTOR_SERVER_TUNNEL_TOKEN` | none | The secret a Node must present in `hello` to open a channel. Required, and an absent or empty value fails startup |
| `CONNECTOR_SERVER_CLIENT_TOKEN` | none | The secret a CLI must present on every request. Required, and an absent or empty value fails startup |
| `CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS` | `30` | How long the Server waits for a Node response before reporting `node_timeout` |

`CONNECTOR_SERVER_TUNNEL_TOKEN` and `CONNECTOR_SERVER_CLIENT_TOKEN` are the only
two secrets the Server reads, and they are read from the environment by explicit
human decision. The cost of that choice is stated in "Secrets in the environment:
an accepted trade-off" above rather than argued away.

The Server has **no** variable for a Node's `node-token`, because the Server must
never learn it. There is no `CONNECTOR_SERVER_NODE_TOKEN`, no
`CONNECTOR_SERVER_NODE_TOKENS_FILE` and no equivalent. A deployment that tries to
configure one has misunderstood the model: the Server forwards the `node-token`
without knowing whether it is correct.

### Node

| Variable | Default | Purpose |
|---|---|---|
| `CONNECTOR_NODE_SERVER_URL` | none | Server channel address. Required |
| `CONNECTOR_NODE_TUNNEL_TOKEN` | none | The `tunnel_token` this Node presents in `hello`. Required |
| `CONNECTOR_NODE_CONFIG_DIR` | platform config directory | Where the Node keeps its identity file and policy file |
| `CONNECTOR_NODE_POLICY_FILE` | `<config>/policy.yaml` | Path to the policy file. A missing file is a startup failure |

The Node's identity — the `node-id.node-token` pair — is **not** an environment
variable. It lives in `<config>/identity` with `0600` on POSIX and an owner-only
ACL on Windows, because it is per-Node, long-lived and regenerable, and because a
value that the Node rewrites itself belongs in a file the Node owns rather than in
the environment of whatever process launched it.

The Node's config directory is created with `0700` on POSIX and an owner-only ACL
on Windows, because it holds the `node-token`. A scope whose root is inside this
directory, or which contains it, is refused at startup.

#### `CONNECTOR_NODE_POLICY_FILE` validation and failure modes

The policy file is the only place a scope is defined and a permission granted, so
every problem with it is a startup failure. A Node that started with a broken
policy would be a Node whose operator believes it is serving something it is not,
and the failure would surface as a refusal at the first request instead of at the
moment the mistake was made.

The value is resolved in this order: the variable when it is set and non-empty,
otherwise `<config>/policy.yaml`. A relative path is refused, because a relative
path resolves against whatever directory the process happened to inherit, so the
same configuration would load a different file under a different launcher.

| Condition | Result |
|---|---|
| Variable unset or empty | Falls back to `<config>/policy.yaml` |
| Path is relative | Startup failure |
| File does not exist | Startup failure (`policy file is missing`) |
| Path is a directory | Startup failure |
| File is empty | Startup failure; an empty file is not an empty policy |
| File exceeds 1 MiB | Startup failure, checked before decoding |
| Malformed YAML | Startup failure |
| More than one YAML document | Startup failure; only the first would be read |
| Unknown top-level key | Startup failure; a misspelt key would otherwise be ignored |
| Unknown key inside a scope | Startup failure |
| Missing `version` or an unknown version | Startup failure |
| Scope name that is not an identifier | Startup failure |
| Scope with no `path` | Startup failure |
| Grant naming an undefined scope | Startup failure |
| Unknown permission name | Startup failure |
| Duplicate permission in one grant | Startup failure |
| Scope path that does not exist | Startup failure |
| Scope path that is a file, not a directory | Startup failure |
| Scope path inside the config directory, or containing it | Startup failure |
| Any scope failing to open | Startup failure; already-opened scopes are closed first |

The last row is the one that matters most: scopes are opened one at a time, and a
failure closes the ones already opened before returning. A half-open Node that
kept serving the scopes that happened to work would be a Node whose reachable
surface depends on which directory was missing.

The 1 MiB cap is applied to the file size before decoding, not to the decoded
result, because a decoder that is asked to read an unbounded file has already lost
the argument. A policy is a short configuration; a policy file measured in
megabytes is a mistake or an attack, and both are refused the same way.

### CLI

The CLI is a subcommand of the Server binary, so these variables are read by the
same executable under a different subcommand. They are listed separately because
they configure the client role, not the Server role.

| Variable | Default | Purpose |
|---|---|---|
| `CONNECTOR_CLI_SERVER_URL` | none | Server HTTP address the CLI calls. Required |
| `CONNECTOR_CLI_CLIENT_TOKEN` | none | The `client_token` the CLI presents on every request. Required |
| `CONNECTOR_CLI_NODE` | none | The `node-id.node-token` pair the CLI addresses. Required |

`CONNECTOR_CLI_NODE` holds the **whole pair**, not the two halves separately. The
CLI splits it on the first dot before sending: the `node-id` goes into the URL path
and the `node-token` goes into `X-Connector-Node-Token`. Splitting in the CLI rather
than asking the operator for two variables means the two halves cannot be configured
out of step with each other, which is the failure mode that would otherwise produce
a request addressed to one Node carrying another Node's secret.

Both `CONNECTOR_CLI_CLIENT_TOKEN` and `CONNECTOR_CLI_NODE` are accepted from the
environment for scripting convenience. A flag takes precedence over the variable,
because a flag is the more explicit statement of intent. There is no config file
for the CLI: the only two sources are a flag and the environment, so an operator
never has to work out which of three places won.

Neither value is ever echoed by `--help`, by an error message or by a verbose dump.
`cli.Describe` renders a request with both secrets replaced by a fixed marker and
the `node-id` printed in full, because the identifier is the public half of the
pair and an operator debugging a routing problem needs to see it.

A long-lived credential in the environment is inherited by every child process, so
a flag is the safer choice for interactive use. The environment exists so a script
can export the pair once instead of repeating it on every call.

### Shared (decided, not yet read)

None of these is read by any code today. They are listed so a later change has a
name to argue against instead of inventing a second one, and the section is marked
because a variable documented as implemented and read by nothing is a variable an
operator will set and expect to work.

| Variable | Default | Purpose |
|---|---|---|
| `CONNECTOR_LOG_LEVEL` | `info` | `debug`, `info`, `warn` or `error` |
| `CONNECTOR_LOG_MAX_SIZE_MB` | `100` | Size at which the log file rotates |
| `CONNECTOR_LOG_MAX_BACKUPS` | `10` | Number of rotated log files kept |
| `CONNECTOR_LOG_MAX_AGE_DAYS` | `30` | Age after which a rotated log file is removed |
| `CONNECTOR_MAX_RESPONSE_BYTES` | `262144` | Cap on a single response payload, so one read cannot exhaust memory |

`CONNECTOR_MAX_RESPONSE_BYTES` is the one exception in spirit: the cap exists and
is enforced, but it is a constant (`node.MaxResponseBytes`) rather than a variable,
because a cap an operator can raise is a cap that will be raised. Making it
configurable is a decision for the version that needs a larger read, not a default.

There is no `CONNECTOR_TOKEN_LEEWAY_SECONDS`, because no secret in this model
carries an expiry and therefore no clock comparison happens. A variable that
configured a leeway would be a variable that configured nothing.

## Validation

A configuration value is validated at startup and a bad value fails startup rather
than falling back to a default. A silent fallback is how a deployment ends up
running with a value nobody chose.

| Value | Rejected when |
|---|---|
| Any duration or size | Negative, zero where zero is meaningless, or not a number |
| `CONNECTOR_SERVER_TUNNEL_TOKEN`, `CONNECTOR_SERVER_CLIENT_TOKEN` | Absent or empty, because an unset secret is the most likely way to accidentally disable authentication. There is no "authentication disabled" mode to fall back to |
| `CONNECTOR_NODE_TUNNEL_TOKEN`, `CONNECTOR_CLI_CLIENT_TOKEN` | Absent or empty, for the same reason |
| `CONNECTOR_CLI_NODE` | No dot, an empty half, a second dot in the token half, or a `node-id` without the `node_` prefix. Whitespace is refused rather than trimmed |
| `CONNECTOR_MAX_RESPONSE_BYTES` | Zero or above a hard ceiling, because an unbounded cap is not a cap |
| `CONNECTOR_LOG_MAX_SIZE_MB`, `CONNECTOR_LOG_MAX_BACKUPS` | Zero, because a rotation policy of zero either never rotates or deletes the active file |
| A `*_FILE` path | Empty, or pointing at a file that does not exist, or readable by a group or other user on POSIX |
| `CONNECTOR_LOG_LEVEL` | Not one of the four names, because a typo would otherwise silently select the default |

A secret is validated for **presence and shape only**, never for correctness. The
Server cannot tell whether `CONNECTOR_SERVER_TUNNEL_TOKEN` is the value a Node
holds, because it has nothing to compare against beyond the value it was given. The
only correctness check that exists is the comparison at request time, and it
produces one error for every kind of mismatch.

## Log rotation

**Not implemented.** Neither binary writes a log file. Both write to standard error
through `log.Printf`, which the process supervisor is expected to capture and
rotate. The `CONNECTOR_LOG_*` variables above are decided but unread.

The intended design, recorded so the eventual implementation has a target: rotation
happens in application code rather than through `logrotate`, because the Node runs
on Windows where `logrotate` does not exist and because a rotation policy that lives
outside the binary is a policy the binary cannot report on. Rotation events are
themselves logged, so an operator can tell a quiet log from a broken one.

This section previously stated that rotation was implemented. It was not, and the
claim was wrong in the direction that matters: an operator reading it would have
assumed a size bound existed and left a log to grow without one.

## Related documents

- `docs/permission-design.md` — the three-secret contract, the `node-id.node-token`
  pair format and the policy file schema.
- `docs/API.md` — the CLI HTTP API.
- `docs/cases/` — the test cases, including the adversarial ones that exercise the
  secret checks described here.
