---
name: connector-server-operations
description: Use when an operator needs to deploy, configure, run, monitor, rotate secrets for, package or troubleshoot the TopsailAI Connector Server in the cloud, i.e. when they ask how to start the Server, which environment variables it needs, how to rotate tunnel_token or client_token, how to expose only the channel and hide the CLI API, how to read its log, why a Node cannot connect, or how to hand a Node to someone else as a zip that unzips and starts. Covers the Server's configuration surface, its single listener with two surfaces, rotation procedure, the make package bundle and the limits that are constants rather than settings.
version: 1.0.0
author: DawsonLin
license: MIT
metadata:
  tags: [connector, server, deployment, operations, secrets, rotation, tls]
  related_skills: [connector-client, connector-node-setup]
---

# Connector Server Operations

## Overview

You are helping an operator run the **Server**: the cloud-side component that
accepts Node connections and relays CLI requests to them. The Server never dials a
Node, so it needs no inbound path to a personal computer.

Four properties of this Server shape every operational decision. Read them before
advising anything, because each one is a rule rather than a preference.

1. **The Server holds two secrets and no Node tokens.** It validates
   `tunnel_token` and `client_token`, both its own. It forwards a Node's
   `node-token` without ever learning the correct value, so it cannot validate it
   and must not claim to.
2. **The Server is not the permission authority.** It has no scope list and no
   permission list. A `denied` answer came from the Node. Nothing on the Server can
   be changed to grant access.
3. **One listener serves two surfaces.** The channel at `/channel` for Nodes, the
   CLI API at `/v1/` for operators. There is no second port to configure.
4. **Secrets are read once at startup.** There is no hot reload and no grace
   period during rotation. Rotation is a coordinated change.

## When to Use

Use this skill when the operator asks to:

- Deploy or start the Server, or write a systemd unit or container entrypoint.
- Find out which environment variables the Server needs and what each does.
- Rotate `tunnel_token` or `client_token`.
- Keep the CLI API unreachable from the internet while the channel stays open.
- Diagnose "a Node cannot connect" or "the CLI gets `node_offline`".
- Understand a limit, such as why a large read is truncated or a request times out.
- Hand a Node to someone who does not build software, as a zip they unzip and start,
  or as one executable they run with nothing to configure.

Do **not** use this skill for the client's command syntax (that is
`connector-client`) or for installing the Node (that is `connector-node-setup`).

## Build and install

```
make build
```

Binaries land in `bin/`. To install somewhere else without editing the Makefile:

```
make build BIN_DIR=/usr/local/bin
```

The Server binary is `connector-server`. It also contains the CLI as a
subcommand, so an operator who installs one binary gets both the Server and the
client. There is no separate client binary.

The Server is deployed on Linux. It is **not** cross-compiled for Windows: a
Windows Server binary would be a build nobody runs, and producing one would invite
the belief that the Server is supported there. The Node is the component that
supports Windows.

## Packaging a Node for someone else

Handing a Node to a user who does not build software is a distribution problem, not
an installation problem. `make package` produces one zip that the user unzips and
starts, and that you can address with the CLI as soon as it connects. The user needs
no Go, no compiler and no configuration file.

```
make package \
  PACKAGE_SERVER_URL=wss://cloud.example:8443/channel \
  PACKAGE_SCOPES='project=/home/me/project notes=/home/me/Documents/notes'
```

For a Windows user, the same inputs through a separate target:

```
make package-windows PACKAGE_SERVER_URL=... PACKAGE_SCOPES='...'
```

`package-windows` is a target rather than a variable you must remember, because
forgetting it produces a Linux binary in a zip a Windows user cannot run, and that
failure appears on their machine instead of yours.

### Inputs

| Variable | Required | Meaning |
|---|---|---|
| `PACKAGE_SERVER_URL` | yes | The Server address. `http`, `https`, `ws` and `wss` are all accepted |
| `PACKAGE_SCOPES` | yes, unless `PACKAGE_SCOPES_FILE` is set | One or more `name=path` entries, space separated |
| `PACKAGE_SCOPES_FILE` | no | A file of `name=path` lines, for paths containing spaces or a long list |
| `PACKAGE_TUNNEL_TOKEN` | no | The `tunnel_token` to embed. Without it the user must supply `CONNECTOR_NODE_TUNNEL_TOKEN` |
| `PACKAGE_ALLOW_FILESYSTEM_ROOT` | no | `1` lets a scope be a volume root. Unset means off. Any other value fails the build |
| `PACKAGE_EMBED_CONFIG` | no | `1` builds one executable with the configuration compiled in, instead of a zip |
| `PACKAGE_NAME` | no | Bundle name. Default `connector-node-<goos>-<goarch>` |
| `PACKAGE_GOOS`, `PACKAGE_GOARCH` | no | Target platform. Default this host |

