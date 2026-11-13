---
name: connector-node-setup
description: Use when a user needs to install, configure, start, or regenerate the identity of a TopsailAI Connector Node on their own computer, i.e. when they ask how to get their node-id.node-token pair, what the policy file looks like, which environment variables the Node needs, how to run it on Windows or Linux, how to change what a scope exposes, how to start a Node from a zip they were handed, or how to revoke a leaked token. Covers the first-run order, the policy file schema and its startup failures, scope path rules, the ready-to-run bundle and regeneration.
version: 1.0.0
author: DawsonLin
license: MIT
metadata:
  tags: [connector, node, setup, policy, identity, windows, regeneration]
  related_skills: [connector-client, connector-server-operations]
---

# Connector Node Setup

## Overview

You are helping a user run a **Node** on their own computer. The Node dials out to
a Server in the cloud and serves only the operations its local policy allows. It
needs no inbound port, no public address and no firewall change, because it always
initiates the connection.

The Node is the **only** authority for permissions. It decides both which areas may
be touched (`scope`) and which action may be taken there (`permission`). The Server
holds no scope list and no permission list, so access cannot be widened by editing
Server configuration.

The Node also owns its own identity: a single string `node-id.node-token`, which it
generates itself at first start. The Server never mints, assigns or overrides it.

## When to Use

Use this skill when the user asks to:

- Install or start the Node, on Windows, Linux or macOS.
- Get or re-read the `node-id.node-token` pair.
- Write or fix the policy file, or understand why the Node refuses to start.
- Change which directory a scope exposes, or add a scope.
- Revoke a leaked token by regenerating the pair.
- Understand why a request came back `denied`.
- Start a Node from a zip someone handed them, and change which folders it exposes.

Do **not** use this skill for the client's command syntax (that is
`connector-client`) or for deploying the Server (that is
`connector-server-operations`).

## The first-run order matters

The Node generates its identity, so it must run once before anyone can address it.
The order is fixed and getting it wrong produces a confusing error:

```
1. Server operator: start the Server with its two secrets set

2. Node operator:   connector-node id
                    -> node_7f3a...9c1e.kQ2v...4d7a     copy this whole pair

3. Node operator:   give the Node the tunnel_token, then start it
                    connector-node run

4. CLI operator:    give the CLI the client_token and the pair
```

Step 2 needs **only** the config directory. It does not need a Server URL or a
tunnel token, because it never dials. This is deliberate: the documented order
requires learning the pair before the tunnel token exists, so requiring a full
configuration would make the order impossible.

If a user reports that `connector-node id` fails with
`CONNECTOR_NODE_SERVER_URL is empty`, they are running a build older than this
behaviour. The fix is to rebuild; the current `id` and `regenerate` read only
`CONNECTOR_NODE_CONFIG_DIR`.

## Build and install

```
make build
```

Binaries land in `bin/`. To install elsewhere:

```
make build BIN_DIR=/usr/local/bin
```

For Windows, cross-compile from a Linux or macOS host:

```
make build-windows
```

That produces `windows/amd64`, `windows/arm64` and `windows/386` builds under
`.tmp/xbuild/`. Copy the one that matches the machine.

Windows is a supported platform, not a later port. The path fence is the standard
library `os.Root`, which enforces the boundary on Windows as well as on POSIX, so
the platform cost is a set of path rules rather than a second fence implementation.

## Running from a bundle you were given

If someone handed you a zip instead of a repository, you do not need this build
section at all. The bundle already contains a Node binary built for your platform,
its identity, the Server address and a scope list. Unzip it and start it:

```
./start.sh                                        # Linux or macOS
powershell -ExecutionPolicy Bypass -File start.ps1   # Windows
```

There is nothing to install and nothing to configure before the first start. The
bundle's own `README.md` describes the folder.

### The one file you edit

`scopes.txt` lists the folders this Node exposes, one `name=path` per line:

```
project=/home/me/project
notes=/home/me/Documents/notes
```

`name` is what a caller asks for and must be an identifier: letters, digits, `-` and
`_`, starting with a letter or a digit. `path` is the folder on this machine; an
absolute path is best, and a relative one is resolved against the bundle folder.

