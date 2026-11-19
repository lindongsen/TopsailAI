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
its tunnel token, loads its client credential file and its listen address, then
binds one listener that serves the channel and the CLI API. The Node validates its
server URL and its tunnel token, loads its credential file and the policy file,
opens every scope the policy defines, and dials the Server. The CLI subcommand
calls the Server over HTTP. The variables that configure the log are decided but
unread, and that section says so.

The sections below separate what is implemented from what is decided. A decided
variable is a decision, not a promise that the name is final; it is listed so a
later change has a name to argue against instead of inventing a second one.

## Configuration precedence

Configuration is resolved in one place, at startup, in this order:

1. Environment variable.
2. Value compiled into the binary, when the binary was built with the
   configuration embedded, which is the default for `make package`.
3. Built-in default.

The Server and the Node have **no** command-line flag for a configuration value
and no configuration file, because a second source of the same value is a second
place for the two to disagree. Their flags select a subcommand and nothing else. A
value that has no default is required, and an absent required value fails startup
instead of falling back.

The CLI is the deliberate exception: it accepts a flag for each of its four
values, and a flag wins over the variable. The reason is that a CLI invocation is
a single explicit act rather than a long-lived process, so stating the value on
the command line is the clearer statement of intent, and a script that already
holds a credential can pass it without exporting it into the environment of every
child process. The precedence is stated once, in the CLI section below, so an
operator never has to work out which of three places won.

The embedded values sit below the environment on purpose: an operator who has to
repoint one binary at another Server can do it without a rebuild, and a rebuild is
the only way to change the policy because a policy is a whole document rather than
a single value. A binary that embedded a policy therefore **refuses**
`CONNECTOR_NODE_POLICY_FILE` instead of letting a file path silently replace every
scope and every grant.

A value is read once at the boundary and converted into a typed field, then passed
downward as a parameter. No package below the entry point reads the environment,
because a function that reads a global variable hides its own dependencies and
cannot be tested without mutating process state. `LoadConfig` therefore takes a
`lookup func(string) string` rather than calling `os.Getenv` itself, so a test
supplies a fixed environment without touching the process.

## Secrets in the environment: an accepted trade-off

The Server's tunnel token, `CONNECTOR_SERVER_TUNNEL_TOKEN`, is read from the
environment. That is a deliberate decision by the human, and it is recorded here
with its cost rather than presented as a best practice.

The client credentials are **not** in the environment. They live in the file named
by `CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE`, because there can be several of them
and an environment variable holds one value. A set of credentials also has to be
rotated one entry at a time, which a single variable cannot express.

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

The trade-off is accepted for the tunnel token because the alternative is worse for
this deployment: a Server that reads it from a file needs a provisioning step, a
file permission audit and a path configuration for every deployment, and the most
likely failure is a missing file that the operator works around by disabling
authentication. An environment variable that is absent fails startup loudly, which
is the behaviour that matters most.

What the decision does **not** change:

- No secret is ever logged, written to a config file, echoed by a configuration
  dump or placed in a URL.
- The Node's credential secret is **not** an environment variable on the Server. It
  is never configured there at all, because the Server never receives it. The
  Server forwards the node proof, which is a signature, not a secret.
- The Node's own credential file lives in the Node's config directory with `0600`
  on POSIX. On Windows the file carries no explicit ACL: it inherits the default
  descriptor of its parent directory, which grants read access to `BUILTIN\Users`
  and therefore to every local account. See "Windows file protection" below.

A deployment that must not use environment variables for secrets can pass the
tunnel token through a systemd `EnvironmentFile=` with `0600` permissions, which is
a file with restrictive permissions that the process manager reads. That is a
deployment choice, not a change to the contract.

## Implemented

Both binaries read their configuration from the environment. The subcommands below
are the only command-line entry points. A subcommand selects a role; the only
flags that carry a value are the CLI's four connection values and the `--key-id`
that names a credential, and both are described in their own sections.

