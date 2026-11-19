---
name: connector-node-setup
description: Use when a user needs to install, configure, start, or move a TopsailAI Connector Node to a new node id on their own computer, i.e. when they ask how to get their node id, what the policy file looks like, which environment variables the Node needs, how to run it on Windows or Linux, how to change what a scope exposes, how to list the scope names the policy defines so a caller knows what to pass as --scope, how to start a Node from a zip they were handed, how to add or remove a caller credential, how to revoke a leaked credential, or how to find the node id, key id and secret after starting the Node. Covers the first-run order, the startup summary printed on every start, the policy file schema and its startup failures, scope path rules, the scope list command, the ready-to-run bundle, credential management and regeneration.
version: 1.4.0
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

The Node also owns its own identity: a `node_` identifier, which it generates
itself at first start. The Server never mints, assigns or overrides it. The
identifier is an address, not a secret; the secrets are the node credentials the
Node accepts, which are stored separately.

## When to Use

Use this skill when the user asks to:

- Install or start the Node, on Windows, Linux or macOS.
- Get or re-read the node id, and add or remove a node credential.
- Write or fix the policy file, or understand why the Node refuses to start.
- Change which directory a scope exposes, or add a scope.
- Revoke a leaked credential, or move the Node to a new node id.
- Understand why a request came back `denied`.
- Start a Node from a zip someone handed them, and change which folders it exposes.
- Start a Node from a single executable someone handed them, with no configuration
  to edit.

Do **not** use this skill for the client's command syntax (that is
`connector-client`) or for deploying the Server (that is
`connector-server-operations`).

## The first-run order matters

The Node generates its identity, so it must run once before anyone can address it.
The order is fixed and getting it wrong produces a confusing error:

```
1. Server operator: start the Server with its tunnel token and a client
                    credential file

2. Node operator:   connector-node id
                    -> node_7f3a...9c1e     copy this; it is an address

3. Node operator:   write the policy file, then start the Node
                    connector-node run
                    -> === connector-node ===
                       server        : wss://host/channel
                       node id       : node_7f3a...9c1e
                       ...
                       key id        : bundle-caller
                       secret        : <43 characters>
                       credential    : bundle-caller.<secret>
                       ...
                       CONNECTOR_CLI_SERVER_URL=http://host
                       CONNECTOR_CLI_NODE_ID=node_7f3a...9c1e
                       CONNECTOR_CLI_NODE_CREDENTIAL=bundle-caller.<secret>

4. CLI operator:    give the CLI the client credential, the node credential
                    and the node id
```

Step 2 needs **only** the config directory. It does not need a Server URL or a
tunnel token, because it never dials. This is deliberate: the documented order
requires learning the node id before the tunnel token exists, so requiring a full
configuration would make the order impossible.

Step 3 is where the node credential appears. The Node writes one on its first
start, because a Node with no credential refuses every caller, and it prints the
whole summary on **every** start, not only the first. That credential is what the
CLI presents; the node id alone is not enough.

The summary is printed on every start because an operator who restarts a Node has
the same question as one who started it. If you lost the scroll, restart the Node
and read it again; you do not have to open the credential file by hand.

**The secret appears in full only when stdout is a terminal.** If you redirect
stdout to a file or a pipe, the summary still prints but the secret is replaced by
`<secret:N bytes>` and a line explains why. That is deliberate: a launcher that
writes stdout to a log would otherwise append a credential that never expires to
that log on every start. To see the secret, run the Node in a terminal, or read
the file the summary names (`credentials`).

If a user reports that `connector-node id` fails with
`CONNECTOR_NODE_SERVER_URL is empty`, they are running a build older than this
behaviour. The fix is to rebuild; the current `id` and `regenerate` read only
`CONNECTOR_NODE_CONFIG_DIR`.

## Where the identity comes from

The Node generates its own node id; nobody configures it. What differs between the
delivery shapes is **which machine** generates it and **when**:

