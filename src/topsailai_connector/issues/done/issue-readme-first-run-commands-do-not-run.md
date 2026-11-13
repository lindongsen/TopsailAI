---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-13
updated: 2026-11-13
---

# The README first-run block documented four commands that do not run

## Symptom

`README.md` "First run" told a new operator to run four commands. None of the
four worked. Each one was executed verbatim on the build host and refused:

| Documented command | Actual result |
|---|---|
| `connector-server -listen :8443` | `flag provided but not defined: -listen` |
| `connector-node -server wss://host/channel` | `flag provided but not defined: -server` |
| `connector-server file read --scope project --path a.txt` | `unknown command "file"; want run or cli` |
| `connector-server cli --scope project --path a.txt file.read` | `--server or CONNECTOR_CLI_SERVER_URL is required` |

## Root cause

The README was written from the design intent rather than from the implemented
interface, and it was never executed.

- `runServer` builds a `flag.FlagSet` and registers **no** flags. The listen
  address comes only from `CONNECTOR_SERVER_LISTEN`, so `-listen` cannot exist.
- `connector-node run` likewise registers no flags; the server address comes from
  `CONNECTOR_NODE_SERVER_URL`.
- The CLI is a subcommand, `cli`, not a bare operation word. `splitCommand` treats
  a leading non-command word as an unknown command rather than as the default
  subcommand, which is deliberate: a typo must not silently start the Server.
- `parseArguments` uses `flag.Parse`, which stops at the first positional
  argument, so every flag must precede the operation name.

## Fix

The block now shows the interfaces that exist:

```
CONNECTOR_SERVER_TUNNEL_TOKEN=<secret> CONNECTOR_SERVER_CLIENT_TOKEN=<secret> \
CONNECTOR_SERVER_LISTEN=:8443 \
  connector-server run

connector-node id

CONNECTOR_NODE_TUNNEL_TOKEN=<secret> \
CONNECTOR_NODE_SERVER_URL=wss://host/channel \
  connector-node run

CONNECTOR_CLI_CLIENT_TOKEN=<secret> \
CONNECTOR_CLI_NODE=node_7f3a...9c1e.9f2b...4d7a \
  connector-server cli --server https://host --scope project --path a.txt file.read
```

The corrected CLI form was executed against a live Server and Node and returned
the file content with `rc=0`.

## Why it was not caught

`docs/API.md` had already been corrected for the same argument-order defect in
`issues/done/issue-cli-example-contradicts-argument-order.md`, but the fix was
applied to the API document only. The README carried the same wrong shape and was
not searched for, because the earlier fix was scoped to one file rather than to
the claim.

## Prevention

- A documented command is a claim about behaviour. Execute it before publishing
  it, and execute it again after changing the interface it names.
- When a defect is found in one document, search every document for the same
  claim. The same wrong example existed in two files and only one was fixed.
