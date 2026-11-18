---
maintainer: AI
author: DawsonLin
---

# Test Cases: The Three Credential Gates

Each credential is validated by exactly one party. These cases check that each gate
admits the right value, refuses the wrong one, and refuses for the right reason.

A credential is never transmitted. The caller presents a proof: a signature over a
canonical string, carrying a public `key_id`, a timestamp, a nonce and the
signature. The verifier looks the secret up by `key_id` and recomputes the
signature. A captured proof therefore yields no reusable secret, and a proof
cannot be edited without invalidating it.

## The tunnel gate

The tunnel gate is unchanged by the credential work: `tunnel_token` is still a
shared secret compared by the Server at the handshake. These cases are recorded
here because the three gates are read together, and a reader who finds only two
would conclude the third was removed.

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

The client gate is the CLI-to-Server boundary. The Server holds the client
credential file and verifies the client proof. The proof travels in
`Authorization`, and the value is a proof rather than a secret.

### TC-SEC-9: A valid client proof admits a CLI request

**Precondition:** Server started with
`CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE` naming a file that holds
`operator-dawson.<secret>`. One Node connected.

**Action:** CLI sends a request with
`Authorization: CONNECTOR-CLIENT-HMAC-SHA256 version=1,key_id=operator-dawson,timestamp_ms=<now>,nonce=<fresh>,signature=<valid>`.

**Expected:** The request is forwarded to the Node.

### TC-SEC-10: A wrong client secret is refused before forwarding

**Precondition:** As TC-SEC-9.

**Action:** CLI signs with a secret that is not the one stored for
`operator-dawson`, keeping the same `key_id`.

**Expected:** `unauthenticated`, and **the Node receives nothing**. The case
asserts the absence of a forwarded frame, because a refusal that still forwards
has not protected the Node.

### TC-SEC-11: A missing `Authorization` header is refused

**Precondition:** As TC-SEC-9.

**Action:** CLI sends a request with no `Authorization` header.

**Expected:** `unauthenticated`.

### TC-SEC-12: An unknown `key_id` is refused

**Precondition:** The credential file holds only `operator-dawson`.

**Action:** CLI signs with `key_id=someone-else` and any secret.

**Expected:** `unauthenticated`. The Server does not try every stored secret: it
looks the key up and refuses when it is absent, so the number of stored
credentials does not change the work one request costs.

### TC-SEC-13: A client proof in the URL is not accepted

**Precondition:** As TC-SEC-9.

**Action:** CLI sends
`GET /v1/nodes/node_x/operations?client_credential=operator-dawson.<secret>`.

**Expected:** `invalid_argument` for the method, and the query string is never
read as a credential. A secret in a URL lands in access logs, proxy logs and
`Referer` headers, so the query string is not a credential channel.

### TC-SEC-14: A client proof does not authorise an operation

**Precondition:** As TC-SEC-9. Node policy grants `project: [read]`. The CLI holds
a node credential for a different Node.

**Action:** CLI sends a request with a valid client proof and a node proof signed
with the wrong Node's secret.

**Expected:** The Server forwards, the Node refuses with `unauthenticated`. The
client proof proves the caller may use the Server and proves nothing about the
operation.

### TC-SEC-15: A tampered body is refused

**Precondition:** As TC-SEC-9.

**Action:** Take a valid request and change `path` in the body after signing.

**Expected:** `unauthenticated`. The client proof binds the SHA-256 of the raw
body, so the Server refuses before the Node is involved.

### TC-SEC-16: A tampered node proof header is refused

**Precondition:** As TC-SEC-9.

**Action:** Take a valid request and replace the `X-Connector-Node-Auth` value
with a different well-formed proof after signing the client proof.

**Expected:** `unauthenticated`. The client proof binds the digest of the node
proof header, so the two proofs cannot be mixed from different requests.

### TC-SEC-17: A replayed client proof is refused

**Precondition:** As TC-SEC-9. One request served successfully.

**Action:** Send the identical request again, byte for byte.

**Expected:** `unauthenticated`. The Server records `(key_id, nonce)` after the
signature verifies, so the second copy is refused as
`authentication proof was already used`.

### TC-SEC-18: A client proof with a stale timestamp is refused

**Precondition:** As TC-SEC-9.

**Action:** Sign with `timestamp_ms` older than the replay window.

**Expected:** `unauthenticated`. The window is the freshness check; a proof with
no timestamp would be valid forever.

### TC-SEC-19: A client proof with a future timestamp is refused

**Precondition:** As TC-SEC-9.

**Action:** Sign with `timestamp_ms` further ahead than the window allows.

