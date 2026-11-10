---
maintainer: AI
author: DawsonLin
---

# Adversarial Cases: The Secrets

Attempts to defeat a gate, extract a secret, or use one secret where another is
required. These cases are about the secrets themselves; the path fence has its own
file.

## Guessing and brute force

### AC-SEC-1: Guessing `tunnel_token`

**Precondition:** Server started with a 32-byte random `tunnel_token`.

**Action:** Send 10 000 `hello` frames with random values.

**Expected:** Every one is refused, and the Server stays responsive. A gate that
degrades under guessing is a gate that can be removed by load.

### AC-SEC-2: Guessing `node-token`

**Precondition:** A Node holds a 32-byte random `node-token`.

**Action:** Send 10 000 requests with random `node-token` values.

**Expected:** Every one is refused by the Node. The Server forwards all of them,
because it cannot check them, so the Node must survive the volume.

### AC-SEC-3: A short secret is refused at startup

**Precondition:** `CONNECTOR_SERVER_TUNNEL_TOKEN=abc`.

**Action:** Start the Server.

**Expected:** Startup fails, or a warning is logged that names the risk. A three
character secret is guessable in milliseconds, so accepting it silently is the
defect.

**Note:** the minimum length is a decision recorded in the design document. This
case verifies that the decision is enforced rather than documented.

### AC-SEC-4: A secret equal to a common word is refused or warned

**Precondition:** `CONNECTOR_SERVER_CLIENT_TOKEN=password`.

**Action:** Start the Server.

**Expected:** Startup fails, or a warning is logged. A dictionary word is not a
secret.

## Extraction

### AC-SEC-5: A secret in an error message

**Action:** Trigger every error path: a wrong secret, a malformed pair, a refused
path, a Node offline, a timeout.

**Expected:** No error message contains a secret. An error message is written by
whoever noticed the problem, which is exactly the moment the value is in hand.

### AC-SEC-6: A secret in a stack trace

**Action:** Trigger a panic in a request handler that holds a secret.

**Expected:** The stack trace contains no secret. A panic that prints its arguments
prints the secret, so the handler must not hold the secret in a named argument that
a trace would render.

### AC-SEC-7: A secret in a debug log

**Precondition:** `CONNECTOR_LOG_LEVEL=debug`.

**Action:** Serve a request and inspect every line.

**Expected:** No secret appears. `debug` is the level where a developer adds a
convenient dump, so it is the level that must be tested.

### AC-SEC-8: A secret in an audit record

**Action:** Serve a request and inspect the audit record.

**Expected:** The record names the `node-id` and the operation. It contains no
`node-token`, no `client_token` and no `tunnel_token`.

### AC-SEC-9: A secret in a crash dump

**Action:** Send `SIGQUIT` to a Server holding a secret, then inspect the goroutine
dump.

**Expected:** No secret appears in the dump. A goroutine dump prints local variables
in some cases, so a secret held in a long-lived local is a leak.

### AC-SEC-10: A secret in a configuration dump

**Action:** Run any command that prints effective configuration.

**Expected:** Each secret is printed as `<set>` or `<redacted>`.

### AC-SEC-11: A secret in a URL

**Action:** Inspect every URL the CLI constructs, and every URL the Server logs.

**Expected:** No secret appears in a path or a query string. A secret in a URL lands
in access logs, proxy logs and `Referer` headers.

### AC-SEC-12: A secret in a redirect

**Action:** Configure the Server to redirect a request, then inspect the `Location`
header.

**Expected:** The header contains no secret. A redirect that carried the
`Authorization` header forward would hand the secret to whatever the redirect names.

### AC-SEC-13: A secret in a `Referer` header

**Action:** Serve a request whose response contains a link, then follow it.

**Expected:** The `Referer` contains no secret, because no secret was ever in a URL.

### AC-SEC-14: A secret in a shell history

**Action:** Run the CLI with a secret passed as a flag, then inspect the shell
history.

**Expected:** The CLI does not accept a secret as a positional argument or a flag
value, or it warns that the value will be recorded. A secret on a command line is in
the process table and in the history file.

### AC-SEC-15: A secret in the process table

**Action:** Run the CLI with a secret in the environment, then inspect `ps` output.

