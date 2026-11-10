---
maintainer: AI
author: DawsonLin
---

# Test Cases: The Three Secret Gates

Each secret is validated by exactly one party. These cases check that each gate
admits the right value, refuses the wrong one, and refuses for the right reason.

## The tunnel gate

### TC-SEC-1: `tunnel_token` admits a Node

**Precondition:** Server started with `CONNECTOR_SERVER_TUNNEL_TOKEN=alpha`.

**Action:** Node sends `hello` with `tunnel_token=alpha`.

**Expected:** `hello_confirm` is returned and the channel stays open.

### TC-SEC-2: A wrong `tunnel_token` is refused

**Precondition:** Server started with `CONNECTOR_SERVER_TUNNEL_TOKEN=alpha`.

**Action:** Node sends `hello` with `tunnel_token=beta`.

**Expected:** The connection closes with `denied`. No frame is accepted after
`hello`.

### TC-SEC-3: An empty `tunnel_token` is refused

**Precondition:** Server started with `CONNECTOR_SERVER_TUNNEL_TOKEN=alpha`.

**Action:** Node sends `hello` with `tunnel_token=""`.

**Expected:** `denied`. An empty value is not treated as "no authentication
required".

### TC-SEC-4: A missing `tunnel_token` field is refused

**Precondition:** Server started with `CONNECTOR_SERVER_TUNNEL_TOKEN=alpha`.

**Action:** Node sends `hello` with no `tunnel_token` field.

**Expected:** `denied`. A missing field and an empty field produce the same
error, so a caller cannot tell which one it sent.

### TC-SEC-5: A prefix of `tunnel_token` is refused

**Precondition:** Server started with `CONNECTOR_SERVER_TUNNEL_TOKEN=alpha123456`.

**Action:** Node sends `hello` with `tunnel_token=alpha`.

**Expected:** `denied`. A prefix check would turn a long secret into a short
one, so the comparison is over the whole value.

### TC-SEC-6: A `tunnel_token` with trailing whitespace is refused

**Precondition:** Server started with `CONNECTOR_SERVER_TUNNEL_TOKEN=alpha`.

**Action:** Node sends `hello` with `tunnel_token="alpha "`.

**Expected:** `denied`. The value is not trimmed, because trimming would make
two different strings equivalent and hide a copy-paste error.

### TC-SEC-7: The Server refuses to start without `tunnel_token`

**Precondition:** `CONNECTOR_SERVER_TUNNEL_TOKEN` is unset.

**Action:** Start the Server.

**Expected:** Startup fails with a message naming the variable. The Server does not
start in a mode where any Node may connect.

### TC-SEC-8: The Server refuses to start with an empty `tunnel_token`

**Precondition:** `CONNECTOR_SERVER_TUNNEL_TOKEN=` (set but empty).

**Action:** Start the Server.

**Expected:** Startup fails. An empty value is the most likely way to accidentally
disable authentication, so it is refused rather than accepted.

## The client gate

### TC-SEC-9: `client_token` admits a CLI request

**Precondition:** Server started with `CONNECTOR_SERVER_CLIENT_TOKEN=gamma`, one
Node connected.

**Action:** CLI sends a request with `Authorization: Bearer gamma`.

**Expected:** The request is forwarded to the Node.

### TC-SEC-10: A wrong `client_token` is refused before forwarding

**Precondition:** Server started with `CONNECTOR_SERVER_CLIENT_TOKEN=gamma`, one
Node connected.

**Action:** CLI sends a request with `Authorization: Bearer delta`.

**Expected:** `denied`, and **the Node receives nothing**. The case asserts
the absence of a forwarded frame, because a refusal that still forwards has not
protected the Node.

### TC-SEC-11: A missing `Authorization` header is refused

**Precondition:** Server started with `CONNECTOR_SERVER_CLIENT_TOKEN=gamma`.

**Action:** CLI sends a request with no `Authorization` header.

**Expected:** `denied`.

### TC-SEC-12: A `client_token` in the URL is not accepted

**Precondition:** Server started with `CONNECTOR_SERVER_CLIENT_TOKEN=gamma`.

**Action:** CLI sends `GET /v1/nodes/node_x/operations?client_token=gamma`.

**Expected:** `denied`. A secret in a URL lands in access logs, proxy logs and
`Referer` headers, so the query string is not a credential channel.

### TC-SEC-13: `client_token` does not authorise an operation

**Precondition:** Server started with `CONNECTOR_SERVER_CLIENT_TOKEN=gamma`. Node
policy grants `project: [read]`. CLI holds a `node-token` for a different Node.

**Action:** CLI sends a request with a valid `client_token` and a wrong
`node-token`.

**Expected:** The Server forwards, the Node refuses with `denied`. The
`client_token` proves the caller may use the Server and proves nothing about the
operation.

## The node gate

### TC-SEC-14: `node-token` admits one operation

**Precondition:** Node holds `node_abc.def`, policy grants `project: [read]`.

**Action:** CLI sends `file.read` on `project` with `node-token=def`.