| Binary | Subcommand | Meaning |
|---|---|---|
| `connector-server` | `run` (default) | Load and validate the configuration, bind the listener and serve until a signal arrives |
| `connector-node` | `run` (default) | Load the configuration, the policy, the identity and the credentials, dial the Server and serve until a signal arrives |
| `connector-node` | `id` | Print the node id and nothing else. Reads only `CONNECTOR_NODE_CONFIG_DIR` |
| `connector-node` | `regenerate` | Replace the node id and print it. Leaves every credential untouched. Reads only `CONNECTOR_NODE_CONFIG_DIR` |
| `connector-node` | `credential add` | Generate one caller credential, append it to the credential file and print it once. `--key-id` names it; empty generates one |
| `connector-node` | `credential list` | Print the key identifiers in the credential file, never a secret |
| `connector-node` | `credential remove` | Remove one caller credential by `--key-id`. Refuses to remove the last one |
| `connector-server` | `cli` | Call one operation on one Node and print the result |

The Server validates `CONNECTOR_SERVER_TUNNEL_TOKEN` at startup and refuses to run
when it is missing, empty, padded with whitespace or shorter than 16 bytes. It also
requires `CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE` to name a readable file that
parses as a credential document, because a Server that cannot load a credential set
can verify no proof at all. The Node validates
`CONNECTOR_NODE_SERVER_URL` and `CONNECTOR_NODE_TUNNEL_TOKEN` the same way, then
loads the credential file and the policy file and opens every scope the policy
defines.

`id`, `regenerate` and the `credential` subcommands are the exception, and the
exception is deliberate. None of them dials the Server, so none requires
`CONNECTOR_NODE_SERVER_URL` or `CONNECTOR_NODE_TUNNEL_TOKEN`; all read only
`CONNECTOR_NODE_CONFIG_DIR`. The first-run order depends on this: the operator runs
`id` to learn the node id before the tunnel token exists, so a full configuration
load would make the documented order impossible. The dial path keeps the strict
load, because a Node that started without a secret would be a Node whose operator
believes it is serving something it is not.

The Server binds its listener before it logs that it is listening, so a bind
failure is reported as a startup failure instead of a process that prints
"starting" and then accepts nothing. The Node dials the Server and retries every
failure except context cancellation, a refused handshake included, pausing
`reconnectDelay` between attempts and logging `retry_in` with each one. A wrong
tunnel token therefore produces a warning every 5 seconds rather than a single
fatal line, which is the behaviour an operator actually observes.

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
| `CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE` | none | Path to the YAML file holding the client credentials the Server accepts. Required, and a missing, empty or unreadable file fails startup |
| `CONNECTOR_SERVER_REPLAY_WINDOW_SECONDS` | `60` | How far a client proof timestamp may differ from the Server's clock. At least 1, at most 600 |
| `CONNECTOR_SERVER_REPLAY_CAPACITY` | `65536` | Number of unexpired client nonces the Server records. A full cache refuses new proofs rather than evicting a live nonce |
| `CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS` | `30` | How long the Server waits for a Node response before reporting `node_timeout`. At least 1, at most 3600 |
| `CONNECTOR_SERVER_MAX_IN_FLIGHT_PER_CALLER` | `2` | How many requests one caller may have in flight at once. At least 1 |
| `CONNECTOR_SERVER_MAX_IN_FLIGHT_PER_NODE` | `4` | How many requests one Node may have in flight at once. At least 1 |
| `CONNECTOR_SERVER_MAX_IN_FLIGHT` | `64` | How many requests the whole Server may have in flight at once. At least 1 |
| `CONNECTOR_SERVER_ADMISSION_WAIT_MS` | `200` | How long a request may wait for a slot before it is refused with `overloaded`. Zero or more, at most 5000 |

The three in-flight limits answer three different questions, and one limit cannot
answer all of them. A Server-wide bound alone stops unbounded growth but lets one
caller occupy every slot, so a second caller waits behind work it did not cause. A
per-caller bound alone lets many callers aimed at one Node saturate that Node. The
per-Node bound is the one that protects the personal computer the Node runs on,
which is the machine this system exists to keep usable.

A value below one is refused at startup rather than clamped. A zero limit would
refuse every request, and a Server that refuses everything looks like a Server that
is working and denying, which is the most expensive kind of misconfiguration to
diagnose.

