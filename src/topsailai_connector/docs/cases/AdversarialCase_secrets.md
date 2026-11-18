---
maintainer: AI
author: DawsonLin
---

# Adversarial Cases: The Credentials

Attempts to defeat a gate, extract a secret, or use one credential where another is
required. These cases are about the credentials themselves; the path fence has its
own file.

A credential is never transmitted. The caller presents a proof: a signature over a
canonical string, carrying a public `key_id`, a timestamp, a nonce and the
signature. So the extraction cases below ask a narrower question than they used to:
not "can the attacker read the secret off the wire", which the design now prevents,
but "can the attacker obtain a value that lets them act". A captured proof is not
such a value, because it is bound to one operation and one nonce.

## Guessing and brute force

### AC-SEC-1: Guessing `tunnel_token`

**Precondition:** Server started with a 32-byte random `tunnel_token`.

**Action:** Send 10 000 `hello` frames with random values.

**Expected:** Every one is refused, and the Server stays responsive. A gate that
degrades under guessing is a gate that can be removed by load.

### AC-SEC-2: Guessing a node secret

**Precondition:** A Node holds a credential whose secret is 32 random bytes.

**Action:** Send 10 000 requests, each with a well-formed node proof signed with a
random secret and a fresh nonce.

**Expected:** Every one is refused by the Node with `unauthenticated`. The Server
forwards all of them, because it cannot check them, so the Node must survive the
volume. A fresh nonce per attempt is what makes this a guessing case rather than a
replay case: the replay cache must not be the thing that refuses them.

### AC-SEC-3: A short `tunnel_token` is refused at startup

**Precondition:** `CONNECTOR_SERVER_TUNNEL_TOKEN=abc`.

**Action:** Start the Server.

**Expected:** Startup fails. A three-character secret is guessable in milliseconds,
so accepting it silently is the defect. The minimum is enforced rather than
documented.

### AC-SEC-4: A short credential secret is refused

**Precondition:** A credential file whose secret is 8 characters.

**Action:** Start the Node.

**Expected:** Startup fails with
`credential secret is 8 bytes, want at least 32`. The bound is on the secret, not
on the whole `key_id.secret` string, because the key id is public and adds no
entropy.

### AC-SEC-5: A credential secret with a character outside the alphabet is refused

**Precondition:** A credential file whose secret contains `+`.

**Action:** Start the Node.

**Expected:** Startup fails, naming the character. A narrow alphabet is what keeps
the value safe in a shell argument, a URL and a Windows file name, so a value
outside it is refused rather than escaped.

## Extraction

### AC-SEC-6: A secret in an error message

**Action:** Trigger every error path: a wrong secret, a malformed proof, a refused
path, a Node offline, a timeout.

**Expected:** No error message contains a secret. An error message is written by
whoever noticed the problem, which is exactly the moment the value is in hand.

### AC-SEC-7: A secret in a stack trace

**Action:** Trigger a panic in a request handler that holds a credential.

**Expected:** The stack trace contains no secret. A panic that prints its arguments
prints the secret, so the handler must not hold the secret in a named argument that
a trace would render.

### AC-SEC-8: A secret in a debug log

**Precondition:** The Server and the Node run at debug level.

**Action:** Serve a request and inspect every line from both processes.

**Expected:** No secret appears. `debug` is the level where a developer adds a
convenient dump, so it is the level that must be tested. The `key_id` may appear,
because it is public.

### AC-SEC-9: A secret in an audit record

**Action:** Serve a request and inspect the audit record.

**Expected:** The record names the `node-id`, the `key_id` and the operation. It
contains no secret and no proof signature.

### AC-SEC-10: A secret in a crash dump

**Action:** Send `SIGQUIT` to a Server holding a credential, then inspect the
goroutine dump.

**Expected:** No secret appears in the dump. A goroutine dump prints local variables
in some cases, so a secret held in a long-lived local is a leak.

### AC-SEC-11: A secret in a configuration dump

**Action:** Run any command that prints effective configuration, and read both
processes' startup lines.