**Expected:** The secret does not appear in the command line. It may appear in
`/proc/<pid>/environ`, which is the accepted cost of the environment decision.

## Substitution

### AC-SEC-16: `tunnel_token` used as `client_token`

**Precondition:** Both secrets set to different values.

**Action:** Send a CLI request with `Authorization: Bearer <tunnel_token>`.

**Expected:** `denied`. Two secrets that both work at both gates are one
secret with two names.

### AC-SEC-17: `client_token` used as `tunnel_token`

**Action:** Send `hello` with `tunnel_token=<client_token>`.

**Expected:** `denied`.

### AC-SEC-18: `node-token` used as `client_token`

**Action:** Send a CLI request with `Authorization: Bearer <node-token>`.

**Expected:** `denied`. The `node-token` is not a Server credential.

### AC-SEC-19: `client_token` used as `node-token`

**Action:** Send a request with a valid `client_token` and `node-token=<client_token>`.

**Expected:** `denied` from the Node.

### AC-SEC-20: A pair from one Node used against another

**Precondition:** Two Nodes connected.

**Action:** Address `node_a` with `node_b`'s `node-token`.

**Expected:** `denied` from `node_a`.

### AC-SEC-21: A pair from a Node that has regenerated

**Precondition:** A Node regenerated its pair.

**Action:** Send a request with the old pair.

**Expected:** `denied`. The old value is not kept as a fallback.

## Replay

### AC-SEC-22: Replaying a captured request

**Precondition:** A request has been captured in full.

**Action:** Replay it verbatim.

**Expected:** **Succeeds**, and this is a documented limitation. No secret expires
and there is no nonce, so a captured request works until the secret is rotated. The
case records the behaviour so it is a decision rather than a surprise.

**Mitigation:** TLS prevents capture in transit, and rotation bounds the window
after a leak is suspected.

### AC-SEC-23: Replaying a captured `hello`

**Precondition:** A `hello` frame has been captured.

**Action:** Replay it from a second connection.

**Expected:** **Succeeds**, for the same reason. Two connections may present the
same `tunnel_token`, because the token gates the channel and does not identify a
single connection.

**Note:** whether a second connection for the same `node-id` replaces the first or
is refused is a decision recorded in the design document. This case verifies the
decision is enforced.

### AC-SEC-24: Replaying after rotation

**Precondition:** `client_token` was rotated.

**Action:** Replay a request captured before the rotation.

**Expected:** `denied`. Rotation is the only revocation mechanism, so it must
actually revoke.

## The Server as an attacker

### AC-SEC-25: The Server tries to mint a `node-token`

**Precondition:** A Node is connected.

**Action:** The Server sends a frame claiming to authorise an operation.

**Expected:** The Node ignores it. The Node is the only authority for permissions, so
a frame from the Server cannot grant one.

### AC-SEC-26: The Server tries to widen a scope

**Precondition:** The policy grants `project: [read]`.

**Action:** The Server forwards a request for `project` with `write`.

**Expected:** The Node refuses. The Server cannot widen its own authority by
rewriting a request.

### AC-SEC-27: The Server rewrites the `node-id`

**Precondition:** Two Nodes connected.

**Action:** The Server forwards a request addressed to `node_a` but rewrites the
`node-id` to `node_b`.

**Expected:** `node_b` refuses, because the `node-token` does not match. The
`node-token` is what binds a request to a Node, not the `node-id` the Server chose.

### AC-SEC-28: The Server stores a `node-token` and is later compromised

**Precondition:** A Server that has served many requests.

**Action:** Inspect the Server's disk and memory for any `node-token` value.

**Expected:** None is present. This is the case that verifies the hard principle
under load rather than on a single request.

### AC-SEC-29: The Server keeps a hash of a `node-token`

**Action:** Inspect the Server for any derived value of a `node-token`: a hash, a
prefix, a fingerprint, a length.

**Expected:** None is present. A stored fingerprint is still a stored credential
index, so it is covered by the same prohibition.

### AC-SEC-30: The Server keeps a `node-token` in a retry buffer

**Precondition:** A request times out and is retried.

**Action:** Inspect the Server's memory between the timeout and the retry.

**Expected:** No copy of the `node-token` survives. The retry re-reads the value
from the caller.

## Configuration attacks

### AC-SEC-31: An unset secret does not disable authentication