| How you got the Node | Generated by | When | One artifact per machine |
|---|---|---|---|
| You built it and run it | this machine | first start, when no identity file exists | yes |
| A zip bundle | the operator's build host | when the bundle was packaged | **yes** |
| A single executable | this machine | first start | no |

The zip row is the one that catches people. The bundle already contains
`config/identity`, because the operator generated it while packaging so they could
hand you a CLI command that works the moment you start. That means **one zip is one
machine**: unzip the same bundle on a second machine and both Nodes present the same
node id, so each connection replaces the other in the Server's registry and the
two take turns being reachable. Ask the operator for a second bundle instead.

A single executable has no identity inside it, so every copy generates its own and
copies do not collide.

### The node id and the node credential are separate files

Two files, two jobs, and confusing them is the most common setup mistake:

| File | Holds | Secret? | Written by |
|---|---|---|---|
| `<config>/identity` | the `node_` identifier | no, it is an address | `id`, `regenerate`, or the packaging step |
| `<config>/credentials.yaml` | one `key_id` and secret per caller | yes | first start, or `credential add` |

`connector-node id` prints only the identifier. `regenerate` replaces only the
identifier. Neither touches `credentials.yaml`, so moving a Node to a new address
does not force every caller to be reissued a secret, and revoking a caller does not
move the Node.

### Where the config directory is

The identity lives in `<config>/identity`, and `<config>` is **not** the same place
in the two delivery shapes. This is the difference that wastes the most time,
because both shapes look like "one executable plus a folder".

| Shape | `<config>` | Why |
|---|---|---|
| A zip bundle | `<bundle>/config` | `start.sh` and `start.ps1` export `CONNECTOR_NODE_CONFIG_DIR="$HERE/config"` |
| A single executable | the platform config directory | there is no start script, so the Node falls back to `os.UserConfigDir()` |

The platform config directory is:

| Platform | Path |
|---|---|
| Linux | `$XDG_CONFIG_HOME/topsailai-connector`, or `~/.config/topsailai-connector` |
| macOS | `~/Library/Application Support/topsailai-connector` |
| Windows | `%APPDATA%\topsailai-connector`, for example `C:\Users\<you>\AppData\Roaming\topsailai-connector` |

Two consequences, and both bite in practice:

- **Looking for `config/identity` beside a single executable finds nothing.** The
  file is in the platform config directory. `connector-node id` prints the node id
  without you needing to know the path, which is the reliable way to read it.
- **A deny rule must name the directory that actually holds the credentials.** On a
  bundle, denying `<bundle>/config` covers it. On a single executable the
  credentials are in the platform config directory, so a scope that covers the
  user's profile exposes them unless that directory is denied. The Node denies its
  own config directory by resolved path, so the protection follows the real
  location rather than a guessed one.
- **A copy of the config directory is not protected.** The deny rule answers by
  identity, so it refuses the real directory and serves a copy of it. If you copy
  the config directory before an upgrade, or a script leaves a
  `topsailai-connector.bak-<date>` sibling, that copy sits inside a scope and a
  caller with a valid node credential reads its `credentials.yaml` in full. Keep a
  backup outside every scope, or delete it once the upgrade is confirmed. See
  `issues/issue-a-copy-of-the-config-directory-is-served.md`.

The directory is created with mode `0700` and the identity file with `0600`. An
existing directory is not re-permissioned, because changing the mode of a directory
the operator created is a surprise; the identity file has its own check.

Set `CONNECTOR_NODE_CONFIG_DIR` to an absolute path when you want the location to be
predictable. A relative path is refused, because it resolves differently per launch.

### Supplying one yourself

The node id is not in the environment table below, so there is nothing to export.
The only way to choose a node id is to put it in `<config>/identity` yourself, which
is exactly what a bundle does:

```
printf '%s\n' 'node_....' > <config>/identity
chmod 600 <config>/identity
```

A file you place there is adopted as-is. This is how a bundle ships an identity, and
it is the only supported way to choose one.