**Expected:** Each secret is printed as `<set>`, `<redacted>` or a byte count. The
`key_id` list is printed, because it is public.

### AC-SEC-12: A secret in a URL

**Action:** Inspect every URL the CLI constructs, and every URL the Server logs.

**Expected:** No secret appears in a path or a query string. A secret in a URL lands
in access logs, proxy logs and `Referer` headers.

### AC-SEC-13: A secret in a redirect

**Action:** Configure the Server to redirect a request, then inspect the `Location`
header.

**Expected:** The header contains no secret. A redirect that carried the
`Authorization` header forward would hand the proof to whatever the redirect names,
and a proof is bound to one request target, so it would not verify there either.

### AC-SEC-14: A secret in a `Referer` header

**Action:** Serve a request whose response contains a link, then follow it.

**Expected:** The `Referer` contains no secret, because no secret was ever in a URL.

### AC-SEC-15: A secret in a shell history

**Action:** Run the CLI with a credential passed as a flag, then inspect the shell
history.

**Expected:** The flag exists so a script that already holds the credential can pass
it without exporting it, and this is the accepted trade-off recorded in the design
document. The environment variable is the recommended form. Removing the flag would
not remove the exposure, because `/proc/<pid>/environ` is readable by the same
accounts that can read `argv`.

### AC-SEC-16: A secret in the process table

**Action:** Run the CLI with a credential in the environment, then inspect `ps`
output.

**Expected:** The secret does not appear in the command line. It may appear in
`/proc/<pid>/environ`, which is the accepted cost of the environment decision.

## Substitution

### AC-SEC-17: A `tunnel_token` presented as a client proof

**Precondition:** A tunnel token and a client credential, both set, with different
values.

**Action:** Send a CLI request whose `Authorization` value is the tunnel token.

**Expected:** `unauthenticated`. Two values that both work at both gates are one
credential with two names.

### AC-SEC-18: A client credential presented as a `tunnel_token`

**Action:** Send `hello` with `tunnel_token=<client secret>`.

**Expected:** `denied`.

### AC-SEC-19: A node proof presented as a client proof

**Action:** Send a CLI request whose `Authorization` value is a valid node proof,
including its `CONNECTOR-NODE-HMAC-SHA256` scheme.

**Expected:** `unauthenticated`. The scheme names the authentication domain, so a
proof from one boundary cannot be presented at another even when both are
well formed.

### AC-SEC-20: A client proof presented as a node proof

**Action:** Send a request whose `X-Connector-Node-Auth` value is a valid client
proof.

**Expected:** `invalid_argument` from the Server, because the scheme does not match
the header, and the request is never forwarded.

### AC-SEC-21: A node proof from one Node used against another

**Precondition:** Two Nodes connected, each with its own credential file.

**Action:** Address `node_a` with a node proof signed for `node_b`.

**Expected:** `unauthenticated` from `node_a`. The canonical operation binds the
node id, so the proof does not verify at a Node it was not built for.

### AC-SEC-22: A node proof from a Node that has regenerated

**Precondition:** A Node regenerated its node id.

**Action:** Send a request addressed to the old node id.

**Expected:** `node_offline`, because no live connection carries that id. The old
address is not kept as a fallback. The credentials are untouched by regeneration,
so a request addressed to the new id with the same credential succeeds.

### AC-SEC-23: A node proof signed with a removed credential

**Precondition:** A Node whose credential file held `operator-dawson`, then
`connector-node credential remove --key-id operator-dawson` was run.

**Action:** Send a request signed with the removed credential.

**Expected:** `unauthenticated`. The Node adopts the new credential file on its next
poll, so the removal takes effect without a restart.

## Replay

### AC-SEC-24: Replaying a captured request

**Precondition:** A request has been captured in full.

**Action:** Replay it verbatim.

**Expected:** `unauthenticated`. The Server records `(key_id, nonce)` after the
signature verifies, so the second copy is refused as
`authentication proof was already used`. This case used to expect success; it now
expects a refusal, and the change is the point of the credential work.

