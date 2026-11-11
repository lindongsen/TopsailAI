---
maintainer: AI
author: DawsonLin
status: done
severity: medium
created: 2026-11-11
fixed: 2026-11-11
platform: all
---

# `connector-node id` requires the dial configuration it does not use

## Symptom

On a fresh machine, the documented first-run sequence fails at step 2:

```
C:\connector> .\connector-node.exe id
connector-node: CONNECTOR_NODE_SERVER_URL is empty; the Node has no address to dial
```

Setting only the URL moves the failure to the next variable:

```
C:\connector> set CONNECTOR_NODE_TUNNEL_TOKEN=
C:\connector> .\connector-node.exe id
connector-node: CONNECTOR_NODE_TUNNEL_TOKEN is empty; an empty secret is a startup failure, not a disabled check
```

So `id` requires both `CONNECTOR_NODE_SERVER_URL` and
`CONNECTOR_NODE_TUNNEL_TOKEN` before it will print the pair.

## Why this is a defect

`id` performs no network work. It resolves the config directory, loads or
creates the identity file and prints the pair. The dial target and the tunnel
token are irrelevant to that.

Two documents state the opposite of what the code does:

- `docs/Environment_Variables.md` line 95 describes `id` as "Print the
  `node-id.node-token` pair and nothing else".
- `README.md` step 2 runs `connector-node id` and step 3 supplies the
  `tunnel_token`. The documented order is therefore impossible: step 2 cannot
  run before step 3.

The consequence is worse than an inconvenience. The operator is told to run
`id` first, it fails with a message about a server address, and the natural
reading is that the Node needs a server before it can have an identity. That
inverts the design: the Node generates its own identity precisely so it works
without the Server being reachable.

## Root cause

`runID` in `cmd/connector-node/main.go` called the full `node.LoadConfig`, which
validates every field including the dial target:

```go
func runID(arguments []string) error {
	config, err := node.LoadConfig(os.Getenv)   // validates ServerURL and TunnelToken
	...
	identity, _, err := node.EnsureIdentity(node.IdentityPath(config.ConfigDir))
```

`LoadConfig` rejects an empty `CONNECTOR_NODE_SERVER_URL` at `config.go:47-50`
and an empty `CONNECTOR_NODE_TUNNEL_TOKEN` at `config.go:52-55`. `runID` only
needs `ConfigDir`.

`runRegenerate` had the same shape and the same defect.

## Detection failure

The unit tests for `runID` supply a complete environment through
`setNodeEnvironment`, so the missing-field path was never exercised. The
documented first-run order was never executed end-to-end on a clean machine,
which is the only way this surfaces.

## Fix

Added `node.ResolveConfigDir`, a narrow resolver that reads only
`CONNECTOR_NODE_CONFIG_DIR` and keeps the existing directory checks (absolute
path, exists or created, is a directory). `runID` and `runRegenerate` now call it
instead of `LoadConfig`.

`LoadConfig` itself was not relaxed. The dial path still refuses to start without
a secret, because a Node that started without one would be a Node whose operator
believes it is serving something it is not.

| File | Change |
|---|---|
| `internal/node/config.go` | Added `ResolveConfigDir` |
| `cmd/connector-node/main.go` | `runID` and `runRegenerate` use `ResolveConfigDir` |
| `cmd/connector-node/main_test.go` | Added `TestRunIDNeedsOnlyTheConfigDirectory`, `TestRunRegenerateNeedsOnlyTheConfigDirectory`, `TestRunStillRejectsAnIncompleteEnvironment` |
| `internal/node/config_test.go` | Added four `ResolveConfigDir` tests |
| `docs/Environment_Variables.md` | Documented which variables each subcommand requires |

## Verification

The regression tests were run against the unfixed code first, to prove they
catch the defect rather than merely passing:

```
--- FAIL: TestRunIDNeedsOnlyTheConfigDirectory
    run(id) with only the config directory = CONNECTOR_NODE_SERVER_URL is empty; the Node has no address to dial, want nil
--- FAIL: TestRunRegenerateNeedsOnlyTheConfigDirectory
    run(id) = CONNECTOR_NODE_SERVER_URL is empty; the Node has no address to dial, want nil
```

After the fix, on Linux:

```
$ CONNECTOR_NODE_CONFIG_DIR=/tmp/verify-cfg connector-node id
node_6rwoghtl6mj2urqa4i2n76s7q4.2ivnlf5w5mgtkxmrzmvich2xrhxgcgmt4ofxhlfkuflsol7cqigq
exit=0

$ CONNECTOR_NODE_CONFIG_DIR=/tmp/verify-cfg connector-node regenerate --keep-id
node_6rwoghtl6mj2urqa4i2n76s7q4.v3wm3eyrbsf2b3bm5dxjvxgcqywfh7z5fl6lmxsesv5lfmcunkpq
exit=0

$ CONNECTOR_NODE_CONFIG_DIR=/tmp/verify-cfg connector-node run
connector-node: CONNECTOR_NODE_SERVER_URL is empty; the Node has no address to dial
exit=1
```

`go vet ./...` clean, `gofmt -l` clean, `go test ./...` all packages pass.

## Reproduction (before the fix)

```
set CONNECTOR_NODE_CONFIG_DIR=C:\connector\config
.\connector-node.exe id
-> CONNECTOR_NODE_SERVER_URL is empty
```

## Verified on

Windows Server 2022 (10.0.20348.587), `connector-node.exe` built from
`cmd/connector-node` at commit `b544bc19`. Fix verified on Linux amd64.