Restart the Node after editing. `policy.yaml` is rebuilt from `scopes.txt` on every
start, so `scopes.txt` is the only file you edit and a scope you delete stops being
served. Do not edit `policy.yaml` itself: your change is discarded on the next
start.

Every scope is granted `read`, `list` and `stat`. This version cannot write or run
commands, so there is nothing else to grant.

### What the start script refuses, and why

| Message | Meaning |
|---|---|
| `scope 'x' path '...' is not a directory on this machine` | The path in `scopes.txt` does not exist here. Fix the path |
| `scope 'x' is '/'` | Expose a subfolder instead; the whole filesystem is every file on the machine |
| `scope 'x' is the home directory` | Expose a subfolder instead; the home directory is every file you own |
| `scope 'x' path '...' overlaps the bundle's config directory` | The folder you exposed contains the bundle, so a caller could list the credential files. Move the bundle outside the folder, or expose a subfolder |
| `no tunnel token` | The bundle has no `config/tunnel_token` and `CONNECTOR_NODE_TUNNEL_TOKEN` is unset. Ask the operator for the token |

These are the same refusals the Node makes, moved earlier so the message names the
scope and the reason. The config-overlap refusal is the one the start script adds,
because a bundle keeps its credentials inside its own folder.

A wrong `tunnel_token` is not a start-script refusal, because the script cannot
check it: only the Server knows the right value. The script starts the Node, the
Node dials, the Server refuses the handshake, and the Node logs a warning and
retries:

```
level=WARN msg="channel ended" error="the server refused the handshake: unauthenticated" retry_in=...
```

That line means the `tunnel_token` is wrong or stale. Ask the operator for the
current one. The Node keeps retrying, so the line repeats until the token is fixed
or the Node is stopped.

### The bundle holds credentials

`config/identity` is this Node's `node-id.node-token` pair and `config/tunnel_token`
is the shared secret that opens the channel. Both never expire.

- Do not put the folder in a public repository, a shared drive or a chat message.
- Do not paste `config/identity` into a ticket or a retained shell history.
- If the folder leaks, tell the operator. They regenerate the pair and give you a
  new bundle; the old one stops working within about a second.

You do not need to read the pair out to anyone. The operator generated it when the
bundle was built, so they already hold it and can call this Node as soon as it
connects. If they ask for it, it is the single line in `config/identity`, and it is
a password.

## Configuration

Every value comes from the environment. There is no configuration file for the
Node's own settings; the policy is a separate file.

### Per subcommand

| Variable | Default | Required by | Purpose |
|---|---|---|---|
| `CONNECTOR_NODE_SERVER_URL` | none | `run` | Server channel address, `ws://` or `wss://` |
| `CONNECTOR_NODE_TUNNEL_TOKEN` | none | `run` | The `tunnel_token` this Node presents in `hello` |
| `CONNECTOR_NODE_CONFIG_DIR` | platform config directory | `run`, `id`, `regenerate` | Where the identity file and the default policy file live |
| `CONNECTOR_NODE_POLICY_FILE` | `<config>/policy.yaml` | `run` | Path to the policy file |

`id` and `regenerate` read **only** `CONNECTOR_NODE_CONFIG_DIR`. They never dial,
so they never need a dial target or a tunnel token.

The identity is **not** an environment variable. It lives in `<config>/identity`,
because it is per-Node, long-lived and regenerable, and because a value the Node
rewrites itself belongs in a file the Node owns rather than in the environment of
whatever process launched it.

### Subcommands

| Subcommand | Meaning |
|---|---|
| `run` (default) | Load the configuration, the policy and the identity, dial the Server and serve |
| `id` | Print the `node-id.node-token` pair and nothing else |
| `regenerate` | Replace the pair; `--keep-id` keeps the node id and replaces only the token |

`connector-node id` prints the pair and nothing else, so it can be copied into a
script. It prints a **secret**, so the output must not be pasted into a ticket, a
chat message or a retained shell history.

## The policy file

The policy file is the only place a scope is defined and a permission granted. It
is YAML, it is required, and a missing file is a startup failure rather than an
implicit allow-all.

```yaml
version: 1
scopes:
  project:
    path: /home/me/project
  scratch:
    path: /home/me/scratch
grants:
  - scope: project
    permissions: [read, list, stat]
```

### Vocabulary

Two words, deliberately separate.