**Residual limitation:** the replay cache is in memory, so a Server restart inside
the window forgets the nonce and the copy would be accepted. That is accepted for
read-only operations and must be revisited before `file.write` or `command.exec`.

### AC-SEC-25: Replaying a captured request at the Node

**Precondition:** A request has been captured in full, and the Server is modified to
forward it twice.

**Action:** The Server forwards the same request twice.

**Expected:** The first succeeds, the second is refused with `unauthenticated`. The
Node keeps its own replay cache, so a Server that replays does not get a second
operation. This is the case that proves the Node's cache is not merely a copy of the
Server's.

### AC-SEC-26: Replaying a captured `hello`

**Precondition:** A `hello` frame has been captured.

**Action:** Replay it from a second connection.

**Expected:** **Succeeds**, and this is a documented limitation of the tunnel gate,
which is outside the credential work. Two connections may present the same
`tunnel_token`, because the token gates the channel and does not identify a single
connection.

**Note:** whether a second connection for the same `node-id` replaces the first or
is refused is a decision recorded in the design document. This case verifies the
decision is enforced.

### AC-SEC-27: Replaying after a credential is removed

**Precondition:** A client credential was removed from the Server's file.

**Action:** Replay a request captured before the removal.

**Expected:** `unauthenticated`. Removal is the only revocation mechanism, so it
must actually revoke, and it must revoke before the replay cache is consulted.

### AC-SEC-28: Replaying with a fresh nonce and the same signature

**Precondition:** A valid request has been captured.

**Action:** Change only the nonce in the proof, keeping the signature.

**Expected:** `unauthenticated`. The nonce is inside the canonical string, so
changing it invalidates the signature. A proof whose nonce could be edited freely
would defeat the replay cache entirely.

### AC-SEC-29: Replaying with a fresh timestamp and the same signature

**Precondition:** A valid request has been captured.

**Action:** Change only `timestamp_ms`, keeping the signature.

**Expected:** `unauthenticated`. The timestamp is inside the canonical string, so a
captured proof cannot be kept fresh by editing its clock.

### AC-SEC-30: Replaying a proof whose nonce was never admitted

**Precondition:** A proof whose signature does not verify.

**Action:** Send it, then send a valid proof that happens to use the same nonce.

**Expected:** The first is refused, the second succeeds. A nonce is recorded only
after the signature verifies, so a forged proof cannot reserve a nonce a legitimate
request later needs.

## The Server as an attacker

### AC-SEC-31: The Server tries to mint a node proof

**Precondition:** A Node is connected.

**Action:** The Server sends a frame claiming to authorise an operation, with a
proof it constructed itself.

**Expected:** The Node refuses with `unauthenticated`. The Server does not hold the
node secret, so it cannot produce a signature that verifies. This is the property
the whole design rests on, and it is stronger than the previous design, where the
Server at least saw a reusable token.

### AC-SEC-32: The Server tries to widen a scope

**Precondition:** The policy grants `project: [read]`.

**Action:** The Server forwards a request for `project` with `write`.

**Expected:** The Node refuses. The Server cannot widen its own authority by
rewriting a request, and it cannot re-sign one either.

### AC-SEC-33: The Server rewrites the `node-id`

**Precondition:** Two Nodes connected.

**Action:** The Server forwards a request addressed to `node_a` but rewrites the
`node-id` to `node_b`.

**Expected:** `node_b` refuses with `unauthenticated`, because the canonical
operation binds the node id and the proof was signed for `node_a`.

### AC-SEC-34: The Server rewrites the path

**Precondition:** A request for `public.txt` has been signed by the caller.

**Action:** The Server forwards it with `path` set to `secret.txt`.

**Expected:** `unauthenticated`. The path is inside the canonical operation, so a
Server that edits a request invalidates the proof rather than widening it.

### AC-SEC-35: The Server substitutes its own request id

**Precondition:** A valid request.

**Action:** The Server forwards it with a different `X-Request-Id`.

**Expected:** `unauthenticated`. The request id is signed by both proofs, so a
Server that substituted its own would make every node proof fail. The Server
therefore forwards the caller's id unchanged.

