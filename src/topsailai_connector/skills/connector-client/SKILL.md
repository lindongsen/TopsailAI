---
name: connector-client
description: Use when a user wants to read files on a remote machine through the TopsailAI Connector, i.e. when they ask to list a directory, inspect a file, copy a file down to their own machine, or read a file on a Node they can address, or when they hit an error code such as unauthenticated, denied, not_found or node_offline and need to know what it means and what to do next. Covers the connector-server cli command, its flags including -o for a whole-file copy, the client and node credentials, the three read-only operations, calling a Node that was distributed as a ready-to-run zip, and every error code.
version: 2.1.0
author: DawsonLin
license: MIT
metadata:
  tags: [connector, cli, remote-file-access, read-only, troubleshooting]
  related_skills: [connector-server-operations, connector-node-setup]
---

# Connector Client

## Overview

You are helping a user read files on a remote machine through the TopsailAI
Connector. The remote machine runs a **Node**. A **Server** in the cloud relays
your request to that Node. You talk to the Server with the `cli` subcommand of the
`connector-server` binary.

Three things are true about this system and they explain almost every error a user
will hit:

1. **The Node decides everything.** The Server only relays. A `denied` answer came
   from the Node's policy file, not from the Server, so nothing on the Server can
   be changed to make it succeed.
2. **The CLI holds two credentials, and neither is sent.** A **client credential**
   proves you may use the Server; the Server checks it. A **node credential**
   proves you may talk to that one Node; the Node checks it. Each credential signs
   the request, so the secret itself never travels.
3. **The first version is read-only.** Only `file.list`, `file.stat` and
   `file.read` exist. Writing and running commands are refused by design.

## When to Use

Use this skill when the user asks to:

- List, inspect or read a file on a remote machine they reach through the Connector.
- Work out why a Connector request failed, from an error code or a message.
- Set up a script that calls the Connector repeatedly.
- Understand what a client credential and a node credential are and where to get
  them.
- Call a Node that was handed to a user as a zip, where the operator already holds
  the node id and a node credential.

Do **not** use this skill to deploy or operate the Server (that is
`connector-server-operations`) or to install and configure the Node (that is
`connector-node-setup`).

## Before the first request

You need four values. Ask the user for whichever is missing; never invent one.

| Value | What it looks like | Where it comes from |
|---|---|---|
| Server URL | `https://cloud.example:8443` | The Server operator |
| Client credential | `operator-dawson.XMUThHjCFvpOjShS1-krCLj-k-k5nl93uEUAXqBZbX4` | The Server operator |
| Node credential | `bundle-caller.1oIP0eKi2U84Voi2XjA8e5Z6FdjMyzmHdhE9Or5AKVQ` | The Node operator, from the Node's first start or `credential add` |
| Node id | `node_j5ys4xzrqlyfct2n7q4a4jione` | The Node operator, from `connector-node id` |

A credential is **one string with one dot in it**. The part before the dot is the
`key_id`, which is public and names which credential was used. The part after the
dot is the secret. The CLI splits it for you; you always pass the whole value.

The node id is **not** a credential. It is an address: it says which Node to route
to, and it grants nothing on its own. A user who has only a node id cannot proceed.
Tell them to ask the Node operator for a node credential as well.

### When the Node came from a bundle

If the Node was distributed as a zip, the operator already holds the node id and
one node credential: both were generated when the bundle was built, and the
packaging output printed them together with a ready-to-run CLI command. Do not ask
the user to read them out of the bundle's `config/` directory in that case, and do
not ask them to run `connector-node id`; the operator has the values already.

The printed command is the one to copy. It puts every flag before the operation,
which is the only order the CLI accepts, and it uses an empty `--path` to list the
scope root. Retyping it from memory is how the flag-order mistake gets made.

The user's only job is to start the bundle. Until they do, the CLI answers
`node_offline`, because the Server has no live connection to route to. That is not a
credential problem and retrying will not fix it; the Node has to be running.

## The command

```
connector-server cli [flags] <operation>
```

**Flags must come before the operation name.** Go's flag parser stops at the first
non-flag argument, so `cli file.read --scope project` treats `--scope` as a second
positional argument and refuses it. This is the single most common usage mistake.

### Flags

