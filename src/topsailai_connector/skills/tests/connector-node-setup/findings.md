---
maintainer: AI
author: DawsonLin
---

# connector-node-setup: executed evidence for `scope list`

Every claim the skill makes about `scope list` was executed against the built
binary, not read off the source. The binary under test is `bin/connector-node`
built by `make build` from commit `648eef5b`.

## Environment

| Item | Value |
|---|---|
| Host | Linux, Go 1.25.12 |
| Binary | `bin/connector-node` |
| Live Node | started in tmux session `skillverify`, policy with two scopes |
| Live policy | `project` -> `.tmp/e2e/scope` with `[read, list, stat]`; `readonly` -> `.tmp/e2e/scope2` with `[read]` |

## Claim: the command prints the scope names, one per line, sorted

Command:

```
CONNECTOR_NODE_CONFIG_DIR=.tmp/e2e/node-config connector-node scope list
```

Expected: `project` then `readonly`, one per line, sorted, nothing else.
Actual:

```
project
readonly
```

Status: PASS. Exit status 0.

## Claim: it prints names, never paths

Command:

```
connector-node scope list | grep -c '/TopsailAI'
```

Expected: 0, because a path is the machine's filesystem layout and does not help
anyone fill `--scope`.
Actual: `0`.

Status: PASS.

## Claim: it works before the first start and where a scope directory does not exist

This is the load-bearing claim, because it is the reason the command does not open
scopes. A fresh config directory was created holding only a policy whose scope path
does not exist, and no `identity` file.

Command:

```
CONNECTOR_NODE_CONFIG_DIR=.tmp/skilltest/fresh connector-node scope list
```

Expected: `notyet`, exit 0, even though `.tmp/skilltest/does-not-exist` was never
created and no identity file existed.
Actual: `notyet`, exit 0. The config directory contained only `policy.yaml`.

Status: PASS. This is the case a fence-opening implementation would have failed.

## Claim: an empty policy prints nothing and exits 0

Command:

```
CONNECTOR_NODE_POLICY_FILE=.tmp/skilltest/fresh/empty.yaml connector-node scope list
```

Expected: no output, exit 0, because an empty policy is a valid document that
refuses every request rather than an error.
Actual: no output, exit 0.

Status: PASS.

## Claim: a missing policy exits 1 and names the path

Command:

```
CONNECTOR_NODE_CONFIG_DIR=.tmp/skilltest/nonexistent connector-node scope list
```

Expected: exit 1 with a message naming the missing file.
Actual: exit 1, `connector-node: policy file is missing: /TopsailAI/src/topsailai_connector/.tmp/skilltest/nonexistent/policy.yaml`.

Status: PASS.

## Claim: a malformed policy exits 1 and reports the same reason `run` reports

Command:

```
CONNECTOR_NODE_POLICY_FILE=.tmp/skilltest/fresh/bad.yaml connector-node scope list
```

Expected: exit 1, naming the relative scope path.
Actual: exit 1, `connector-node: scope "bad": path "rel/path" is relative; a relative path resolves differently per launch`.

The same policy through `run`:

```
CONNECTOR_NODE_TUNNEL_TOKEN=0123456789abcdef0123456789abcdef connector-node run
```

Actual: exit 1, `connector-node: load authority: scope "bad": path "rel/path" is relative; a relative path resolves differently per launch`.

Status: PASS after a wording correction. The reason is identical but the prefix
differs (`load authority: `), and the skill originally claimed "the message the Node
would print", which is not literally true. The skill now states the difference and
quotes both forms, because a documented message must be the string the program
emits.

## Claim: exit status 2 for a rejected command line

| Command | Expected | Actual | Status |
|---|---|---|---|
| `connector-node scope` | 2, `usage: scope needs a subcommand: list` | 2, same | PASS |
| `connector-node scope lst` | 2, `usage: unknown scope subcommand "lst"; want list` | 2, same | PASS |
| `connector-node scope list project` | 2, `usage: unexpected argument "project"; want flags only` | 2, same | PASS |

## Claim: a relative CONFIG_DIR is refused

Command:

```
CONNECTOR_NODE_CONFIG_DIR=relative/dir connector-node scope list
```

Expected: exit 1, because a relative path resolves differently per launch.
Actual: exit 1, `connector-node: CONNECTOR_NODE_CONFIG_DIR "relative/dir" is relative; a relative path resolves differently per launch`.

Status: PASS.

## Claim: an embedded build lists the scopes it carries and refuses a policy file

Built with `-ldflags "-X .../embedded.PolicyBase64=<base64> -X .../embedded.ServerURL=..."`.

| Command | Expected | Actual | Status |
|---|---|---|---|
| `scope list` on the embedded build | the two embedded names, exit 0 | `embeddedone`, `embeddedtwo`, exit 0 | PASS |
| `scope list` with `CONNECTOR_NODE_POLICY_FILE` set | exit 1, refusing the second source | exit 1, `CONNECTOR_NODE_POLICY_FILE is set but this build compiled its policy in; ...` | PASS |

## Claim: the help page documents the command

Command:

```
connector-node help scope
```

Expected: NAME, SYNOPSIS, DESCRIPTION, SUBCOMMANDS, ENVIRONMENT, EXIT STATUS and
EXAMPLES sections, and the main SYNOPSIS listing `scope list`.
Actual: all seven sections present; the DESCRIPTION states why a caller cannot ask
the Node and why names are printed rather than paths.

Status: PASS.

## Limitations

- The Windows behaviour of `scope list` was not executed on this host. The command
  reads a YAML document and prints strings, so it has no platform-specific path
  logic, but that is an argument rather than a measurement.
- The embedded-build cases were run against a throwaway binary built for this
  check, not against a shipped artifact.