### A file that does not parse is refused, never replaced

If `config/identity` exists but does not parse, the Node refuses to start and
**leaves the file untouched**:

```
connector-node: identity file "...": node id "garbage" does not start with "node_"
```

Regenerating would silently change the address the operator already copied into a
CLI, and the symptom would be `node_offline` that names nothing. Fix the file, or
run `connector-node regenerate` if you want a new node id.

### The file must not be readable by anyone else

A group- or world-readable identity file is refused:

```
connector-node: identity file "...": has mode 0644, want no group or other access
```

`chmod 600` fixes it. The check is skipped on Windows, where the permission bits Go
reports are synthesised from the read-only attribute and carry no ownership
information; a check that cannot answer the question does not pretend to.

### Every start prints the summary

`connector-node id` always prints the node id. `connector-node run` prints a
summary on **every** start, to stdout rather than to the log:

```
=== connector-node ===
server        : wss://host/channel
node id       : node_....
config dir    : /etc/connector/node
credentials   : /etc/connector/node/credentials.yaml
policy        : /etc/connector/node/policy.yaml
scopes        : project tool
key id        : bundle-caller
secret        : <43 characters>
credential    : bundle-caller.<secret>

To reach this node from a CLI, set:
  CONNECTOR_CLI_SERVER_URL=http://host
  CONNECTOR_CLI_NODE_ID=node_....
  CONNECTOR_CLI_NODE_CREDENTIAL=bundle-caller.<secret>
  CONNECTOR_CLI_CLIENT_CREDENTIAL=<the server's client credential>
```

The scheme of `CONNECTOR_CLI_SERVER_URL` follows the channel address the Node
dials. A `ws://` channel is served by a plaintext HTTP listener, so the printed
address is `http://`; a `wss://` channel is served by TLS, so it is `https://`.
Copy the line as printed. Changing `http://` to `https://` by hand fails with
`server gave HTTP response to HTTPS client`, which reads as a certificate problem
rather than as a wrong address.

A first start also prints two lines above the summary saying that a node id and a
credential were written by this start. A restart prints the summary without those
lines, because nothing was written.

A build that was packaged with `PACKAGE_EMBED_IDENTITY=1` carries a node id and one
credential inside the binary. The first start writes them to the identity and
credential files, so the summary shows the values the operator chose at packaging
time rather than random ones. From then on the files win: `regenerate`,
`credential add` and `credential remove` behave exactly as they do on a build with
nothing embedded, and a credential you remove is not restored by a restart. The
operator already has these values in the packaging env file, so you never have to
report them back.

The node id is an address, so losing it costs only a lookup. The credential is a
secret that never expires, so losing it costs a rotation: `credential add` issues a
replacement and `credential remove` retires the lost one. You do not have to rotate
just because you lost the scroll, because the summary prints the same value again on
the next start.

**The secret is withheld when stdout is not a terminal.** Redirect stdout to a file
and you get:

```
secret        : <secret:43 bytes>
credential    : bundle-caller.<secret:43 bytes>
                (withheld because stdout is not a terminal; run the node in a
                 terminal to see it, or read the credentials file named above)
```

That is deliberate. A launcher that writes stdout to a log would otherwise append a
credential that never expires to that log on every start. The rest of the summary
still prints, so a log still records which node id, which scopes and which key id
are in force. To see the secret, run the Node in a terminal, or read the file named
on the `credentials` line.

`connector-node credential add` is different: it prints the new credential once and
never again, because it is a management command whose output is the only copy. If
you lose that output, add another credential and remove the lost one.

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

The bundle keeps its credentials in `<bundle>/config`, because the start script
exports `CONNECTOR_NODE_CONFIG_DIR` pointing there. A single executable has no start
script and uses the platform config directory instead; see "Where the config
directory is" above.

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

`config/credentials.yaml` holds the node credentials this Node accepts, and
`config/tunnel_token` is the shared secret that opens the channel. Both never
expire. `config/identity` holds only the node id, which is an address rather than a
secret.