**Expected:** The file content is returned.

### TC-SEC-15: A wrong `node-token` is refused by the Node

**Precondition:** Node holds `node_abc.def`.

**Action:** CLI sends a request with `node-token=xyz`.

**Expected:** `denied` from the Node. The Server forwarded it, because the
Server cannot check it.

### TC-SEC-16: The Server never learns the correct `node-token`

**Precondition:** Node holds `node_abc.def`, one request served.

**Action:** Inspect every Server-side observable: logs, any config dump, any
in-memory structure reachable through a debug endpoint.

**Expected:** The string `def` appears nowhere. This is the case that verifies the
hard principle, and it is the one that must never be deleted.

### TC-SEC-17: The Server does not log the `node-token` on a refusal

**Precondition:** Node holds `node_abc.def`.

**Action:** CLI sends a request with `node-token=xyz`, which the Node refuses.

**Expected:** The Server's log records the refusal and the `node-id`, and does not
record `xyz`. A refusal path is where a token most often reaches a log, because the
error message is written by whoever noticed the problem.

## Retention and logging

### TC-SEC-18: The Server does not log `client_token`

**Precondition:** Server started with `CONNECTOR_SERVER_CLIENT_TOKEN=gamma`.

**Action:** Serve one successful request and one refused request.

**Expected:** `gamma` appears in no log line, at any level, including `debug`.

### TC-SEC-19: A `node-token` is not retained after forwarding

**Precondition:** Node holds `node_abc.def`, one request served.

**Action:** Serve a second request for the same Node, then inspect the Server's
memory for a copy of `def` from the first request.

**Expected:** No copy survives the first request. The second request carries its own
value, read from the caller.

### TC-SEC-20: A retry re-reads the secret from the caller

**Precondition:** Node holds `node_abc.def`. The first attempt times out.

**Action:** The Server retries the request.

**Expected:** The retry carries the value the caller sent, not a stored copy. If the
caller sends a different `node-token` on the retry, the retry uses the new value.

## Comparison

### TC-SEC-21: Comparison is constant time

**Precondition:** A unit test with a comparison helper.

**Action:** Compare a correct secret, a secret differing in the first byte, and a
secret differing in the last byte, measuring elapsed time over many iterations.

**Expected:** The three timings are indistinguishable. An early return leaks the
length of the matching prefix, which lets an attacker recover a secret one byte at
a time.

**Note:** this case is inherently statistical. It asserts that no branch returns
early, by reading the implementation, and uses timing only as a secondary signal.

### TC-SEC-22: Every mismatch produces the same error

**Precondition:** Server started with `CONNECTOR_SERVER_CLIENT_TOKEN=gamma`.

**Action:** Send four requests: no header, empty header, wrong value, value that is
a prefix of the correct one.

**Expected:** All four return the identical error code and the identical message. A
distinguishable error tells an attacker whether a guess was close.

### TC-SEC-23: `tunnel_token` and `client_token` are not interchangeable

**Precondition:** Server started with `CONNECTOR_SERVER_TUNNEL_TOKEN=alpha` and
`CONNECTOR_SERVER_CLIENT_TOKEN=gamma`.

**Action:** Send `hello` with `tunnel_token=gamma`, and send a CLI request with
`Authorization: Bearer alpha`.

**Expected:** Both are refused. Two secrets that both work at both gates are one
secret with two names.

## Rotation

### TC-SEC-24: Rotating `client_token` invalidates the old value

**Precondition:** Server started with `CONNECTOR_SERVER_CLIENT_TOKEN=gamma`.

**Action:** Restart the Server with `CONNECTOR_SERVER_CLIENT_TOKEN=gamma2`, then
send a request with `gamma`.

**Expected:** `denied`. There is no grace period, because a grace period is a
second valid credential.

### TC-SEC-25: Rotating `tunnel_token` drops live channels

**Precondition:** One Node connected with `tunnel_token=alpha`.

**Action:** Restart the Server with `CONNECTOR_SERVER_TUNNEL_TOKEN=alpha2`.

**Expected:** The Node's channel is gone and it must reconnect with the new value.
A channel that survived a credential change would be authenticated by a credential
that no longer exists.

## Output hygiene

### TC-SEC-26: A secret is not echoed by `--help`

**Precondition:** `CONNECTOR_CLI_CLIENT_TOKEN=gamma` is set.

**Action:** Run `connector-server --help` and every subcommand's `--help`.

**Expected:** `gamma` appears in no output.

### TC-SEC-27: A secret is not echoed by a configuration dump

**Precondition:** All secrets set.

**Action:** Run any command that prints effective configuration.

**Expected:** Each secret is printed as `<set>` or `<redacted>`, never as its value.

### TC-SEC-28: A secret is not placed in a URL by the CLI

**Precondition:** `CONNECTOR_CLI_CLIENT_TOKEN=gamma`.

**Action:** Run a request against a local listener that records the request line.

**Expected:** The recorded request line contains no secret. The `client_token` is in
the `Authorization` header and the `node-token` is in `X-Connector-Node-Token`.
