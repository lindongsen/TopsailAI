---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-20
---

# The startup summary prints an https CLI address for a plaintext Server

## Symptom

A Node started with `ws://192.168.2.3:8743/channel` prints:

```
To reach this node from a CLI, set:
  CONNECTOR_CLI_SERVER_URL=https://192.168.2.3:8743
```

Copying that line and calling the CLI fails:

```
connector-cli: call server: Post "https://192.168.2.3:8743/v1/nodes/node_.../operations":
http: server gave HTTP response to HTTPS client
rc=1
```

The same request with `http://192.168.2.3:8743` returns `rc=0`.

## Root cause

`cliServerURL` in `cmd/connector-node/startup.go` strips the `ws://` or `wss://`
prefix and then unconditionally prepends `https://`:

```go
for _, prefix := range []string{"wss://", "ws://"} {
    ...
}
...
return "https://" + trimmed
```

The scheme of the channel address is discarded, so the two cases that must differ
produce the same output. `ws://` is a plaintext WebSocket and its HTTP counterpart
is `http://`; `wss://` is a TLS WebSocket and its counterpart is `https://`.

## Why the test did not catch it

`TestCLIServerURLRewritesTheChannelAddress` in `cmd/connector-node/main_test.go`
asserts the wrong answer as the expected value:

```go
{"ws with channel path", "ws://192.168.2.3:8743/channel", "https://192.168.2.3:8743"},
```

The test passes because it encodes the defect. This is the "a test can encode the
bug it is testing" failure mode: the case was written by reading the implementation
rather than by asking what the operator needs, so the implementation's mistake
became the specification.

The integration test `TestPrintStartupSummary` also asserts
`CONNECTOR_CLI_SERVER_URL=https://127.0.0.1:8443` while its fixture dials
`wss://127.0.0.1:8443/channel`, so it is consistent with the defect rather than
with the product.

## Consequence

The summary is the only place an operator learns the CLI address. A wrong scheme
there is worse than an omission, because it looks authoritative: the operator
copies four lines, the first one is wrong, and the failure message names TLS
rather than the summary that produced it. The operator then looks for a
certificate problem that does not exist.

## Fix

Map the scheme instead of replacing it:

| Channel scheme | CLI scheme |
|---|---|
| `ws://` | `http://` |
| `wss://` | `https://` |

An address with neither prefix keeps the current behaviour of assuming TLS, which
is the safe default for a deployment that reached the summary without a scheme.

## Verification required

- `cliServerURL("ws://host:port/channel")` returns `http://host:port`.
- `cliServerURL("wss://host:port/channel")` returns `https://host:port`.
- The existing `wss` cases keep their expected values, so the change is scoped to
  the plaintext case.
- The integration test fixture must dial `ws://` and assert `http://`, so the pair
  is measured together rather than each half separately.
- A live call using the printed line must return `rc=0` against the deployed
  plaintext Server.
- Mutate the fix back to the unconditional `https://` and confirm the test fails.

## Resolution

Fixed in `cmd/connector-node/startup.go`: `cliServerURL` maps the channel scheme
instead of replacing it. `ws://` yields `http://`, `wss://` yields `https://`, and
an address with no scheme keeps `https://` as the safe default.

The test that encoded the defect was corrected rather than supplemented.
`TestCLIServerURLRewritesTheChannelAddress` asserted
`{"ws with channel path", "ws://192.168.2.3:8743/channel", "https://192.168.2.3:8743"}`,
which is the wrong answer written down as the expected value, so it passed for as
long as the defect existed. Two `ws` cases were added beside it, and a new
`TestRunNodeWithOutputPrintsThePlaintextCLIAddress` dials `ws://` and asserts both
the `server :` line and the `CONNECTOR_CLI_SERVER_URL=http://` line together, plus a
negative assertion that no `https://` address appears. The old integration test
dialled `wss://` and asserted `https://`, which is consistent with either
implementation and therefore could not detect the defect.

Mutation evidence: reverting the mapping made four assertions fail — the new
integration test and the three `ws` sub-cases. The file was restored and its md5
compared with the pre-mutation value.

Live evidence on Windows: a Node started from the rebuilt desktop binary with
`ws://192.168.2.3:8743/channel` printed
`CONNECTOR_CLI_SERVER_URL=http://192.168.2.3:8743`, and that printed line used
unchanged returned `rc=0` for `file.stat` and `file.read`. The same line with
`https://` returns `rc=1` with `http: server gave HTTP response to HTTPS client`.

The desktop `README.txt` was corrected in the same change, because it told the
reader to copy the `https://` line the binary no longer prints.