**Expected:** `unauthenticated`. The window is symmetric, so a clock that runs
fast does not extend a proof's life.

### TC-SEC-20: A malformed client proof is refused

**Precondition:** As TC-SEC-9.

**Action:** Send `Authorization: CONNECTOR-CLIENT-HMAC-SHA256 version=1,key_id=operator-dawson`.

**Expected:** `unauthenticated`. A proof missing its timestamp, nonce or signature
is refused rather than defaulted, because a defaulted field is a field the caller
did not sign.

### TC-SEC-21: The wrong scheme is refused

**Precondition:** As TC-SEC-9.

**Action:** Send a node proof in `Authorization`, with the
`CONNECTOR-NODE-HMAC-SHA256` scheme.

**Expected:** `unauthenticated`. The scheme names the authentication domain, so a
proof from one boundary cannot be presented at another.

## The node gate

The node gate is the CLI-to-Node boundary. The Node holds the node credential file
and verifies the node proof. The Server forwards the proof byte for byte and never
verifies it, because it does not hold the secret.

### TC-SEC-22: A valid node proof admits one operation

**Precondition:** Node holds `operator-dawson.<secret>` in `credentials.yaml`,
policy grants `project: [read]`.

**Action:** CLI sends `file.read` on `project` with a valid node proof.

**Expected:** The file content is returned.

### TC-SEC-23: A wrong node secret is refused by the Node

**Precondition:** As TC-SEC-22.

**Action:** CLI signs the node proof with a secret that is not the stored one,
keeping the same `key_id`.

**Expected:** `unauthenticated` from the Node. The Server forwarded it, because the
Server cannot check it.

### TC-SEC-24: An unknown node `key_id` is refused by the Node

**Precondition:** As TC-SEC-22.

**Action:** CLI signs with `key_id=retired-caller`.

**Expected:** `unauthenticated`. The Node looks the key up in its own credential
file and refuses when it is absent.

### TC-SEC-25: A replayed node proof is refused

**Precondition:** As TC-SEC-22. One request served successfully.

**Action:** Send the identical request again.

**Expected:** `unauthenticated`. The Node records `(key_id, nonce)` after the
signature verifies, so the second copy is refused.

### TC-SEC-26: A node proof for another node id is refused

**Precondition:** Two Nodes, each with its own credential file.

**Action:** Address `node_a` with a node proof signed for `node_b`.

**Expected:** `unauthenticated`. The canonical operation binds the node id, so a
proof built for one Node does not verify at another.

### TC-SEC-27: A node proof for a different path is refused

**Precondition:** As TC-SEC-22.

**Action:** Sign for `public.txt`, then send the request with `path` set to
`secret.txt`.

**Expected:** `unauthenticated`. The canonical operation binds the path, so a
valid proof cannot be reused for a different file.

### TC-SEC-28: A node proof with a stale timestamp is refused

**Precondition:** As TC-SEC-22.

**Action:** Sign with `timestamp_ms` older than the Node's replay window.

**Expected:** `unauthenticated`. The Node's window is its own; the Server's window
does not extend it.

### TC-SEC-29: The Server never receives the node secret

**Precondition:** Node holds `operator-dawson.<secret>`, one request served.

**Action:** Inspect every Server-side observable: logs, any config dump, any
in-memory structure reachable through a debug endpoint, and the forwarded frame.

**Expected:** The secret appears nowhere. The Server receives a signature and a
public `key_id`, and a signature is not a credential. This is the case that
verifies the hard principle, and it is the one that must never be deleted.

### TC-SEC-30: The Server does not log the node proof signature

**Precondition:** As TC-SEC-29.

**Action:** CLI sends a request the Node refuses, then search every Server log
line.

**Expected:** The Server's log records the refusal, the `node-id` and the
`key_id`, and does not record the signature. A refusal path is where a value most
often reaches a log, because the error message is written by whoever noticed the
problem.

## Retention and logging

### TC-SEC-31: The Server does not log the client secret

**Precondition:** Server started with a credential file holding
`operator-dawson.<secret>`.

**Action:** Serve one successful request and one refused request.

**Expected:** The secret appears in no log line, at any level, including `debug`.
The `key_id` may appear, because it is public.

### TC-SEC-32: A proof is not retained after forwarding

**Precondition:** As TC-SEC-29, one request served.

**Action:** Serve a second request for the same Node, then inspect the Server's
memory for a copy of the first proof.

**Expected:** No copy survives the first request. The second request carries its
own proof, read from the caller.

### TC-SEC-33: A retry re-reads the proof from the caller

**Precondition:** As TC-SEC-29. The first attempt times out.

**Action:** The Server retries the request.