`CONNECTOR_SERVER_ADMISSION_WAIT_MS` is in milliseconds because the useful range is
a fraction of a second: the wait absorbs a burst, it does not queue work. A
seconds-based variable would make the smallest useful value one second, which is
already a queue. **Zero is a meaningful setting**, not "unset": it means refuse
immediately rather than wait, and it is the correct value for a deployment that
would rather answer fast than hold a request. The default is applied only when the
variable is absent, so an operator who writes `0` gets `0`.

A request that waits the full budget and still finds no slot is refused with
`overloaded` (`1010`), which is retryable. It is deliberately not `internal`
(`1009`): an internal failure is a defect and a retry repeats it, while an overload
is a temporary shortage and a retry is the correct response. Admission runs after
the client proof verifies, so an unauthenticated caller cannot occupy capacity.

`CONNECTOR_SERVER_TUNNEL_TOKEN` is the only secret the Server reads from the
environment, and it is read there by explicit human decision. The cost of that
choice is stated in "Secrets in the environment: an accepted trade-off" above
rather than argued away.

The client credentials are a **file**, not a variable, because there can be several
of them and each one is rotated on its own schedule. The file holds `key_id` and
`secret` pairs; the Server looks a credential up by the `key_id` the caller presents
and never tries every secret in turn. The file is parsed strictly, so an unknown key
is a startup failure rather than an ignored line, and it is capped at 1 MiB.

The Server has **no** variable for a Node credential secret, because the Server
never receives it. There is no `CONNECTOR_SERVER_NODE_SECRET`, no
`CONNECTOR_SERVER_NODE_CREDENTIALS_FILE` and no equivalent. A deployment that tries
to configure one has misunderstood the model: the Server forwards the node proof,
which is a signature over the request, and it cannot verify that signature because
it does not hold the secret that produced it.

### Node

| Variable | Default | Required by | Purpose |
|---|---|---|---|
| `CONNECTOR_NODE_SERVER_URL` | none | `run` | Server channel address |
| `CONNECTOR_NODE_TUNNEL_TOKEN` | none | `run` | The `tunnel_token` this Node presents in `hello` |
| `CONNECTOR_NODE_CONFIG_DIR` | platform config directory | all subcommands | Where the Node keeps its identity file, credential file and policy file |
| `CONNECTOR_NODE_CREDENTIALS_FILE` | `<config>/credentials.yaml` | `run` | Path to the caller credentials the Node accepts. A relative path is refused |
| `CONNECTOR_NODE_POLICY_FILE` | `<config>/policy.yaml` | `run` | Path to the policy file. A missing file is a startup failure |
| `CONNECTOR_NODE_REPLAY_WINDOW_SECONDS` | `60` | `run` | How far a node proof timestamp may differ from the Node's clock. At least 1, at most 600 |
| `CONNECTOR_NODE_REPLAY_CAPACITY` | `65536` | `run` | Number of unexpired node nonces the Node records. A full cache refuses new proofs rather than evicting a live nonce |

`id`, `regenerate` and the `credential` subcommands read only
`CONNECTOR_NODE_CONFIG_DIR`. They never dial, so they never need a dial target or a
tunnel token, and requiring one would make the documented first-run order
impossible.

The Node's identity and its credentials are two different values in two different
files, because they answer two different questions.

| File | Holds | Written by | Answers |
|---|---|---|---|
| `<config>/identity` | The node id, and nothing else | The Node, on first start and on `regenerate` | Which Node is this |
| `<config>/credentials.yaml` | `key_id` and `secret` pairs | The operator, through `credential add` and `credential remove` | Which callers may operate on it |

Neither is an environment variable. The identity is per-Node, long-lived and
regenerated by the Node itself, so it belongs in a file the Node owns rather than in
the environment of whatever process launched it. The credentials are a set the
operator edits, so they belong in a file with restrictive permissions rather than in
a variable that holds one value.

Splitting them is what makes `regenerate` safe: it changes the address and leaves
every credential untouched, so a caller does not have to be reissued a secret
because the Node moved. Merging them would make "change my address" and "revoke a
caller" the same operation.

The Node's config directory is created with `0700` on POSIX. A scope whose root is
inside this directory, or which contains it, is refused at startup, unless the
policy states `allow_filesystem_root: true`; in that case the deny list refuses the
directory and everything inside it, and a listing omits it.

