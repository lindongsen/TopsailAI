---
maintainer: AI
author: DawsonLin
---

# Test Cases: CLI and Routing

The CLI is a subcommand of the Server binary. These cases check its surface, the
routing decision, and the rule that the `node-id` in the URL and in the pair must
agree.

## CLI surface

### TC-CLI-1: `file read` sends the documented request

**Precondition:** A Node connected, a policy granting `project: [read]`.

**Action:** `connector-server file read --scope project --path notes.md`.

**Expected:** A `POST` to `/v1/nodes/<node-id>/operations` with
`Authorization: Bearer <client_token>`, `X-Connector-Node-Token: <node-token>` and a
body naming `file.read`, `project` and `notes.md`.

### TC-CLI-2: `file list` sends the documented request

**Action:** `connector-server file list --scope project`.

**Expected:** A request naming `file.list`.

### TC-CLI-3: `file stat` sends the documented request

**Action:** `connector-server file stat --scope project --path notes.md`.

**Expected:** A request naming `file.stat`.

### TC-CLI-4: The CLI prints the payload and nothing else

**Action:** `file read` on a file containing `hello`.

**Expected:** `hello` on stdout, with no decoration. A CLI that wrapped the payload
in a status line would make `> out.txt` produce a file with a status line in it.

### TC-CLI-5: The CLI prints a refusal to stderr and exits non-zero

**Action:** `file read` on a path outside the scope.

**Expected:** The error on stderr, nothing on stdout, exit code non-zero. A refusal
that exited zero would be a refusal a script could not detect.

### TC-CLI-6: The CLI exits non-zero on a missing `client_token`

**Precondition:** `CONNECTOR_CLI_CLIENT_TOKEN` is unset.

**Action:** Any operation.

**Expected:** A message naming the variable, exit code non-zero, and no request sent.

### TC-CLI-7: The CLI exits non-zero on a malformed pair

**Precondition:** `CONNECTOR_CLI_NODE=node_abc` (no dot).

**Action:** Any operation.

**Expected:** A message naming the problem, exit code non-zero, and no request sent.
The CLI validates the pair before sending, so a malformed value never reaches the
Server.

### TC-CLI-8: The CLI splits the pair before sending

**Precondition:** `CONNECTOR_CLI_NODE=node_abc.def`.

**Action:** Any operation, against a listener that records the request.

**Expected:** The URL path contains `node_abc` and the header contains `def`. The
whole pair never appears in one place, so the Server never holds a value that is
half public and half secret.

### TC-CLI-9: The CLI does not accept a secret as a flag value

**Action:** `connector-server file read --client-token gamma ...`.

**Expected:** The flag does not exist, or it is refused with a message that the
value would be recorded in the shell history and the process table.

### TC-CLI-10: The CLI does not echo a secret in an error

**Precondition:** A wrong `client_token`.

**Action:** Any operation.

**Expected:** The error names the refusal and does not print the value.

### TC-CLI-11: `--help` lists the operations

**Action:** `connector-server --help`.

**Expected:** `file list`, `file stat`, `file read` are listed, and `file write` and
`command exec` are not. A help text that listed an unimplemented operation would
advertise a capability the binary refuses.

### TC-CLI-12: An unknown subcommand exits non-zero

**Action:** `connector-server file delete ...`.

**Expected:** A message and a non-zero exit code.

### TC-CLI-13: A missing `--scope` exits non-zero

**Action:** `connector-server file read --path notes.md`.

**Expected:** A message naming the missing flag, exit code non-zero, no request sent.

### TC-CLI-14: A missing `--path` exits non-zero for `read`

**Action:** `connector-server file read --scope project`.

**Expected:** A message, exit code non-zero, no request sent.

### TC-CLI-15: `--path` is optional for `list`

**Action:** `connector-server file list --scope project`.

**Expected:** The request names the scope root.

## Routing

### TC-CLI-16: A request is routed to the named Node

**Precondition:** Two Nodes connected, `node_a` and `node_b`.

**Action:** Address `node_a`.

**Expected:** `node_a` serves it and `node_b` receives nothing.

### TC-CLI-17: A request for an unknown `node-id` is refused

**Action:** Address `node_unknown`.

**Expected:** `node_not_connected`. The Server does not forward to any Node.

### TC-CLI-18: A request for a disconnected Node is refused

**Precondition:** A Node was connected and has disconnected.

**Action:** Address it.

**Expected:** `node_not_connected`, immediately. The request is not queued.

**Why this case exists:** a queued request would execute later without the operator
knowing, and the operator would have no way to cancel it.

### TC-CLI-19: A request for a Node that never connected is refused