### AC-SEC-36: The Server stores a node secret and is later compromised

**Precondition:** A Server that has served many requests.

**Action:** Inspect the Server's disk and memory for any node secret.

**Expected:** None is present, because none was ever received. This is the case that
verifies the hard principle under load rather than on a single request.

### AC-SEC-37: The Server keeps a derived value of a node secret

**Action:** Inspect the Server for any derived value of a node secret: a hash, a
prefix, a fingerprint, a length.

**Expected:** None is present. A stored fingerprint is still a stored credential
index, so it is covered by the same prohibition. The Server does hold the public
`key_id`, which is an address rather than a credential.

### AC-SEC-38: The Server keeps a proof in a retry buffer

**Precondition:** A request times out and is retried.

**Action:** Inspect the Server's memory between the timeout and the retry.

**Expected:** No copy of the proof survives. The retry re-reads the proof from the
caller, because a replayed stored proof would be refused by the Node.

## Configuration attacks

### AC-SEC-39: A missing credential file does not disable authentication

**Precondition:** `CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE` names a path that does
not exist.

**Action:** Start the Server.

**Expected:** The Server does not start. A missing credential file is the most
likely way to accidentally disable authentication, so it is a startup failure
rather than an open gate.

### AC-SEC-40: An empty credential file does not disable authentication

**Precondition:** A credential file of zero bytes.

**Action:** Start the Server.

**Expected:** Startup fails with `credential file is empty`. An empty file is not an
empty credential set: the second is a recorded decision, the first is a mistake.

### AC-SEC-41: A credential file with no credentials is accepted and refuses everything

**Precondition:** A credential file containing `version: 1` and `credentials: []`.

**Action:** Start the Server, then send a request with any proof.

**Expected:** The Server starts, and every request is refused with
`unauthenticated`. This is a recorded decision rather than an oversight: an operator
may deliberately start a Server that admits no caller, and the refusal is the same
one an unknown `key_id` produces.

### AC-SEC-42: A credential file with a duplicate key id is refused

**Precondition:** A credential file naming `operator-dawson` twice.

**Action:** Start the Server.

**Expected:** Startup fails with
`credential key id "operator-dawson" appears twice`. Two secrets for one key id
would make the lookup order decide which one works.

### AC-SEC-43: A credential file over the size cap is refused

**Precondition:** A credential file larger than 1 MiB.

**Action:** Start the Server.

**Expected:** Startup fails with
`CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE "<path>" is <n> bytes, want at most 1048576`.
The Server checks the size before reading, and the parser checks it again before
decoding, because reading an oversized file into memory before deciding it is
oversized is the wrong order.

### AC-SEC-44: A credential file with more than 32 credentials is refused

**Precondition:** A credential file holding 33 credentials.

**Action:** Start the Server.

**Expected:** Startup fails with
`credential set holds 33 credentials, want at most 32`. The bound exists so the
lookup table cannot be grown without limit by whoever can write the file.

### AC-SEC-45: A credential file with a trailing newline in the secret is refused

**Precondition:** A credential file whose secret was written from a file that ends
with a newline.

**Action:** Start the Server.

**Expected:** Startup fails, naming the character. A trailing newline from a file is
the most common way a correct secret fails, so the message must say so without
printing the value.

### AC-SEC-46: A credential file readable by a group is refused

**Precondition:** A Node credential file with mode `0644`.

**Action:** Start the Node.

**Expected:** Startup fails with
`credential file "<path>" has mode 0644, want no group or other access; it holds secrets that never expire`.
A credential that never expires must not be readable by another account.

**Note:** the Server's credential file is not mode-checked, because the Server is
deployed by an operator who controls the file's permissions. The Node's is checked
because it is created by the Node itself on a machine the operator may not
administer.

### AC-SEC-47: The Node's identity file readable by a group is refused

**Precondition:** `<config>/identity` is `0644`.

**Action:** Start the Node.

**Expected:** Startup fails with
`identity file "<path>" has mode 0644, want no group or other access`. The identity
file holds the node id, which is an address rather than a credential, but the check
is kept because the file sits beside the credential file and a reader who finds one
readable will assume the other is too.