| Flag | Environment variable | Required | Meaning |
|---|---|---|---|
| `--server` | `CONNECTOR_CLI_SERVER_URL` | yes | Server base URL, `http` or `https` |
| `--client-credential` | `CONNECTOR_CLI_CLIENT_CREDENTIAL` | yes | The client credential, `key_id.secret` |
| `--node-credential` | `CONNECTOR_CLI_NODE_CREDENTIAL` | yes | The node credential, `key_id.secret` |
| `--node-id` | `CONNECTOR_CLI_NODE_ID` | yes | The node id the request is for |
| `--scope` | none | yes | A scope name the Node's policy defines |
| `--path` | none | no | Relative path inside the scope; empty means the scope root |
| `--offset` | none | no | Byte offset for `file.read`, default `0` |
| `--length` | none | no | Byte count for `file.read`; `0` means up to the cap |
| `--request-id` | none | no | Correlation id, signed by both proofs and echoed by the Server |
| `--json` | none | no | Print the whole response envelope instead of the payload |
| `-o`, `--output` | none | no | Where the result goes: `-` for stdout, or a local file path |
| `--force` | none | no | Replace an existing local file named by `-o` |

A flag wins over its environment variable. The environment exists so a script can
export a value once instead of repeating it on every line.

**Prefer the environment variable for the two credentials.** A secret passed as a
flag is visible in `argv` to every account on the host and is written to shell
history by default. The flag is there for a script that already holds the secret
and would otherwise have to export it; that exposure is an accepted trade-off
recorded in the residual risks of `docs/permission-design.md`.

### Operations

| Operation | Needs `--path` | Returns |
|---|---|---|
| `file.list` | no; empty lists the scope root | one line per entry: name, type, size |
| `file.stat` | yes | one `key<TAB>value` line per field |
| `file.read` | yes | the file content, as raw bytes |

`file.stat` reports a symlink **without following it**, so `is_symlink` and
`link_target` describe the link itself. That is deliberate: following a link is
exactly the operation the Node's path fence refuses.

## Reading a whole file

**This is the part that surprises people.** A single `file.read` returns at most
256 KiB. That limit belongs to the Node and cannot be raised from the CLI.

So `file.read > out.bin` is **not** a whole-file copy. For a file larger than
256 KiB it writes the first 256 KiB and prints a notice on stderr:

```
connector-server cli: content truncated at 262144 bytes
```

If you redirect stderr away, you get a partial file with nothing to warn you.

**Use `-o` to read a whole file.** It repeats the request until the end of the
file, so the result is complete no matter how large the file is:

```
connector-server cli ... --scope project --path photos/cat.jpg -o cat.jpg file.read
```

Three things follow from that, and all three are deliberate:

- **A file that exists is a complete file.** The CLI writes to a temporary file
  beside the destination and moves it into place only after the last byte arrives.
  A failure part-way leaves the destination untouched, so you never get half a
  file that looks whole.
- **An existing destination is refused.** You get
  `... already exists; pass --force to replace it` and exit status `1`. Add
  `--force` when you mean to overwrite. A read tool that silently replaced your
  local file would destroy work you never asked it to touch.
- **`-o` works for all three operations.** It means "where the result goes", so
  `file.list -o listing.txt` and `file.stat -o info.txt` work too. Only
  `file.read` needs the repeat loop, because it is the only operation whose answer
  is capped.

`-o -` writes to stdout and still reads the whole file. Use it when you want the
complete content in a pipeline:

```
connector-server cli ... --scope project --path big.bin -o - file.read | sha256sum
```

The difference between `-o -` and no `-o` at all is worth remembering: **`-o -`
reads the whole file, no `-o` reads one capped response.**

### Reading part of a file

`--offset` and `--length` still work, and they combine with `-o`:

```
connector-server cli ... --scope project --path big.log --offset 0 --length 4096 file.read
```

That returns at most 4096 bytes. With `-o` the CLI still loops, but it stops when
your `--length` budget is spent, so `--offset 200000 --length 400000 -o part.bin`
gives you exactly that 400000-byte window.

`--length 0` means "as much as the cap allows", not "zero bytes".

### Examples

List the root of a scope:

```
connector-server cli --server https://cloud.example:8443 \
    --client-credential "$CONNECTOR_CLI_CLIENT_CREDENTIAL" \
    --node-credential "$CONNECTOR_CLI_NODE_CREDENTIAL" \
    --node-id "$CONNECTOR_CLI_NODE_ID" \
    --scope project \
    file.list
```

Copy a whole file from the remote machine to this one:

```
connector-server cli --server https://cloud.example:8443 \
    --client-credential "$CONNECTOR_CLI_CLIENT_CREDENTIAL" \
    --node-credential "$CONNECTOR_CLI_NODE_CREDENTIAL" \
    --node-id "$CONNECTOR_CLI_NODE_ID" \
    --scope project --path photos/cat.jpg \
    -o cat.jpg file.read
```

Read a small text file straight into a pipeline:

```
connector-server cli ... --scope project --path notes.md -o - file.read
```

Read a byte range:

```
connector-server cli ... --scope project --path big.log --offset 0 --length 4096 file.read
```

Inspect a file without reading it:

```
connector-server cli ... --scope project --path notes.md file.stat
```

Save a directory listing to a local file:

```
connector-server cli ... --scope project -o listing.txt file.list
```

Get the full envelope for scripting:

```
connector-server cli ... --scope project --path notes.md --json file.read
```

`--json` and `-o` cannot be combined. `--json` prints the whole envelope, `-o`
writes the payload; asking for both is refused with exit status `2` rather than
silently picking one.

## Reading the answer

### Exit status

| Status | Meaning |
|---|---|
| `0` | The operation succeeded |
| `1` | The request failed, the Server answered with a non-zero code, or `-o` refused to write |
| `2` | The command line itself was wrong: a missing flag, a bad operation name, a negative offset, `--json` with `-o` |

A shell script can branch on the status. The error code and message go to stderr;
the payload goes to stdout.

One case is worth calling out because it is easy to misread: **an existing `-o`
destination exits `1`, not `2`**, and its message carries no `usage:` prefix. The
refusal happens while the result is being written, after the command line was
accepted and the request ran. Treat `1` as "nothing was written" and `2` as
"nothing was sent".

The prefix and the status agree. Every message beginning `usage:` exits `2`,
including the values checked after the command line is parsed but before the
request is sent — a malformed `--node-id`, a scope name outside the alphabet, a
`--server` URL that is not `http` or `https`. Nothing was sent in any of those
cases, so `2` is the honest answer and a script may branch on either the status or
the prefix.

### Error codes

| Code | Name | What it means | What to do |
|---|---|---|---|
| `0` | `success` | The operation happened | — |
| `1001` | `invalid_argument` | The request is malformed: bad scope name, rejected path, bad JSON, malformed proof | Fix the request. Do not retry |
| `1002` | `unauthenticated` | The client credential was refused, **or** the Node refused the node credential | Check both credentials. Do not retry |
| `1003` | `node_offline` | No live connection for that node id | Retry later; the Node is not connected |
| `1004` | `node_timeout` | The Node did not answer in time | Retry once; if it repeats, the Node is unhealthy |
| `1005` | `denied` | The Node's policy does not allow it | Ask the Node operator to change the policy |
| `1006` | `not_found` | The path does not exist inside the scope | Check the path |
| `1007` | `unsupported_operation` | Unknown operation, or declared but not enabled in this version | Use one of the three read operations |
| `1008` | `too_large` | The response or request exceeds the cap | Use `--offset` and `--length` to read a range |
| `1009` | `internal` | The Server failed | Retry; if it repeats, the Server operator must read the log |
| `1010` | `overloaded` | The Server is at its admission limit and refused the request instead of queueing it | Retry after a short wait; the work already admitted finishes and capacity returns |

`denied` and `not_found` are deliberately different. `denied` means the policy
refused; `not_found` means the policy allowed it and the file is not there. Do not
tell a user "the file does not exist" when the answer was `denied` — that is a
different fact and it is not yours to infer.

### The one ambiguous code

`1002 unauthenticated` covers two different causes: the Server refusing the client
credential, and the Node refusing the node credential. The Server cannot tell them
apart, because it never receives the node secret and cannot check it. To narrow it
down:

1. If the request reached the Server at all (you got a JSON answer rather than a
   connection error), the client credential was accepted and the Node refused the
   node credential.
2. If you got a connection error, the Server was unreachable or the client
   credential was rejected before forwarding.

