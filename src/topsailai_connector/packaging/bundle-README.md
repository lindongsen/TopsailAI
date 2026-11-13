# Connector Node bundle

This folder is a ready-to-run Node. It dials the Server, keeps the link open and
serves only the folders listed in `scopes.txt`.

You do not need Go, a compiler or any other tool. Unzip, start, done.

## Start it

Linux or macOS:

```
./start.sh
```

Windows (PowerShell):

```
powershell -ExecutionPolicy Bypass -File start.ps1
```

The first start prints the folders it exposes and then connects. Leave it
running: it is the process that answers requests.

## Choose which folders are exposed

Edit `scopes.txt`. One line per folder, `name=path`:

```
project=/home/me/project
notes=/home/me/Documents/notes
```

- `name` is what a caller asks for. Letters, digits, `-` and `_` only, and it
  must start with a letter or a digit.
- `path` is the folder on this machine. An absolute path is best. A relative
  path is resolved against this bundle folder, which is predictable but easy to
  misread.
- Every scope is granted `read`, `list` and `stat`. This version cannot write or
  run commands, so there is nothing else to grant.

Restart the Node after editing. `policy.yaml` is rebuilt from `scopes.txt` on
every start, so `scopes.txt` is the only file you edit and a scope you delete
stops being served.

A folder that does not exist, a folder that is a drive root or your home
directory, and a folder that overlaps this bundle's `config` folder are all
refused at start with a message naming the scope. Those refusals are deliberate:
each one would expose far more than the folder you meant to share.

## What is in the folder

| Path | What it is |
|---|---|
| `connector-node` / `connector-node.exe` | The Node binary |
| `start.sh` / `start.ps1` | Turns `scopes.txt` into `policy.yaml` and starts the Node |
| `scopes.txt` | The folders this Node exposes. Edit this one |
| `server_url` | The Server address the Node dials |
| `config/identity` | This Node's `node-id.node-token` pair |
| `config/tunnel_token` | The `tunnel_token` this Node presents, when the operator provisioned one |
| `config/policy.yaml` | Generated on every start. Do not edit; edit `scopes.txt` |

## This folder holds credentials

`config/identity` contains the `node-token` half of this Node's identity, and
`config/tunnel_token` contains the shared secret that opens the channel. Both are
credentials that never expire.

- Do not put this folder in a public repository, a shared drive or a chat
  message.
- Do not paste the contents of `config/identity` into a ticket or a retained
  shell history.
- If the folder leaks, the operator regenerates the pair and gives you a new
  bundle. The old pair stops working within about a second.

## If it does not start

| Message | Meaning |
|---|---|
| `no tunnel token` | The bundle has no `config/tunnel_token` and `CONNECTOR_NODE_TUNNEL_TOKEN` is unset. Ask the operator for the token |
| `scope 'x' path '...' is not a directory on this machine` | The path in `scopes.txt` does not exist here. Fix the path |
| `scope 'x' path '...' overlaps the bundle's config directory` | The folder you exposed contains this bundle, so a caller could list the credential files. Move the bundle outside the folder, or expose a subfolder |
| `scope 'x' is '/'` | Expose a subfolder instead; the whole filesystem is every file on the machine |
| `scope 'x' is the home directory` | Expose a subfolder instead |
| `dial ...` | The Server address in `server_url` is unreachable. Check the address and your network |

A wrong `tunnel_token` is not a start-script refusal, because the script cannot
check it: only the Server knows the right value. The Node starts, dials, and the
Server refuses the handshake, so the Node logs:

```
level=WARN msg="channel ended" error="the server refused the handshake: unauthenticated" retry_in=...
```

That line means the `tunnel_token` is wrong or stale. Ask the operator for the
current one.

The Node retries a dropped connection on its own, and it retries a refused
handshake too, so the warning repeats every few seconds until the token is fixed or
the Node is stopped. A wrong token does not become right by retrying, so the
repetition is a reminder rather than a recovery.

## What the operator needs from you

Nothing, if the bundle was built with the identity already inside it. The
operator already holds the `node-id.node-token` pair and can call this Node as
soon as it connects.

If the operator asks for the pair, it is the single line in `config/identity`.
Treat it as a password.
