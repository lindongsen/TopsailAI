---
name: connector-client
description: Use when a user wants to read files on a remote machine through the TopsailAI Connector, i.e. when they ask to list a directory, inspect a file, or read a file on a Node they can address, or when they hit an error code such as unauthenticated, denied, not_found or node_offline and need to know what it means and what to do next. Covers the connector-server cli command, its flags, the node-id.node-token pair, the three read-only operations and every error code.
version: 1.0.0
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
2. **The CLI carries two secrets.** A `client_token` proves you may use the Server.
   A `node-id.node-token` pair proves you may talk to that one Node. Each is
   checked by a different party.
3. **The first version is read-only.** Only `file.list`, `file.stat` and
   `file.read` exist. Writing and running commands are refused by design.

## When to Use

Use this skill when the user asks to:

- List, inspect or read a file on a remote machine they reach through the Connector.
- Work out why a Connector request failed, from an error code or a message.
- Set up a script that calls the Connector repeatedly.
- Understand what the `node-id.node-token` pair is and where to get it.

Do **not** use this skill to deploy or operate the Server (that is
`connector-server-operations`) or to install and configure the Node (that is
`connector-node-setup`).

## Before the first request

You need three values. Ask the user for whichever is missing; never invent one.

| Value | What it looks like | Where it comes from |
|---|---|---|
| Server URL | `https://cloud.example:8443` | The Server operator |
| `client_token` | an opaque string, at least 16 bytes | The Server operator |
| `node-id.node-token` pair | `node_7f3a...9c1e.kQ2v...4d7a` | The Node operator, from `connector-node id` |

The pair is **one string with one dot in it**. The part before the dot is the
`node-id`, which is public and is an address. The part after the dot is the
`node-token`, which is a secret. The CLI splits it for you; you always pass the
whole pair to `--node`.

If the user has only a `node-id` and no token, they cannot proceed. A `node-id`
grants nothing on its own. Tell them to run `connector-node id` on the Node
machine, or to ask whoever set the Node up.

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
| `--client-token` | `CONNECTOR_CLI_CLIENT_TOKEN` | yes | The `client_token` |
| `--node` | `CONNECTOR_CLI_NODE` | yes | The whole `node-id.node-token` pair |
| `--scope` | none | yes | A scope name the Node's policy defines |
| `--path` | none | no | Relative path inside the scope; empty means the scope root |
| `--offset` | none | no | Byte offset for `file.read`, default `0` |
| `--length` | none | no | Byte count for `file.read`; `0` means up to the cap |
| `--request-id` | none | no | Correlation id echoed by the Server |
| `--json` | none | no | Print the whole response envelope instead of the payload |

A flag wins over its environment variable. The environment exists so a script can
export a value once instead of repeating it on every line.

### Operations

| Operation | Needs `--path` | Returns |
|---|---|---|
| `file.list` | no; empty lists the scope root | `entries`: name, type, size, mode, modified_at |
| `file.stat` | yes | `type`, `size`, `mode`, `modified_at`, `is_symlink`, `link_target` |
| `file.read` | yes | the file content on stdout, plus `size` and `truncated` |

`file.stat` reports a symlink **without following it**, so `is_symlink` and
`link_target` describe the link itself. That is deliberate: following a link is
exactly the operation the Node's path fence refuses.

### Examples

List the root of a scope:

```
connector-server cli --server https://cloud.example:8443 \
    --client-token "$CONNECTOR_CLI_CLIENT_TOKEN" \
    --node "$CONNECTOR_CLI_NODE" \
    --scope project \
    file.list
```

Read a file into a pipeline:

```
connector-server cli --server https://cloud.example:8443 \
    --client-token "$CONNECTOR_CLI_CLIENT_TOKEN" \
    --node "$CONNECTOR_CLI_NODE" \
    --scope project --path notes.md \
    file.read > notes.md
```

`file.read` writes raw bytes to stdout, not JSON, so it pipes cleanly. A truncation
notice goes to stderr, never to stdout, so it cannot corrupt a piped payload.

Read a byte range:

```
connector-server cli ... --scope project --path big.log --offset 0 --length 4096 file.read
```

Inspect a file without reading it:

```
connector-server cli ... --scope project --path notes.md file.stat
```