#### Embedded configuration

This is the default packaging mode: `make package` builds a binary that carries
its configuration, so it needs no environment variable and no file. Three values
are compiled in:

| Value | Source | Overridable at runtime |
|---|---|---|
| Server channel address | `PACKAGE_SERVER_URL` | Yes, `CONNECTOR_NODE_SERVER_URL` |
| Policy document | `PACKAGE_SCOPES` or `PACKAGE_SCOPES_FILE` | **No.** `CONNECTOR_NODE_POLICY_FILE` is refused |
| `tunnel_token` | `PACKAGE_TUNNEL_TOKEN`, when set | Yes, `CONNECTOR_NODE_TUNNEL_TOKEN` |

The identity and the credentials are **not** embedded. The identity is generated on
first start, polled every second and rewritten by `regenerate`; two copies of one
binary would share a node id, and the Server's `node_id -> connection` registry
would evict the first. The credentials are a set the operator adds to and revokes
from, which a compiled-in value cannot express. The recipient therefore runs the
binary once with `id` to create the identity, and the first `run` creates one
caller credential and prints it once, exactly as with a zip bundle. `credential
add` is how a second caller is added, not a required first-run step.

The policy is stored base64 encoded. That is a **quoting** decision, not a secrecy
one: a YAML document contains newlines, quotes and spaces, and the linker splits
its argument on whitespace. The values are stored as plain text in the binary's
data section, so `strings` recovers them. A binary built this way is a credential.

Because the binary is a credential, a build that carries the `tunnel_token` adds
its own executable to the deny list. A scope that contains the binary cannot serve
it: `file.read` and `file.stat` return `denied`, and `file.list` omits it. The
entry is conditional on the token being present, so a normal build is unaffected
and an install directory stays readable.

The scope paths are written into the embedded policy exactly as they were given,
not resolved on the build host. A zip bundle resolves them when it starts, because
it runs on the target; an embedded policy is fixed at build time, so resolving
would bake the build host's filesystem into a binary meant for another machine. A
scope path that does not exist on the target is tolerated rather than refused: the
scope starts, is reported absent, and answers `not_found` until the directory
exists and the Node restarts.

#### Windows file protection

On Windows the Node sets **no** ACL on the identity file, the credential file or the
config directory. `os.MkdirAll` ignores its permission argument on Windows, and
`os.Chmod` only toggles the read-only attribute; neither writes a security
descriptor. All three therefore inherit the default descriptor of their parent
directory.

The inherited descriptor grants `BUILTIN\Users` read access, so **every local
account on the machine can read the credential file**, which holds the secrets that
authorize every operation on this Node. This was measured on Windows Server 2022
with `Get-Acl`:

```
Path   : C:\connector\config\credentials.yaml
Access : NT AUTHORITY\SYSTEM Allow  FullControl
         BUILTIN\Administrators Allow  FullControl
         BUILTIN\Users Allow  ReadAndExecute, Synchronize
```

The identity file is readable too, but it holds only the node id, which is public by
design: it is an address, not a credential. The credential file is the one that
matters, and it is the one the inherited descriptor exposes.

`checkIdentityFileMode` and `checkCredentialFileMode` do not detect this, because on
Windows the permission bits Go reports are synthesised from the read-only attribute
and carry no ownership information. Both checks are skipped there rather than
pretending to answer a question they cannot.

The consequence for an operator: on Windows, place the config directory somewhere
whose ACL is already restrictive, for example a directory whose inherited
permissions have been replaced with an owner-only descriptor. The Node does not do
this for you, and it does not warn you that it has not. On POSIX no action is
needed, because `0600` is enforced and verified at load time.

#### `CONNECTOR_NODE_POLICY_FILE` validation and failure modes