- Do not put the folder in a public repository, a shared drive or a chat message.
- Do not paste `config/credentials.yaml` or `config/tunnel_token` into a ticket or
  a retained shell history.
- If the folder leaks, tell the operator. They remove the exposed credential with
  `connector-node credential remove --key-id <name>` and give you a new one; the old
  one stops working at once.

You do not need to read the credential out to anyone. The operator generated it when
the bundle was built, so they already hold it and can call this Node as soon as it
connects. If they ask for the node id, it is the single line in `config/identity`.
The value to treat as a password is in `config/credentials.yaml`.

## Running from a single executable you were given

This is the default delivery shape: one executable with the Server address, the
policy and, when the operator supplied one, the `tunnel_token` compiled into it.
There is no zip, no `scopes.txt`, no `policy.yaml` and no environment variable to
set. Copy the file, run it, and the Node connects.

```
./connector-node                                    # Linux or macOS
connector-node.exe                                  # Windows
```

The first start generates this machine's node id and its first credential, prints
both once, and connects. The node id is an address; the credential is a secret
that is never printed again, so copy it into the CLI before the output scrolls
away. Everything after that behaves exactly as a bundle does: the same
subcommands, the same policy vocabulary, the same refusals.

### What you cannot change, and what you can

| Setting | Changeable here | How |
|---|---|---|
| Server address | yes | `CONNECTOR_NODE_SERVER_URL` overrides the compiled value |
| `tunnel_token` | yes | `CONNECTOR_NODE_TUNNEL_TOKEN` overrides the compiled value |
| Policy (scopes and grants) | **no** | It is compiled in. Ask the operator for a build with different scopes |
| Config directory | yes | `CONNECTOR_NODE_CONFIG_DIR` |
| Identity | yes | `connector-node regenerate`, as with any build |

The environment wins over a compiled value, field by field, so setting only the
Server address leaves the compiled `tunnel_token` in force.

The policy is the exception, and it fails loudly rather than silently: setting
`CONNECTOR_NODE_POLICY_FILE` on a build that compiled its policy in is a startup
failure. The two would disagree about every scope and every grant, and the operator
would believe the compiled policy was still in force.

### The executable is a credential

This is the part that differs from a bundle, and it is not a detail.

A build that compiled the `tunnel_token` in carries a Server-wide secret in its own
bytes. `strings connector-node` recovers it, because the linker stores the value as
plain text. That is inherent to the mechanism, not a defect in this build.

So the file is a password, and a more dangerous one than `config/identity`:

- `config/identity` is per-Node. Leaking it exposes this one machine.
- The `tunnel_token` is Server-wide. Leaking it lets the holder open a channel and
  impersonate **any** Node that Server serves, not just this one.

Handle it accordingly:

- Do not put it in a public repository, a shared drive, a chat message or an email
  attachment that is retained.
- Do not copy it to a machine you do not control.
- If it leaks, tell the operator. They rotate the `tunnel_token` on the Server,
  which invalidates every Node and every CLI at once, and send you a new build.

### The Node refuses to serve its own executable

If the compiled policy exposes a folder that contains the executable, the Node
refuses to serve that file: `file.read` and `file.stat` return `denied`, and
`file.list` omits it. A neighbouring file in the same folder is still served.

This is deliberate. Without it, a caller with `read` on that folder could download
the binary and recover the Server-wide token from it. The refusal is conditional on
the build actually carrying a token: a normal build is served normally, because its
bytes disclose nothing.

The refusal is by file identity, so a copy of the executable elsewhere is a
different file and is served. The protection covers the running binary, not every
copy of it.

### What this shape does not give you

- **No scope editing.** Changing a scope means a new build from the operator.
- **No policy reload.** `SIGHUP` reloads a policy file; there is none here.
- **No per-machine scopes.** The compiled paths are the ones the operator chose at
  build time. A path that does not exist on this machine fails at startup, exactly
  as a bundle's `scopes.txt` entry would.