| Word | Meaning | Example |
|---|---|---|
| `scope` | A named area the Node exposes. A name, never a path | `project`, `tool`, `scratch` |
| `permission` | An action allowed inside a scope | `read`, `write`, `list`, `stat`, `exec` |

A scope name must be an identifier: letters, digits, `-` and `_` only. A space, a
tab, a control character, a colon, a trailing dot or a path separator is refused,
because such a name reaches a filesystem call in a form no policy author intended.

The Node maps a scope name to a local directory. The Server never learns the real
absolute path, so a directory rename does not invalidate the policy and a leaked
policy does not leak the filesystem layout.

### What the first version supports

Only `file.list`, `file.stat` and `file.read` exist. `file.write` and
`command.exec` are refused at dispatch even if a grant names them, so a policy that
grants `write` does not enable writing.

### Every validation failure is a startup failure

A Node that started with a broken policy would be a Node whose operator believes it
is serving something it is not. So every problem fails startup:

| Condition | Result |
|---|---|
| File does not exist | Startup failure |
| File is empty | Startup failure; an empty file is not an empty policy |
| File exceeds 1 MiB | Startup failure, checked before decoding |
| Malformed YAML | Startup failure |
| More than one YAML document | Startup failure; only the first would be read |
| Unknown top-level key | Startup failure |
| Unknown key inside a scope | Startup failure |
| Missing `version` or unknown version | Startup failure |
| Scope name that is not an identifier | Startup failure |
| Scope with no `path`, or a relative `path` | Startup failure |
| Grant naming an undefined scope | Startup failure |
| Unknown permission name | Startup failure |
| Duplicate permission in one grant | Startup failure |
| Scope path that does not exist, or is a file | Startup failure |
| Scope path inside the config directory, or containing it | Startup failure |
| Any scope failing to open | Startup failure; already-opened scopes are closed first |

An empty `grants` list is valid and refuses everything. That is a working Node that
denies every request, which is a legitimate starting point.

### Scope path rules

A scope root is validated once at startup, and the resolved path is stored, so a
rename during runtime does not silently change what a scope means.

- The path is absolute. A relative path would resolve differently per launch.
- The path exists and is a directory.
- The path is not a symlink or a junction.
- The path is not `/`, not the user's home directory, and not a filesystem or mount
  root, because the blast radius of those is the whole machine.
- The path is not inside the Node's config directory, and the config directory is
  not inside the path. A scope that can read its own credentials is a configuration
  mistake worth refusing at startup.

On Windows the comparison is case-insensitive, so `c:\users\me` is recognised as the
home directory even when the policy spells it differently from the system.

## Starting the Node

```
CONNECTOR_NODE_SERVER_URL=wss://cloud.example:8443/channel \
CONNECTOR_NODE_TUNNEL_TOKEN=<secret> \
  connector-node run
```

The Node dials the Server and retries a dropped connection every 5 seconds. A
**refused handshake is not retried**, because a wrong tunnel token does not become
right by trying again. If the log shows a refusal and then silence, the token is
wrong.

A graceful shutdown closes the channel. Send `SIGINT` or `SIGTERM`.

### Windows notes

- Run it from a console or as a service; there is no installer.
- The config directory defaults to the platform configuration directory. Set
  `CONNECTOR_NODE_CONFIG_DIR` explicitly if you want it somewhere predictable.
- Reserved device names (`NUL`, `CON`, `COM1`, `LPT1`), alternate data streams
  (`file.txt:stream`), trailing dots and trailing spaces are all refused as paths.
  That is defence in depth, not a limitation.
- A junction or symlink that escapes the scope is refused by the same rule as on
  POSIX.

## Regenerating the pair

```
connector-node regenerate              # new node-id and new node-token
connector-node regenerate --keep-id    # same node-id, new node-token
```

Both forms invalidate the old `node-token` **immediately**. The Node keeps no
history of accepted values, so an old token cannot be accepted after a
regeneration.

A running Node adopts the new pair on its own: it watches its identity file and,
within about one second, adopts the new pair, drops the channel that was
authenticated with the retired one, and reconnects. **No restart is required.**

What regeneration costs:

| Action | `node-id` | `node-token` | Consequence |
|---|---|---|---|
| `regenerate` | New | New | The CLI must be given the new pair, including the new address |
| `regenerate --keep-id` | Unchanged | New | The CLI keeps its routing name but must be given the new secret |