The output is `bin/<PACKAGE_NAME>.zip`, or `bin/<PACKAGE_NAME>` when
`PACKAGE_EMBED_CONFIG=1`.

### What the zip contains

| Path | What it is |
|---|---|
| `connector-node` / `connector-node.exe` | The Node binary for the target platform |
| `start.sh` / `start.ps1` | Rebuilds `policy.yaml` from `scopes.txt`, then starts the Node |
| `scopes.txt` | The folders this Node exposes. The user edits this one |
| `server_url` | The channel address the Node dials |
| `config/identity` | The `node-id.node-token` pair, generated at packaging time |
| `config/tunnel_token` | The `tunnel_token`, mode `0600`, when you supplied one |
| `README.md` | The user-facing instructions |

### Three decisions that make it work

**The scope paths are not baked into a policy file.** A policy requires absolute
paths, and your paths are not the user's paths. The bundle therefore carries an
editable `scopes.txt`, and the start script rebuilds `policy.yaml` from it on every
start. That is what makes one zip usable on a machine whose folders this host has
never seen. Because the file is rebuilt rather than merged, a scope the user deletes
stops being served.

**The identity pair is generated at packaging time**, with the Node's own `id`
command rather than a second implementation of the pair format. If the Node
generated it on the user's machine, you would have to ask the user to read the pair
back before the CLI could address the Node, which defeats the point of handing over
a bundle. The consequence is that the pair is known to you before the user starts
anything, and the packaging output prints it.

The same consequence has a second edge: **one zip is one machine.** Every copy of
one bundle presents the same `node-id`, and the Server keeps one entry per `node-id`
where a new connection replaces the previous one. Two machines running the same
bundle therefore take turns being reachable, each start evicting the other, and a
request lands on whichever connected last. Build a separate bundle per machine; each
build generates its own pair and prints it.

**The tunnel token is written to a `0600` file** that the start script exports as
`CONNECTOR_NODE_TUNNEL_TOKEN`. The Node still reads the documented environment
variable; the file is your provisioning store, the same shape as a systemd
`EnvironmentFile=`.

### The URL is normalised for you

The Node dials WebSocket and refuses any other scheme at startup, while the CLI uses
HTTP. You pass one address and the packaging converts it: `http` becomes `ws`,
`https` becomes `wss`, and a URL with no path gets `/channel`. Pasting the HTTP
address you use for the CLI therefore produces a working bundle instead of a startup
failure on the user's machine.

### What the packaging prints

The pair, and a CLI command that runs as soon as the user starts the bundle. The
flags come before the operation because the CLI stops parsing flags at the first
positional argument, so the operation must be last. Copy the command rather than
retyping it.

### The bundle is a credential

It carries the Node's identity pair and, when you supply one, the `tunnel_token`.
Hand it over the way you would hand over a password: not through a public
repository, a shared drive or a chat message. If it leaks, run
`connector-node regenerate` on that Node and hand over a new bundle; the old pair
stops working within about a second.

### What the start script refuses

Each refusal is one the Node would also make, moved earlier so the message appears
next to the person who can fix it:

| Refusal | Why |
|---|---|
| The scope path is not a directory on this machine | The path in `scopes.txt` does not exist there |
| The scope is `/` or the home directory | The blast radius is the whole machine |
| The scope overlaps the bundle's `config` directory | A caller could list the credential files |
| `scopes.txt` defines no scope | A Node that exposes nothing serves nothing |

The config-overlap check is enforced by the start script rather than by the Node,
because the bundle keeps its credentials inside its own folder, which is exactly the
layout that check exists to refuse. Both sides of that comparison are resolved
physically, so a bundle reached through a symlink or a junction is still refused.