- **No secrecy.** The token is recoverable from the file by anyone who has the file.

If you need to change scopes yourself, ask for a bundle instead. The bundle keeps
the policy in a file you edit and holds no Server-wide secret in the binary.

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
| `run` (default) | Load the configuration, the policy, the node id and the credentials, dial the Server and serve |
| `id` | Print the node id and nothing else |
| `regenerate` | Replace the node id; credentials are untouched |
| `credential add` | Add a caller credential; `--key-id` names it, and a name is generated when omitted |
| `credential list` | Print the key identifiers and never a secret |
| `credential remove` | Remove one credential by `--key-id`; the last one cannot be removed |
| `scope list` | Print the scope names the policy defines, one per line, in sorted order |

`connector-node id` prints the node id and nothing else, so it can be copied into a
script. It is an address, not a secret, so it is safe to show.

The secret appears in two places, and the two behave differently:

- `run` prints it in the startup summary on **every** start, but only when stdout is
  a terminal. Redirect stdout and the summary still prints with the secret replaced
  by `<secret:N bytes>`, so a launcher that logs stdout does not accumulate a
  credential that never expires.
- `credential add` prints the new credential **once**, because that output is the
  only copy. If you lose it, add another credential and remove the lost one.

Either way, a secret must not be pasted into a ticket, a chat message or a retained
shell history.

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

### How to learn a scope name

`--scope` is required on every CLI request, and no API lists the names. The Node
refuses a request naming a scope the policy does not define with `denied`, and it
refuses a request naming a scope you have no permission on with `denied` too, so a
caller cannot tell the two apart and cannot enumerate names by guessing.

The names come from the policy file, and this command prints them:

```
connector-node scope list
```

The output is one name per line, sorted, and nothing else:

```
pending
project
tool
```

What it does and does not do:

- It reads the policy document only. It does not dial the Server, so it needs no
  `CONNECTOR_NODE_SERVER_URL` and no `CONNECTOR_NODE_TUNNEL_TOKEN`.
- It does not open a scope, so it works before the first start and on a machine
  where a scope directory does not exist yet.
- It prints names, never paths. The path is the Node's own filesystem layout and
  does not help anyone fill `--scope`.
- It prints no permission and no secret.
- It uses the same strict decoder the Node uses at startup, so a malformed policy
  fails here with the same reason `run` reports, and the command doubles as a policy
  check. The prefix differs: this command prints
  `connector-node: scope "bad": path "rel/path" is relative; ...` while `run` prints
  the same reason after `connector-node: load authority: `.
- It reads `CONNECTOR_NODE_CONFIG_DIR` and `CONNECTOR_NODE_POLICY_FILE`, exactly as
  `run` does. A build with an embedded policy reads the embedded document and
  refuses `CONNECTOR_NODE_POLICY_FILE`.

Exit status:

| Status | Meaning |
|---|---|
| `0` | The names were printed |
| `1` | The policy could not be read or is invalid; the message names the reason |
| `2` | The command line was rejected, for example `scope` with no subcommand |

Give the names to whoever calls this Node. They cannot discover them from the CLI,
because the answer would tell an unauthorized caller which areas exist.

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
- The config directory is the platform configuration directory, not a `config`
  folder beside the executable. See "Where the config directory is" above for the
  path on each platform and for why a bundle differs.