A node credential that used to work and now does not usually means the Node
operator removed it with `connector-node credential remove`. Ask them for a current
one. Regenerating the node id does **not** invalidate a credential, so a node id
change alone is not the cause.

### Why a request cannot simply be resent

Each request carries a timestamp and a one-time nonce, and both verifiers remember
the nonces they have seen. A request resent byte for byte is refused as a replay,
even though its credentials are still valid. The CLI generates a fresh timestamp
and nonce on every invocation, so **re-running the command is correct and resending
a captured request is not**.

If you write your own client instead of using the CLI, you must generate a new
nonce per attempt. Reusing one is the mistake that produces an `unauthenticated`
answer from a credential that is actually correct.

## Common Pitfalls

- **Flags after the operation.** `cli file.read --scope project` fails with a
  positional-argument error. Flags go first, always.
- **Passing only the node id.** `--node-id node_7f3a...` without a node credential
  is refused locally before anything is sent. Both are required.
- **Swapping the two credentials.** The client credential and the node credential
  are different values checked by different parties. Passing one where the other
  belongs produces `unauthenticated` with no hint about which was wrong.
- **Trimming whitespace from a copied credential.** A credential with a leading or
  trailing space is refused rather than trimmed, because trimming would hide a
  copy-paste error. Re-copy it cleanly.
- **Assuming `--path` is a filesystem path.** It is relative to the scope root and
  is not a path on the Server. `..`, a leading `/`, a backslash, a colon and a NUL
  byte are all refused with `invalid_argument`.
- **Assuming `.` means the scope root.** `--path .` is refused, because a `.`
  component is rejected rather than normalised. Use an empty `--path` to list the
  root.
- **Retrying `denied` or `unauthenticated`.** Neither becomes true by trying
  again. Only `node_offline`, `node_timeout`, `overloaded` and `internal` are worth
  a retry.
- **Reporting a secret.** Never print the secret half of either credential in a
  message, a log or a ticket. The `key_id` half and the node id are public and are
  fine to show.
- **Expecting a write.** `file.write` and `command.exec` are refused in this
  version. Do not offer them as an option.
- **Assuming `file.read > out.bin` copies a whole file.** It copies one capped
  response, at most 256 KiB. Use `-o out.bin` when the file may be larger, and
  treat a redirect as correct only for a file you know is small.
- **Expecting `-o` to overwrite silently.** An existing destination is refused
  with `... already exists; pass --force to replace it` and exit status `1`. Add
  `--force` when you mean to replace it.
- **Writing `-o` with no value.** `-o ""` is refused with
  `usage: -o needs a destination; use - for stdout or a file path` and exit
  status `2`. An empty value is not the same as leaving `-o` out.
- **Adding `--force` without `-o`.** It is refused with
  `usage: --force requires -o` and exit status `2`, because there is nothing to
  replace.
- **Combining `--json` with `-o`.** They are refused together with
  `usage: --json and -o cannot be combined; --json prints the envelope and -o
  writes the payload`, exit status `2`. Pick one.
- **Assuming the `-o` path is remote.** `--path` is relative to the scope root on
  the Node; `-o` is a path on the machine running the CLI. The two follow
  different rules, and `-o` may be absolute.

## Verification Checklist

- [ ] Every flag precedes the operation name.
- [ ] `--client-credential` holds a `key_id.secret` value from the Server operator.
- [ ] `--node-credential` holds a `key_id.secret` value from the Node operator.
- [ ] `--node-id` holds a `node_` identifier, and is not used as a credential.
- [ ] `--scope` names a scope the Node's policy defines, not a directory path.
- [ ] `--path` is relative, contains no `..`, `.`, backslash, colon or NUL byte.
- [ ] The operation is one of `file.list`, `file.stat`, `file.read`.
- [ ] A whole-file copy used `-o`, not a shell redirect, when the file may exceed
      256 KiB.
- [ ] `--force` was added only when replacing an existing local file on purpose.
- [ ] `--json` and `-o` were not combined.
- [ ] The `-o` destination is a path on this machine, not a path inside the scope.
- [ ] The exit status was checked, not just the printed output.
- [ ] A non-zero code was explained from the error table, not guessed.
- [ ] No secret appears in anything you printed or reported.
