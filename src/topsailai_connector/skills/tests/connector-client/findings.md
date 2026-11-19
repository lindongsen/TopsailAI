---
maintainer: AI
author: DawsonLin
---

# connector-client: executed evidence for the scope-name claim

The skill tells a caller that no API lists scope names, and that a request naming
an undefined scope and a request naming a scope without a grant "cannot be told
apart". That second half is a security property, so it was measured over the real
wire rather than argued from the source.

## Environment

| Item | Value |
|---|---|
| Server | `bin/connector-server run` on `127.0.0.1:37837`, started by `tests/e2e/start.sh` |
| Node | `bin/connector-node run` in tmux session `skillverify`, connected as `node_aock2fzmgbpxhjxhxgdk22bk3i` |
| Policy | `project` -> `[read, list, stat]`; `readonly` -> `[read]` |
| CLI | `bin/connector-server cli` with the e2e client credential and node credential |

The policy deliberately holds two scopes so that one refusal comes from an
undefined scope and the other from a defined scope missing the required grant. A
single-scope policy cannot produce both cases.

## Claim: an undefined scope and a missing grant are indistinguishable to the caller

Case 1, undefined scope:

```
connector-server cli --scope absent --path hello.txt file.read
```

Case 2, defined scope without the `list` grant:

```
connector-server cli --scope readonly --path '' file.list
```

| Case | Exit | stdout | stderr |
|---|---|---|---|
| 1, undefined scope | 1 | empty | `connector-server cli: denied: the node refused the operation` |
| 2, no grant | 1 | empty | `connector-server cli: denied: the node refused the operation` |

The two are byte-identical. Status: PASS.

## Control: the credential and the scope really work

Without a control, two identical failures could mean the credential was wrong
rather than that the refusals were deliberately indistinguishable.

```
connector-server cli --scope readonly --path two.txt file.read
```

Expected: the file content, exit 0.
Actual: `second scope`, exit 0.

Status: PASS. The same node credential and the same scope succeed for a granted
operation, so the two refusals above are authorization decisions rather than an
authentication failure.

## The distinction exists on the Node and is withheld from the caller

The Node log records the real reason for each refusal:

```
msg="connector-node refused a request" operation=file.read scope=absent code=denied
  reason="authorization refused: denied: scope \"absent\" does not grant \"read\""
msg="connector-node refused a request" operation=file.list scope=readonly code=denied
  reason="authorization refused: denied: scope \"readonly\" does not grant \"list\""
```

So the Node knows which case it refused, and the caller does not. That is the
property the skill describes, and it is the reason `denied` is one code rather than
two.

The mechanism, confirmed by reading the structs after the measurement: the
dispatcher logs the reason and returns `protocol.Failure(code)`, and
`protocol.Response` carries only `Code`, `Data` and `Content` with no message field.
The differing text therefore has no path to the caller.

Status: PASS.

## Claim: the skill points the caller at the operator

The skill states that the names come from the person who runs the Node, who reads
them with `connector-node scope list`, and that a caller who does not run the Node
must ask its operator. Verified by reading the section, and by the fact that no CLI
subcommand or HTTP endpoint lists scope names:

- `internal/server/listener.go` registers only `/channel` and `/v1/nodes/`.
- The CLI operations are `file.list`, `file.stat` and `file.read` only.

Status: PASS.

## Limitations

- The measurement used a plaintext `http://` listener on loopback. TLS changes
  nothing about the response body, so the result carries over, but that is an
  argument rather than a second measurement.
- The `readonly` scope was added by restarting the Node with an edited policy. The
  Node has no `SIGHUP` reload, so a running Node cannot gain a scope; this is
  consistent with the design document and was confirmed by grepping for `SIGHUP`
  and `Reload` in `internal/node/`.