**Expected:** The retry carries the proof the caller sent, not a stored copy. A
retry that replayed a stored proof would be refused by the Node as a replay, so
the retry must come from the caller.

## Comparison

### TC-SEC-34: Signature comparison is constant time

**Precondition:** A unit test with the comparison helper.

**Action:** Compare a correct signature, a signature differing in the first byte,
and a signature differing in the last byte, measuring elapsed time over many
iterations.

**Expected:** The three timings are indistinguishable. An early return leaks the
length of the matching prefix, which lets an attacker recover a signature one byte
at a time.

**Note:** this case is inherently statistical. It asserts that no branch returns
early, by reading the implementation, and uses timing only as a secondary signal.
The implementation uses `hmac.Equal`, which is the standard library's
constant-time comparison.

### TC-SEC-35: Every authentication failure produces the same answer

**Precondition:** As TC-SEC-9.

**Action:** Send five requests: no header, empty header, malformed proof, unknown
`key_id`, wrong secret.

**Expected:** All five return `unauthenticated` with the same message. A
distinguishable answer tells an attacker whether a guess was close. The reason is
recorded in the Server's log, where the operator can read it and the caller
cannot.

### TC-SEC-36: A tunnel token is not a client credential

**Precondition:** Server started with `CONNECTOR_SERVER_TUNNEL_TOKEN=alpha` and a
credential file holding `operator-dawson.<secret>`.

**Action:** Send a CLI request whose `Authorization` value is the tunnel token.

**Expected:** `unauthenticated`. Two values that both work at both gates are one
credential with two names.

## Rotation

### TC-SEC-37: Removing a client credential invalidates it

**Precondition:** The credential file holds `operator-dawson` and `ci-system`.

**Action:** Remove `operator-dawson` from the file, restart the Server, then send a
request signed with it.

**Expected:** `unauthenticated`. There is no grace period, because a grace period
is a second valid credential.

### TC-SEC-38: Removing one client credential leaves the others working

**Precondition:** As TC-SEC-37.

**Action:** After removing `operator-dawson`, send a request signed with
`ci-system`.

**Expected:** The request is forwarded. This is the property that makes multiple
credentials worth having: one caller can be retired without retiring the rest.

### TC-SEC-39: Removing a node credential invalidates it

**Precondition:** Node holds `operator-dawson` and `backup-service`.

**Action:** Run `connector-node credential remove --key-id operator-dawson`, then
send a request signed with it.

**Expected:** `unauthenticated`. The Node adopts the new credential file without a
restart, so the removal takes effect on the next request.

### TC-SEC-40: Rotating `tunnel_token` drops live channels

**Precondition:** One Node connected with `tunnel_token=alpha`.

**Action:** Restart the Server with `CONNECTOR_SERVER_TUNNEL_TOKEN=alpha2`.

**Expected:** The Node's channel is gone and it must reconnect with the new value.
A channel that survived a credential change would be authenticated by a credential
that no longer exists.

## Output hygiene

### TC-SEC-41: A secret is not echoed by `--help`

**Precondition:** `CONNECTOR_CLI_CLIENT_CREDENTIAL=operator-dawson.<secret>` is
set.

**Action:** Run `connector-server --help`, `connector-server cli --help` and
`connector-node --help`.

**Expected:** The secret appears in no output.

### TC-SEC-42: A secret is not echoed by a configuration dump

**Precondition:** All credentials set.

**Action:** Run any command that prints effective configuration, and read the
Server's startup log line.

**Expected:** Each secret is printed as `<set>` or `<redacted>`, never as its
value. The startup line names the `key_id` list, which is public, and the
`tunnel_token` as a byte count.

### TC-SEC-43: A secret is not placed in a URL by the CLI

**Precondition:** `CONNECTOR_CLI_CLIENT_CREDENTIAL=operator-dawson.<secret>`.

**Action:** Run a request against a local listener that records the request line
and the headers.

**Expected:** The recorded request line contains no secret. The client proof is in
`Authorization`, the node proof is in `X-Connector-Node-Auth`, and neither value is
a secret.

### TC-SEC-44: A credential file with group or other access is refused

**Precondition:** A Node credential file with mode `0644`.

**Action:** Start the Node.

**Expected:** Startup fails with
`credential file "<path>" has mode 0644, want no group or other access; it holds secrets that never expire`.
A credential that never expires must not be readable by another account.

### TC-SEC-45: A credential file with an unknown key is refused

**Precondition:** A credential file containing an extra top-level key.

**Action:** Start the Node.

**Expected:** Startup fails. The decoder is strict, so a typo in a security
configuration is refused rather than silently ignored.