The policy file is the only place a scope is defined and a permission granted, so
almost every problem with it is a startup failure. A Node that started with a broken
policy would be a Node whose operator believes it is serving something it is not,
and the failure would surface as a refusal at the first request instead of at the
moment the mistake was made. The one exception is a scope path that does not exist
yet, which is tolerated because a policy is written before the machine is ready.

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
| Scope path that does not exist | **Not** a startup failure. The scope stays defined, keeps its grant, is reported absent at startup and answers `not_found` until the directory exists and the Node restarts |
| Scope path that is a file, not a directory | Startup failure |
| Scope path inside the config directory, or containing it | Startup failure, unless the policy states `allow_filesystem_root: true`; the deny list then protects the credential files |
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
| `CONNECTOR_CLI_CLIENT_CREDENTIAL` | none | The client credential in `key_id.secret` form. Required |
| `CONNECTOR_CLI_NODE_CREDENTIAL` | none | The node credential in `key_id.secret` form. Required |
| `CONNECTOR_CLI_NODE_ID` | none | The node id the request is addressed to. Required |

The CLI holds two credentials because it crosses two authentication boundaries, and
each boundary is verified by a different party. The client credential is signed into
the `Authorization` header, which the Server verifies and discards. The node
credential is signed into `X-Connector-Node-Auth`, which the Server forwards
unchanged and the Node verifies. Neither secret is ever transmitted: only the
signature over the request is.

The node id is a separate variable from the node credential, and that separation is
the point. The node id is an address and appears in the URL path and in every log
line; the node credential is a secret and appears nowhere. A single variable holding
both would be a value that is sometimes logged and sometimes secret, and such a value
eventually gets logged whole.

All four are accepted from the environment for scripting convenience. A flag takes
precedence over the variable, because a flag is the more explicit statement of
intent. There is no config file for the CLI: the only two sources are a flag and the
environment, so an operator never has to work out which of three places won.

No secret is ever echoed by `--help`, by an error message or by a verbose dump.
`cli.Describe` renders a request with both secrets replaced by a fixed marker, and
prints the node id and both key identifiers in full, because those are public and an
operator debugging a routing or authentication problem needs to see which Node was
addressed and which credential was used.

A long-lived credential in the environment is inherited by every child process, so a
flag is the safer choice for interactive use. The environment exists so a script can
export the credentials once instead of repeating them on every call.

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

There is no `CONNECTOR_TOKEN_LEEWAY_SECONDS`, because the freshness window is the
clock comparison and it has its own variable per verifier. A second leeway variable
would be a second answer to the same question, and the two would eventually disagree
about how stale a proof may be.

## Validation

A configuration value is validated at startup and a bad value fails startup rather
than falling back to a default. A silent fallback is how a deployment ends up
running with a value nobody chose.

| Value | Rejected when |
|---|---|
| Any duration or size | Negative, zero where zero is meaningless, or not a number |
| `CONNECTOR_SERVER_TUNNEL_TOKEN`, `CONNECTOR_NODE_TUNNEL_TOKEN` | Absent or empty, because an unset secret is the most likely way to accidentally disable authentication. There is no "authentication disabled" mode to fall back to |
| `CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE`, `CONNECTOR_NODE_CREDENTIALS_FILE` | Empty, relative, a directory, larger than 1 MiB, unreadable, malformed, holding more than one YAML document, or holding more than 32 credentials. An empty file is refused; a file that states `credentials: []` is a recorded decision and is accepted, and it refuses every caller |
| A credential value | Not in `key_id.secret` form, a key id outside `a-z0-9-_` or longer than 64 characters, or a secret shorter than 32 characters |
| `CONNECTOR_CLI_NODE_ID` | Empty, or not a node id. Whitespace is refused rather than trimmed |
| `CONNECTOR_SERVER_REPLAY_WINDOW_SECONDS`, `CONNECTOR_NODE_REPLAY_WINDOW_SECONDS` | Not a whole number of seconds, below 1, or above 600. A window measured in hours is not a freshness check |
| `CONNECTOR_SERVER_REPLAY_CAPACITY`, `CONNECTOR_NODE_REPLAY_CAPACITY` | Not a whole number, or below 1 |
| `CONNECTOR_MAX_RESPONSE_BYTES` | Zero or above a hard ceiling, because an unbounded cap is not a cap |
| `CONNECTOR_LOG_MAX_SIZE_MB`, `CONNECTOR_LOG_MAX_BACKUPS` | Zero, because a rotation policy of zero either never rotates or deletes the active file |
| A `*_FILE` path | Empty, relative, a directory, or pointing at a file that does not exist. The Node's credential file is additionally refused when a group or other user can read it on POSIX; the Server's credential file and the policy file are not mode-checked, so their permissions are the operator's responsibility |
| `CONNECTOR_LOG_LEVEL` | Not one of the four names, because a typo would otherwise silently select the default |