A bundle expresses the policy's `allow_filesystem_root` opt-in only when you ask
for it: `PACKAGE_ALLOW_FILESYSTEM_ROOT=1`. Unset means off, and the start scripts
then refuse a volume root and generate a policy without the key. The default is
off because the recipient did not write the policy and should not be able to widen
the blast radius by editing one line of `scopes.txt`; the switch is a packaging
decision, recorded in the bundle's `allow_filesystem_root` file, so the recipient
cannot turn it on themselves. Only `1`, `0` and an empty value are accepted, and
any other spelling fails the build rather than guessing.

### A single executable instead of a zip

`make package-embedded` produces one file rather than a zip: the Server address,
the policy and, when you supply it, the `tunnel_token` are compiled into the
binary. The recipient copies the file and runs it. There is nothing to unzip and
nothing to edit.

```
make package-embedded PACKAGE_SERVER_URL=... PACKAGE_SCOPES_FILE=... \
  PACKAGE_TUNNEL_TOKEN=...
make package-embedded-windows ...        # the same, for a Windows target
```

The inputs are the same as for a zip, plus `PACKAGE_EMBED_CONFIG=1` when you call
`make package` directly instead of the dedicated target.

Choose this shape when the recipient should not edit anything, and choose a zip
when they need to change scopes themselves. The trade is explicit:

| | Zip | Single executable |
|---|---|---|
| Scopes the recipient can edit | yes, `scopes.txt` | no, compiled in |
| Policy reload on `SIGHUP` | yes | no policy file to reload |
| `tunnel_token` in the binary | no, in `config/tunnel_token` | **yes, in plain text** |
| Leak blast radius | that one Node | **every Node on this Server** |
| Files to hand over | a zip | one file |

The last two rows are the reason this is a separate target rather than a flag on
the existing one. A zip leaks one Node's identity; an embedded binary leaks the
Server-wide `tunnel_token`, which lets the holder impersonate any Node. `strings`
recovers it, because the linker stores the value as plain text. Hand the file over
the way you would hand over the Server's own secret, and rotate the
`tunnel_token` if it leaks.

The Node compensates where it can: a build that carries a token refuses to serve
its own executable through a scope, so a caller with `read` on the install folder
cannot download the binary and extract the token. A normal build is served
normally, because its bytes disclose nothing.

The identity is deliberately **not** embedded. It is generated on the recipient's
machine at first start, so two copies of one binary do not share a `node-id` and
evict each other from the Server's registry. The recipient runs
`connector-node id` once to learn the pair, exactly as with a normal build.

Scope paths are compiled in as you wrote them, not resolved on your build host. A
path that does not exist on the recipient's machine fails at startup, which is the
same failure a bundle's `scopes.txt` entry produces.

## Configuration

Every value comes from the environment. There is no configuration file and no flag
that overrides a variable, because a second source of the same value is a second
place for the two to disagree.

### Required

| Variable | Purpose |
|---|---|
| `CONNECTOR_SERVER_TUNNEL_TOKEN` | The secret a Node presents in `hello`. Gates the channel |
| `CONNECTOR_SERVER_CLIENT_TOKEN` | The secret a CLI presents on every request. Gates the CLI API |

Both are required. An absent, empty, whitespace-padded or shorter-than-16-byte
value is a **startup failure**, not an "authentication disabled" mode. That is
deliberate: an unset secret is the most likely way to accidentally disable
authentication, so the Server refuses to start rather than run unprotected.

### Optional

| Variable | Default | Purpose |
|---|---|---|
| `CONNECTOR_SERVER_LISTEN` | `:8443` | Address to bind. One listener serves both surfaces |
| `CONNECTOR_SERVER_TLS_CERT` | none | Path to the TLS certificate |
| `CONNECTOR_SERVER_TLS_KEY` | none | Path to the TLS private key |
| `CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS` | `30` | How long to wait for a Node before answering `node_timeout` |

TLS is required unless it is terminated in front of the Server. Setting one of the
certificate variables without the other is a startup failure, because a key without
a certificate cannot serve TLS and a certificate without a key cannot either.

### What does not exist, and must not be invented

There is **no** variable for a Node's `node-token`. No
`CONNECTOR_SERVER_NODE_TOKEN`, no `CONNECTOR_SERVER_NODE_TOKENS_FILE`, no
equivalent. If an operator asks for one, the model has been misunderstood: the
Server forwards the token without knowing whether it is correct, and a Server that
stored it would collapse the separation between the channel authority and the
operation authority into one authority.

There is also no variable that grants a permission or defines a scope. Those live
in the Node's policy file and nowhere else.