- A process started over SSH dies when the session ends. `Start-Process` returns a
  live process that connects and then disappears silently, leaving a zero-byte log.
  Start it through WMI instead, which detaches it from the session:

  ```
  Invoke-CimMethod -ClassName Win32_Process -MethodName Create `
    -Arguments @{ CommandLine = 'cmd.exe /c C:\path\to\run.cmd'; CurrentDirectory = 'C:\path\to' }
  ```

- Redirect the log inside a `.cmd` launcher (`connector-node.exe > start.out.log
  2> start.err.log`). `Start-Process -RedirectStandardOutput` produced a zero-byte
  file while the process ran.
- Reserved device names (`NUL`, `CON`, `COM1`, `LPT1`), alternate data streams
  (`file.txt:stream`), trailing dots and trailing spaces are all refused as paths.
  That is defence in depth, not a limitation.
- A junction or symlink that escapes the scope is refused by the same rule as on
  POSIX. A junction pointing at the Node's own config directory is refused for
  `read`, `list` and `stat`, and it does not appear in its parent's listing.

## Moving the Node to a new node id

```
connector-node regenerate
```

`regenerate` replaces the node id and prints the new one. It does **not** touch
`credentials.yaml`, so every caller keeps working and no secret has to be reissued.
`--keep-id` no longer exists: it kept the address while replacing the secret, which
was meaningful only when the address and the secret were one value. It is now
refused rather than silently ignored.

A running Node adopts the new node id on its own: it watches its identity file and,
within about one second, adopts the new value, drops the channel that was
authenticated under the retired one, and reconnects. **No restart is required.**

What regeneration costs:

| Action | node id | credentials | Consequence |
|---|---|---|---|
| `regenerate` | New | Unchanged | The CLI must be given the new node id; the credentials stay valid |

Regeneration is **not** revocation of a credential. To revoke one, use
`connector-node credential remove --key-id <name>`, which takes effect at once and
affects only that caller. Regeneration is also not revocation of `tunnel_token` or
the Server's client credentials; those are changed by the Server operator.

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
| Reconnects every 5 seconds | The Server is down, or the node id was regenerated | Check both logs |
| A request came back `denied` | The policy does not grant it | Add the grant and reload |
| A request came back `not_found` | The policy allowed it and the path is not there | Check the path |
| `invalid_argument` on a path | The path has `..`, `.`, a backslash, a colon, a NUL, or is absolute | Use a plain relative path |
| `node id "garbage" does not start with "node_"` | `config/identity` does not hold a valid node id | Fix the file, or `connector-node regenerate` for a new node id. The Node never replaces it for you |
| `has mode 0644, want no group or other access` | The identity or credential file is readable by others | `chmod 600 <config>/identity <config>/credentials.yaml` |

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
- **Assuming a regeneration needs a restart.** A running Node adopts the new node id
  within about one second and reconnects on its own.
- **Assuming a regeneration revokes the Server's secrets.** It does not. Those are
  Server-wide.
- **Pasting `connector-node id` output into a ticket.** The node id is an address, so
  that is harmless. The credential is the secret: never paste it into a ticket, a
  chat message or a retained shell history.
- **Trimming whitespace from a copied node id.** Whitespace is refused rather than
  trimmed, because trimming would hide a copy-paste error.
- **Using a relative config directory.** Refused, because it resolves differently
  per launch.

## Verification Checklist

- [ ] `connector-node id` printed a node id with a `node_` prefix and a 26 character
      body.
- [ ] The node credential was copied whole and stored as a secret, not in a ticket or
      history.
- [ ] `CONNECTOR_NODE_CONFIG_DIR` is an absolute path.
- [ ] The policy file exists, is non-empty, and has `version: 1`.
- [ ] Every scope has an absolute `path` that exists and is a directory.
- [ ] No scope root is `/`, the home directory, a mount root, a symlink, or
      overlapping the config directory.
- [ ] Every grant names a defined scope and a known permission.
- [ ] `run` has `CONNECTOR_NODE_SERVER_URL` and `CONNECTOR_NODE_TUNNEL_TOKEN` set.
- [ ] The log shows a handshake accepted, not a refusal followed by silence.
- [ ] After a regeneration, the CLI was given the new node id. The credential is
      unchanged, because regeneration replaces the address and not the secret.
- [ ] For a single-executable build, the file was stored as a credential, because it
      carries the Server-wide `tunnel_token` in plain text.
- [ ] For a single-executable build, `CONNECTOR_NODE_POLICY_FILE` is unset, because
      setting it is a startup failure.