Get the full envelope for scripting:

```
connector-server cli ... --scope project --path notes.md --json file.read
```

## Reading the answer

### Exit status

| Status | Meaning |
|---|---|
| `0` | The operation succeeded |
| `1` | The request failed, or the Server answered with a non-zero code |
| `2` | The command line itself was wrong: a missing flag, a bad operation name, a negative offset |

A shell script can branch on the status. The error code and message go to stderr;
the payload goes to stdout.

### Error codes

| Code | Name | What it means | What to do |
|---|---|---|---|
| `0` | `success` | The operation happened | — |
| `1001` | `invalid_argument` | The request is malformed: bad scope name, rejected path, bad JSON | Fix the request. Do not retry |
| `1002` | `unauthenticated` | `client_token` is wrong or missing, **or** the Node refused the `node-token` | Check both secrets. Do not retry |
| `1003` | `node_offline` | No live connection for that `node_id` | Retry later; the Node is not connected |
| `1004` | `node_timeout` | The Node did not answer in time | Retry once; if it repeats, the Node is unhealthy |
| `1005` | `denied` | The Node's policy does not allow it | Ask the Node operator to change the policy |
| `1006` | `not_found` | The path does not exist inside the scope | Check the path |
| `1007` | `unsupported_operation` | Unknown operation, or declared but not enabled in this version | Use one of the three read operations |
| `1008` | `too_large` | The response or request exceeds the cap | Use `--offset` and `--length` to read a range |
| `1009` | `internal` | The Server failed | Retry; if it repeats, the Server operator must read the log |

`denied` and `not_found` are deliberately different. `denied` means the policy
refused; `not_found` means the policy allowed it and the file is not there. Do not
tell a user "the file does not exist" when the answer was `denied` — that is a
different fact and it is not yours to infer.

### The one ambiguous code

`1002 unauthenticated` covers two different causes: a wrong `client_token`, and a
Node refusing the `node-token`. The Server cannot tell them apart, because it never
learns the correct `node-token`. To narrow it down:

1. If the request reached the Server at all (you got a JSON answer rather than a
   connection error), the `client_token` was accepted and the Node refused the
   token.
2. If you got a connection error, the Server was unreachable or the
   `client_token` was rejected before forwarding.

A `node-token` that used to work and now does not usually means the Node was
regenerated. Ask the Node operator for the new pair.

## Common Pitfalls

- **Flags after the operation.** `cli file.read --scope project` fails with a
  positional-argument error. Flags go first, always.
- **Passing only the `node-id`.** `--node node_7f3a...` without the dot and the
  token is refused locally before anything is sent. The whole pair is required.
- **Passing the two halves separately.** There is no `--node-id` and no
  `--node-token` flag. One `--node` value holds both.
- **Trimming whitespace from a copied pair.** A pair with a leading or trailing
  space is refused rather than trimmed, because trimming would hide a copy-paste
  error. Re-copy it cleanly.
- **Assuming `--path` is a filesystem path.** It is relative to the scope root and
  is not a path on the Server. `..`, a leading `/`, a backslash, a colon and a NUL
  byte are all refused with `invalid_argument`.
- **Assuming `.` means the scope root.** `--path .` is refused, because a `.`
  component is rejected rather than normalised. Use an empty `--path` to list the
  root.
- **Retrying `denied` or `unauthenticated`.** Neither becomes true by trying
  again. Only `node_offline`, `node_timeout` and `internal` are worth a retry.
- **Reporting a secret.** Never print `client_token` or the `node-token` half in a
  message, a log or a ticket. The `node-id` half is public and is fine to show.
- **Expecting a write.** `file.write` and `command.exec` are refused in this
  version. Do not offer them as an option.

## Verification Checklist

- [ ] Every flag precedes the operation name.
- [ ] `--node` holds the whole `node-id.node-token` pair, with exactly one dot.
- [ ] `--scope` names a scope the Node's policy defines, not a directory path.
- [ ] `--path` is relative, contains no `..`, `.`, backslash, colon or NUL byte.
- [ ] The operation is one of `file.list`, `file.stat`, `file.read`.
- [ ] The exit status was checked, not just the printed output.
- [ ] A non-zero code was explained from the error table, not guessed.
- [ ] No secret appears in anything you printed or reported.