## Running it

```
CONNECTOR_SERVER_TUNNEL_TOKEN=<secret> \
CONNECTOR_SERVER_CLIENT_TOKEN=<secret> \
  connector-server run
```

`run` is the default subcommand, so `connector-server` with no argument does the
same thing.

The Server binds its listener **before** it logs that it is listening, so a bind
failure is reported as a startup failure instead of a process that prints
"starting" and then accepts nothing. If the process is alive and the port is not
open, the startup failed and the reason is in the log.

A graceful shutdown closes the HTTP server and every live channel, so a Node that
is mid-request is answered instead of being cut off. Send `SIGINT` or `SIGTERM` and
give it up to 10 seconds.

### systemd sketch

```
[Service]
ExecStart=/usr/local/bin/connector-server run
EnvironmentFile=/etc/connector/server.env
Restart=on-failure
```

`EnvironmentFile` with `0600` permissions is the recommended way to keep the two
secrets out of a unit file that gets copied around. The secrets are still
environment variables at runtime; the file is how the process manager supplies
them.

## The two surfaces and how to expose them differently

| Path | Surface | Client |
|---|---|---|
| `/channel` | WebSocket, the channel protocol | Node |
| `/v1/nodes/{node_id}/operations` | HTTP JSON | CLI |

Both are served from one listener on one port behind one certificate. This is
deliberate: the two surfaces share the routing registry, so a second port would not
isolate state, and it would cost a second certificate, a second firewall rule and a
second proxy entry for one service.

The consequence to state plainly: **the CLI API is reachable by anyone who can
reach the channel port.** That is acceptable because the API authenticates every
request with `client_token` before it reads the `node-token`, and because a caller
who can reach the port can already attempt a `hello`.

A deployment that must keep the CLI API unreachable from the internet blocks
`/v1/` at the reverse proxy. The path prefix is part of the contract, so a proxy
rule can depend on it:

```
# nginx sketch: channel open, CLI API closed
location /channel { proxy_pass http://127.0.0.1:8443; proxy_http_version 1.1;
                    proxy_set_header Upgrade $http_upgrade;
                    proxy_set_header Connection "upgrade"; }
location /v1/     { deny all; }
```

Changing either path is a breaking change to the deployment, not an implementation
detail.

## Rotation

Rotation is the **only** revocation mechanism, because no secret in this model
carries an expiry. It must be a planned procedure, not an incident-time
improvisation.

| Secret | How to rotate | Blast radius | Downtime |
|---|---|---|---|
| `tunnel_token` | Change the environment, restart the Server, update every Node | Every Node | Every Node reconnects |
| `client_token` | Change the environment, restart the Server, update every CLI | Every CLI | None for Nodes |
| A Node's pair | `connector-node regenerate` on that Node | One Node | That Node reconnects |

Two rules make rotation safe, and both are stated rather than softened:

- **The Server accepts exactly one value per secret.** There is no "old and new
  both work" window. A grace period would be a second valid credential, and the
  point of rotating is to end the first one. The cost is that rotation is a
  coordinated change.
- **Rotation is not a hot reload.** The Server reads its secrets once at startup. A
  `SIGHUP` that reloaded them would let a running Server change its own authority
  without a restart, and a restart is the cheapest possible audit trail: it is
  visible in the process table and in the log.

Rotating a Node's pair does **not** affect `tunnel_token` or `client_token`, and
rotating those affects every Node and every CLI at once. Do not conflate them.

## Secrets: what the Server must never do

These are hard constraints. A change that violates one is a design regression.

- Never write `tunnel_token`, `client_token` or a `node-token` to a log, a trace,
  an audit record or an error message. An audit record names the `node-id`, which
  is public, and never a secret.
- Never store a `node-token`: no database row, no file, no cache, no in-memory map
  keyed by token, and no derived value such as a hash, prefix or fingerprint. A
  stored fingerprint is still a stored credential index.
- Never keep `client_token` beyond the request it arrived with.
- Never echo a secret from a configuration dump or a startup banner. A startup log
  line may say a secret is set, never what it is.
- Never place a secret in a URL, a query string or a path segment, because those
  are what proxies and access logs record by default.

When you inspect a running Server, verify these rather than assume them:

```
grep -c '<the node-token value>' /var/log/connector/server.log     # must be 0
grep -c '<the client_token value>' /var/log/connector/server.log   # must be 0
```