Regeneration is **not** revocation of `tunnel_token` or `client_token`. Those are
Server-wide and are changed by the Server operator.

Regeneration is local and operator-initiated. The Server cannot trigger it, because
a Server that could force regeneration could also force a denial of service.

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| `CONNECTOR_NODE_SERVER_URL is empty` on `run` | The variable is unset | Set it; `run` requires it |
| `CONNECTOR_NODE_TUNNEL_TOKEN is empty` on `run` | The variable is unset | Set it |
| `policy file is missing` | No policy at the default path | Create `<config>/policy.yaml` or set `CONNECTOR_NODE_POLICY_FILE` |
| `is relative; a relative path resolves differently per launch` | A relative config dir or policy path | Use an absolute path |
| `is not a directory` | The config dir path is a file | Fix the path |
| Startup fails naming a scope | That scope's path is missing, is a file, is a symlink, or overlaps the config dir | Fix the policy |
| Handshake refused, then silence | Wrong `tunnel_token` | Get the correct value from the Server operator |
| Reconnects every 5 seconds | The Server is down, or the pair was regenerated | Check both logs |
| A request came back `denied` | The policy does not grant it | Add the grant and reload |
| A request came back `not_found` | The policy allowed it and the path is not there | Check the path |
| `invalid_argument` on a path | The path has `..`, `.`, a backslash, a colon, a NUL, or is absolute | Use a plain relative path |

### `denied` versus `not_found`

These are deliberately different. `denied` means the policy refused; `not_found`
means the policy allowed it and the file is not there. Do not tell a user "the file
does not exist" when the answer was `denied`.

### Reloading the policy

A policy reload is all-or-nothing: a file that fails validation leaves the previous
policy in force and logs the rejection. A half-applied policy would be a Node whose
reachable surface depends on which line happened to parse.

## Common Pitfalls

- **Running `id` before the Server exists.** That is correct and expected. `id`
  needs only the config directory.
- **Putting the identity in an environment variable.** It belongs in
  `<config>/identity`. The Node rewrites it on regeneration, and an environment
  variable cannot be rewritten by the process that owns it.
- **Making a scope root the home directory or `/`.** Refused at startup, because
  the blast radius is the whole machine. A whole volume such as `C:\` is refused
  for the same reason unless the policy states `allow_filesystem_root: true`, which
  is the operator writing that blast radius down on purpose.
- **Making a scope contain the config directory.** Refused at startup, because a
  scope that can read its own credentials is a configuration mistake. The one
  exception is the filesystem-root opt-in, which necessarily contains the config
  directory; the deny list then refuses the directory and everything inside it, and
  a listing omits it.
- **Expecting `write` to work because the policy grants it.** `file.write` is not
  enabled in this version and is refused at dispatch.
- **Assuming a regeneration needs a restart.** A running Node adopts the new pair
  within about one second and reconnects on its own.
- **Assuming a regeneration revokes the Server's secrets.** It does not. Those are
  Server-wide.
- **Pasting `connector-node id` output into a ticket.** It is a secret with no
  expiry. Treat it as one.
- **Trimming whitespace from a copied pair.** Whitespace is refused rather than
  trimmed, because trimming would hide a copy-paste error.
- **Using a relative config directory.** Refused, because it resolves differently
  per launch.

## Verification Checklist

- [ ] `connector-node id` printed a pair with exactly one dot and a `node_` prefix.
- [ ] The pair was copied whole and stored as a secret, not in a ticket or history.
- [ ] `CONNECTOR_NODE_CONFIG_DIR` is an absolute path.
- [ ] The policy file exists, is non-empty, and has `version: 1`.
- [ ] Every scope has an absolute `path` that exists and is a directory.
- [ ] No scope root is `/`, the home directory, a mount root, a symlink, or
      overlapping the config directory.
- [ ] Every grant names a defined scope and a known permission.
- [ ] `run` has `CONNECTOR_NODE_SERVER_URL` and `CONNECTOR_NODE_TUNNEL_TOKEN` set.
- [ ] The log shows a handshake accepted, not a refusal followed by silence.
- [ ] After a regeneration, the CLI was given the new pair.