A secret is validated for **presence and shape only**, never for correctness. The
Server cannot tell whether `CONNECTOR_SERVER_TUNNEL_TOKEN` is the value a Node holds,
because it has nothing to compare against beyond the value it was given. The only
correctness check that exists is the comparison at request time, and it produces one
error for every kind of mismatch.

A credential is likewise validated for shape only. The Server cannot tell whether a
client credential is the one a caller holds; it looks the presented key id up and
compares the signature. An unknown key id and a wrong secret produce the same
refusal, so a caller cannot use the answer to learn which key ids exist.

## Transport and its fixed limits

The channel between the Node and the Server is a WebSocket, provided by
`github.com/gorilla/websocket v1.5.3`. It is the project's second third-party
dependency, after `gopkg.in/yaml.v3` for the policy file. The choice is recorded
here because a dependency is a decision, not an implementation detail: the
standard library has no WebSocket server, and the alternative was a hand-rolled
framing layer over a hijacked HTTP connection, which is more code to get wrong
than a library that is already widely deployed.

The CLI does **not** use the WebSocket. It calls the Server over plain HTTP JSON,
so a CLI client needs no WebSocket implementation and no long-lived connection.

The limits below are **constants, not environment variables**. A timeout an
operator can raise is a timeout that will be raised, and each of these exists to
bound a failure rather than to be tuned. They are documented so an operator can
predict behaviour instead of discovering it during an incident.

| Constant | Value | Where | Purpose |
|---|---|---|---|
| `MaxChannelMessageBytes` | 1 MiB | Server | Largest channel message accepted. A larger message is refused rather than buffered |
| `MaxFramePayloadBytes` | 1 MiB | Node | Largest frame payload accepted, matching the Server's cap so a request the Server accepted is never refused here for size alone |
| `MaxRequestBodyBytes` | 1 MiB | Server | Largest CLI request body accepted, checked before decoding |
| `MaxResponseBytes` | 256 KiB | Node | Cap on a single file read, so one read cannot exhaust memory |
| `MaxResponseBytes` (CLI) | 8 MiB | CLI | Cap on a CLI response, above the Node's cap so a legitimate answer is never truncated by the client |
| `handshakeTimeout` | 10 s | Server | How long the Server waits for `hello` after the upgrade |
| `handshakeTimeout` | 10 s | Node | How long the Node waits for `hello_confirm` |
| `writeTimeout` | 10 s | Server | Per-frame write deadline on the channel |
| `socketWriteTimeout` | 10 s | Node | Per-frame write deadline on the socket |
| `dialTimeout` | 15 s | Node | How long one connection attempt may take |
| `reconnectDelay` | 5 s | Node | Pause between connection attempts after any failed attempt, a refused handshake included |
| `shutdownTimeout` | 10 s | Server | How long a graceful shutdown waits before closing what remains |
| `maxInFlight` | 64 | Server | Requests one channel may have outstanding at once |

Two of these deserve a note because the value is not arbitrary:

- **`reconnectDelay` applies to every failed attempt, a refused handshake
  included.** `Dialer.Run` retries any error except context cancellation or a
  deadline, so a wrong tunnel token produces one warning every 5 seconds rather
  than a single fatal line. That is a deliberate trade: a laptop that sleeps and a
  Server that restarts are ordinary events, and a Node that gave up on the first
  failure would need a human to restart it. The cost is a steady warning line
  while the token is wrong, which is the signal an operator needs.
- **The Server's `http.Server` deliberately has no write timeout.** A forwarded
  request is already bounded by `CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS`, and a
  second bound would cut a slow but healthy answer short with a transport error
  instead of the `node_timeout` the caller can act on.

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

- `docs/permission-design.md` — the three-credential contract, the node identity and
  credential split, and the policy file schema.
- `docs/API.md` — the CLI HTTP API, including both proof headers.
- `docs/cases/` — the test cases, including the adversarial ones that exercise the
  secret checks described here.