**Action:** Address a `node-id` that has never been seen.

**Expected:** `node_not_connected`. The error is the same as for a disconnected Node,
so a caller cannot tell which Nodes exist.

### TC-CLI-20: The `node-id` in the URL and in the pair must agree

**Precondition:** Two Nodes connected.

**Action:** Address `node_a` with `node_b`'s `node-token`.

**Expected:** `invalid_argument` from the Server, before forwarding. The Server can
see both halves of the address, so a disagreement is a malformed request rather than
an authentication failure.

### TC-CLI-21: A `node-id` in the URL with no pair is refused

**Action:** Send a request with no `X-Connector-Node-Token` header.

**Expected:** `invalid_argument`. The Server needs both halves to route and to
forward.

### TC-CLI-22: A pair with no `node-id` in the URL is refused

**Action:** Send a request to `/v1/nodes//operations`.

**Expected:** `invalid_argument`.

### TC-CLI-23: The Server does not check whether the `node-token` is correct

**Precondition:** A Node connected.

**Action:** Send a request with a wrong `node-token`.

**Expected:** The Server forwards it and the Node refuses. The Server cannot check
the value, so a Server-side refusal would mean the Server had learned it.

### TC-CLI-24: A second connection for the same `node-id` follows the documented rule

**Precondition:** `node_a` is connected.

**Action:** Connect a second channel claiming `node_a`.

**Expected:** The behaviour matches the design decision: either the new connection
replaces the old one, or it is refused. The case verifies the decision is enforced
rather than left to chance.

### TC-CLI-25: A request is not forwarded to a Node that has not completed `hello`

**Precondition:** A connection that has sent `hello` but not received
`hello_confirm`.

**Action:** Address it.

**Expected:** `node_not_connected`. A half-open connection is not a route.

## Timeouts

### TC-CLI-26: A Node that does not answer produces a timeout

**Precondition:** A Node that accepts a request and never responds.

**Action:** Address it.

**Expected:** `node_timeout` after the configured timeout, and the CLI exits
non-zero.

### TC-CLI-27: A timeout does not leave the request queued

**Action:** After a timeout, send a second request.

**Expected:** The second request is served normally. A timed-out request that stayed
queued would execute later.

### TC-CLI-28: A timeout does not retain the `node-token`

**Action:** After a timeout, inspect the Server's memory.

**Expected:** No copy of the `node-token` survives.

### TC-CLI-29: A slow Node does not block other Nodes

**Precondition:** Two Nodes, one slow.

**Action:** Send a request to the slow Node, then one to the fast Node.

**Expected:** The fast Node answers without waiting for the slow one. A single
blocking worker would make one slow Node a denial of service for all of them.

## Transport

### TC-CLI-30: The CLI refuses a plaintext Server URL

**Action:** `CONNECTOR_CLI_SERVER_URL=http://host:8443`.

**Expected:** A message and a non-zero exit code, or a warning that names the risk. A
secret sent over plaintext is a leaked secret.

### TC-CLI-31: The CLI verifies the Server certificate

**Precondition:** A Server with a self-signed certificate.

**Action:** Any operation.

**Expected:** The request fails with a certificate error. A CLI that skipped
verification would make TLS decorative.

### TC-CLI-32: The CLI does not follow a redirect

**Action:** A Server that redirects `/v1/` elsewhere.

**Expected:** The CLI refuses. A redirect that carried the `Authorization` header
forward would hand the secret to whatever the redirect names.

### TC-CLI-33: The CLI sends the secrets in headers, not in the URL

**Action:** Inspect the request against a recording listener.

**Expected:** Both secrets are in headers. The URL contains only the `node-id`.

### TC-CLI-34: The CLI sets a request id

**Action:** Inspect the request.

**Expected:** An `X-Request-Id` header is present, so a Server log line and a CLI
error can be correlated.

### TC-CLI-35: The CLI reports the request id on failure

**Action:** Trigger a refusal.

**Expected:** The error names the request id, so an operator can find the Server's
log line for that request.

## Concurrency

### TC-CLI-36: Two concurrent requests to one Node both complete

**Action:** Send two requests concurrently.

**Expected:** Both complete with their own results. A shared buffer would mix the
payloads.

### TC-CLI-37: A response is matched to its request

**Precondition:** A Node that answers out of order.

**Action:** Send two requests concurrently.

**Expected:** Each caller receives its own response. A protocol that matched by
arrival order would swap them.

### TC-CLI-38: A cancelled request does not leave a pending entry

**Action:** Cancel a request in flight, then inspect the Server's pending map.

**Expected:** No entry survives. A pending entry that outlived its caller is a leak
that grows with every cancellation.