## Denial of service

### AC-SEC-48: A huge `tunnel_token` in `hello`

**Action:** Send `hello` with a 10 MiB `tunnel_token`.

**Expected:** The frame is refused before the value is compared. An unbounded field
is a memory problem, and comparing it is wasted work.

### AC-SEC-49: A huge proof header

**Action:** Send a request with a 10 MiB `Authorization` value.

**Expected:** `unauthenticated`. The proof header is capped at 512 bytes, and the cap
is applied before parsing, so an oversized value is refused rather than split.

### AC-SEC-50: A huge request body

**Action:** Send a request with a 10 MiB body.

**Expected:** `too_large`. The body is capped at 1 MiB and the cap is applied while
reading, so the Server does not buffer the whole value before deciding it is
oversized.

### AC-SEC-51: A huge node id in the URL

**Action:** Send a request to `/v1/nodes/<10 MiB>/operations`.

**Expected:** `invalid_argument`. The node id is bounded, so a huge one is refused
before routing.

### AC-SEC-52: Many connections with a wrong `tunnel_token`

**Action:** Open 10 000 connections, each with a wrong `tunnel_token`.

**Expected:** Each is closed promptly and the Server stays responsive. A gate that
holds a connection open while deciding is a gate that can be exhausted.

### AC-SEC-53: A slow `hello`

**Action:** Open a connection and send `hello` one byte at a time.

**Expected:** The connection is closed after a bounded time. A handshake with no
deadline is a slowloris target.

### AC-SEC-54: Filling the replay cache

**Precondition:** A replay cache with a small capacity, and a valid credential.

**Action:** Send valid requests with distinct nonces until the cache is full, then
send one more.

**Expected:** The request that cannot be admitted is refused rather than accepted.
The cache fails closed: it never evicts a nonce that is still inside the window,
because evicting one would make a replay of that nonce succeed.

## Regeneration as an attack

### AC-SEC-55: The Server forces regeneration repeatedly

**Precondition:** A Node is connected.

**Action:** The Server sends many frames asking the Node to regenerate.

**Expected:** The Node ignores all of them. A Server that could force regeneration
could force a denial of service by invalidating the operator's address repeatedly.

### AC-SEC-56: Regeneration while a request is in flight

**Precondition:** A request is being served.

**Action:** Run `connector-node regenerate` during the request.

**Expected:** The in-flight request either completes against the node id it was
addressed to, or fails with `unauthenticated`. It does not silently switch to the
new id mid-request. The credentials are untouched by regeneration, so the failure
mode is an address mismatch rather than a credential mismatch.

### AC-SEC-57: An attacker with write access to the credential file

**Precondition:** An attacker can write `<config>/credentials.yaml`.

**Action:** The attacker writes a credential they know the secret of.

**Expected:** The Node adopts it on its next poll, and this is a documented
limitation: write access to the credential file is equivalent to being an authorised
caller. The mitigation is file permissions, which is why `0600` is a startup check
rather than a suggestion.

### AC-SEC-58: An attacker with write access to the identity file

**Precondition:** An attacker can write `<config>/identity`.

**Action:** The attacker writes a chosen node id.

**Expected:** The Node adopts the chosen address, and this is a documented
limitation: write access to the identity file is equivalent to choosing where the
Node is reachable. It does not grant the ability to operate, because the credentials
are a separate file.

## A secret compiled into the binary

A self-contained build compiles the `tunnel_token` into the executable, so the
executable becomes a credential. These cases cover what that costs and what the
Node does about it. The mechanism is `go build -ldflags "-X ..."`, which stores the
value as plain text in the data section; no case below claims otherwise.

### AC-SEC-59: A scope that contains the binary cannot serve it

**Precondition:** A build with the `tunnel_token` embedded, placed inside a scope
directory. The scope grants `read`, `list` and `stat`.

**Action:** `file.read` the binary through that scope, by its path relative to the
scope root.