**Precondition:** `CONNECTOR_SERVER_CLIENT_TOKEN` is unset.

**Action:** Start the Server, then send a request with no `Authorization` header.

**Expected:** The Server does not start. An unset secret is the most likely way to
accidentally disable authentication, so it is a startup failure rather than an
open gate.

### AC-SEC-32: An empty secret does not disable authentication

**Precondition:** `CONNECTOR_SERVER_CLIENT_TOKEN=` (set but empty).

**Action:** Start the Server.

**Expected:** Startup fails.

### AC-SEC-33: A whitespace-only secret is refused

**Precondition:** `CONNECTOR_SERVER_CLIENT_TOKEN="   "`.

**Action:** Start the Server.

**Expected:** Startup fails. A whitespace-only value is an empty value that looks
set.

### AC-SEC-34: A secret with a trailing newline is refused

**Precondition:** `CONNECTOR_SERVER_CLIENT_TOKEN` is set from a file that ends with a
newline.

**Action:** Start the Server, then send a request with the value without the
newline.

**Expected:** `denied`, and the startup log names the likely cause. A trailing
newline from a file is the most common way a correct secret fails, so the error
message must say so without printing the value.

### AC-SEC-35: A secret file readable by a group is refused

**Precondition:** A deployment that passes secrets through a file.

**Action:** Start the Server with a file that is `0644`.

**Expected:** Startup fails. A group-readable secret file is a leaked secret.

### AC-SEC-36: The Node's identity file readable by a group is refused

**Precondition:** `<config>/identity` is `0644`.

**Action:** Start the Node.

**Expected:** Startup fails, or the file is rewritten with `0600` and the change is
logged. A Node that silently accepts a world-readable identity file is a Node whose
`node-token` is already leaked.

## Denial of service

### AC-SEC-37: A huge `tunnel_token` in `hello`

**Action:** Send `hello` with a 10 MiB `tunnel_token`.

**Expected:** The frame is refused before the value is compared. An unbounded field
is a memory problem, and comparing it is wasted work.

### AC-SEC-38: A huge `node-token` in a request

**Action:** Send a request with a 10 MiB `node-token`.

**Expected:** `invalid_argument` from the Server, before forwarding. The Server
cannot check the value, but it can check the size.

### AC-SEC-39: A huge pair in the URL

**Action:** Send a request to `/v1/nodes/<10 MiB>/operations`.

**Expected:** `invalid_argument`. The `node-id` is bounded, so a huge one is refused
before routing.

### AC-SEC-40: Many connections with wrong `tunnel_token`

**Action:** Open 10 000 connections, each with a wrong `tunnel_token`.

**Expected:** Each is closed promptly and the Server stays responsive. A gate that
holds a connection open while deciding is a gate that can be exhausted.

### AC-SEC-41: A slow `hello`

**Action:** Open a connection and send `hello` one byte at a time.

**Expected:** The connection is closed after a bounded time. A handshake with no
deadline is a slowloris target.

## Regeneration as an attack

### AC-SEC-42: The Server forces regeneration repeatedly

**Precondition:** A Node is connected.

**Action:** The Server sends many frames asking the Node to regenerate.

**Expected:** The Node ignores all of them. A Server that could force regeneration
could force a denial of service by invalidating the operator's pair repeatedly.

### AC-SEC-43: Regeneration while a request is in flight

**Precondition:** A request is being served.

**Action:** Run `connector-node regenerate` during the request.

**Expected:** The in-flight request either completes with the old value it was
authorised by, or fails. It does not silently switch to the new value mid-request.

### AC-SEC-44: An attacker with write access to the identity file

**Precondition:** An attacker can write `<config>/identity`.

**Action:** The attacker writes a chosen pair.

**Expected:** The Node uses the chosen pair, and this is a documented limitation:
write access to the identity file is equivalent to being the Node. The mitigation is
file permissions, which is why `0600` is a startup check rather than a suggestion.

## What these cases do not cover

- A compromised Server host. The design states what the attacker gains (the ability
  to connect and to call) and what they do not gain (the ability to operate). The
  cases above verify the second half.
- A compromised Node host. The fence and the `node-token` are both gone.
- A side channel in the comparison. The constant-time requirement is verified by
  reading the implementation, because a timing assertion in a unit test is flaky.