## Limits that are constants, not settings

These are compiled in on purpose. A timeout an operator can raise is a timeout that
will be raised, and each of these exists to bound a failure rather than to be tuned.

| Constant | Value | Purpose |
|---|---|---|
| `MaxChannelMessageBytes` | 1 MiB | Largest channel message accepted |
| `MaxRequestBodyBytes` | 1 MiB | Largest CLI request body, checked before decoding |
| `handshakeTimeout` | 10 s | How long the Server waits for `hello` |
| `writeTimeout` | 10 s | Per-frame write deadline on the channel |
| `shutdownTimeout` | 10 s | How long a graceful shutdown waits |
| `maxInFlight` | 64 | Requests one channel may have outstanding |

The Server's HTTP server deliberately has **no** write timeout. A forwarded request
is already bounded by `CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS`, and a second bound
would cut a slow but healthy answer short with a transport error instead of the
`node_timeout` the caller can act on.

## Troubleshooting

Work from the outside in. Each step rules out one layer.

| Symptom | Likely cause | Check |
|---|---|---|
| Process exits immediately | A required secret is missing, empty or too short | The log names the variable |
| Process alive, port closed | Bind failed | The log has the bind error; the process should have exited |
| Node cannot connect | Wrong `tunnel_token`, or TLS mismatch | The Server logs `refusing a hello with a wrong tunnel token`; the Node logs `the server refused the handshake: unauthenticated` |
| Node connects then drops repeatedly | The Node's pair was regenerated, or the Server restarted | Both logs show the reconnect |
| CLI gets `node_offline` | No live connection for that `node_id` | Is the Node running? Did it regenerate its `node-id`? |
| CLI gets `unauthenticated` | Wrong `client_token`, or the Node refused the `node-token` | The Server cannot tell these apart; see below |
| CLI gets `node_timeout` | The Node did not answer within the timeout | Is the Node healthy? Is the file huge? |
| CLI gets `denied` | The Node's policy refused | Nothing on the Server can fix this |

### The one ambiguous answer

`unauthenticated` covers two causes: a wrong `client_token`, and a Node refusing
the `node-token`. The Server cannot distinguish them, because it never learns the
correct `node-token`. Do not claim to know which one it was.

What you can say: if the request produced a JSON answer, the `client_token` was
accepted and the Node refused the token. If it produced a connection error, the
Server was unreachable or rejected the `client_token` before forwarding.

### What the Server cannot answer

The Server cannot answer "may this caller do this?" It does not know the policy, so
any answer it gave would be a guess. It forwards and reports what the Node said.
When an operator asks you to grant access by editing Server configuration, the
answer is that no such setting exists and the change belongs on the Node.

## Common Pitfalls

- **Trying to configure a Node token on the Server.** There is no such variable and
  there must not be one. The Server forwards the token without knowing it.
- **Expecting a grace period during rotation.** There is none. Rotation is
  coordinated: update the Server and every holder of the secret together.
- **Reloading secrets with `SIGHUP`.** The Server reads them once at startup. A
  reload would let a running Server change its own authority without a restart.
- **Opening a second port for the CLI API.** One listener serves both surfaces
  because they share the registry. Block `/v1/` at the proxy instead.
- **Assuming a `denied` answer is a Server problem.** It came from the Node's
  policy. Changing the Server cannot make it succeed.
- **Logging a secret while debugging.** A log line is the most common way a secret
  escapes. Redact it and name the `node-id` instead.
- **Raising a timeout to "fix" a slow read.** The caps are constants. A slow read
  is a large file; use `--offset` and `--length` on the client instead.
- **Building the Server for Windows.** It is deployed on Linux. Only the Node
  supports Windows.

## Verification Checklist

- [ ] Both required secrets are set, non-empty and at least 16 bytes.
- [ ] The process is alive **and** the port is open; a bind failure exits.
- [ ] TLS is configured, or terminated in front of the Server.
- [ ] `/v1/` is blocked at the proxy if the CLI API must not be internet-reachable.
- [ ] No secret appears in the log, the unit file, a config dump or a URL.
- [ ] No Node token is stored anywhere on the Server, including as a hash.
- [ ] Rotation was planned as a coordinated change with no grace period.
- [ ] A `denied` answer was traced to the Node's policy, not to Server config.
- [ ] The Server was not built for Windows.