**Expected:** `denied`. Not `not_found`, not `invalid_argument`: the file exists and
the path is well formed, so the only correct answer is that the deny list refused
it. A build that serves its own executable hands the caller a Server-wide secret,
which lets that caller impersonate any Node rather than only this one.

### AC-SEC-60: The refusal does not disclose the token

**Precondition:** As AC-SEC-59.

**Action:** `file.read` the binary, then inspect the error message, the error code
and the log line the Node wrote.

**Expected:** The message names the path and the refusal, and contains no fragment
of the `tunnel_token`. A refusal that quotes the value it protected is a leak with
an error code attached.

### AC-SEC-61: `file.stat` and `file.list` do not disclose the binary

**Precondition:** As AC-SEC-59, with a neighbouring ordinary file in the same
directory.

**Action:** `file.stat` the binary, then `file.list` the directory.

**Expected:** `file.stat` is `denied`. The listing omits the binary and still shows
the neighbouring file. The second half is the control: a listing that omits
everything has not tested the deny list, it has tested a broken listing.

### AC-SEC-62: A build that carries no secret still serves its own executable

**Precondition:** A normal build, with no embedded configuration, placed inside a
scope directory.

**Action:** `file.read` the binary through that scope.

**Expected:** `success`. A normal binary discloses nothing by being read, because
its bytes are the source it was compiled from. Refusing it would break the ordinary
case of serving an install directory, so the deny entry is conditional on the build
actually carrying a secret.

### AC-SEC-63: An embedded policy cannot be replaced by a file

**Precondition:** A build that compiled its policy in. `CONNECTOR_NODE_POLICY_FILE`
is set to a valid policy file that grants a scope the embedded policy does not.

**Action:** Start the Node.

**Expected:** Startup fails, and the message names `CONNECTOR_NODE_POLICY_FILE`. The
two sources must not be reconciled silently: an embedded policy is a whole document,
so accepting a file path would replace every scope and every grant at once, and the
operator would believe the embedded policy was still in force.

### AC-SEC-64: The environment overrides an embedded value

**Precondition:** A build with an embedded `tunnel_token` and Server URL.
`CONNECTOR_NODE_TUNNEL_TOKEN` is set to a different valid value.

**Action:** Start the Node, then inspect which token the Server accepted.

**Expected:** The environment value is used, and the embedded value is not. The
override is field by field, so setting only the Server URL leaves the embedded token
in force. A binary that ignored the environment could only be repointed by
repackaging, which is the failure mode a self-contained build is most likely to
create.

### AC-SEC-65: A malformed embedded policy fails startup rather than crashing

**Precondition:** A build whose `PolicyBase64` value is not valid base64, produced by
a packaging mistake.

**Action:** Start the Node.

**Expected:** Startup fails with a message naming the embedded policy, and no panic.
A packaging mistake must surface as a startup failure on the machine that runs the
binary, not as a stack trace on a machine the operator cannot see.

### AC-SEC-66: Two copies of one binary do not share an identity

**Precondition:** The same embedded binary copied to two machines, each with its own
config directory.

**Action:** Start both, then read the `node-id` each one reports.

**Expected:** Two different `node-id` values. The identity is generated locally at
first start and is deliberately not embedded, because two copies sharing one
`node-id` would collide in the Server's `node_id -> connection` registry and evict
each other. The embedded binary still generates, persists and regenerates its
identity exactly as a normal build does.

## What these cases do not cover

- A compromised Server host. The design states what the attacker gains (the ability
  to connect and to call) and what they do not gain (the ability to operate). The
  cases above verify the second half, and the credential work strengthens it: the
  Server no longer receives a reusable node credential at all.
- A compromised Node host. The fence and the credential file are both gone.
- A side channel in the signature comparison. The constant-time requirement is
  verified by reading the implementation, because a timing assertion in a unit test
  is flaky.
- A first-use race on a plaintext link. An attacker who captures a request and sends
  it first wins, and the legitimate copy is refused as a replay. Timestamps and
  nonces cannot order two identical requests, so TLS is what prevents this, and the
  limitation is recorded in the design document rather than tested here.
