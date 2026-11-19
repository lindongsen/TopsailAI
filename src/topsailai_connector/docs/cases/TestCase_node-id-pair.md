---
maintainer: AI
author: DawsonLin
---

# Test Cases: The Node Id and the Node Credential

The node id and the node credential are two values with different jobs, stored in
two files. These cases check the identifier's format, the credential's format, the
parsing rules and the regeneration behaviour.

An earlier version of this file described one string, `node-id.node-token`, whose
halves were an address and a secret. That shape is retired: a single string that is
sometimes logged and sometimes secret will eventually be logged whole, and a
credential that travels on the wire is a credential an observer can reuse. The two
values are now separate, and the credential never travels.

| Value | File | Secret? | Purpose |
|---|---|---|---|
| node id | `<config>/identity` | No | Routing and audit |
| node credential | `<config>/credentials.yaml` | Yes | Authentication |

## The node id

A node id is `node_` followed by 26 characters of unpadded lowercase base32: the
characters `a` to `z` and `0` to `9`, and nothing else. The length is derived from
128 bits of entropy rather than chosen, so a change to the entropy cannot leave the
validator checking a length the generator no longer produces.

### TC-PAIR-1: A well-formed node id is accepted

**Action:** Validate `node_7f3a9c1e2b4d6a8f0c1e3b5d7a`.

**Expected:** Accepted. The body is 26 characters.

### TC-PAIR-2: An empty node id is refused

**Action:** Validate `""`.

**Expected:** `invalid_argument`, with `node id is empty`.

### TC-PAIR-3: A node id without the `node_` prefix is refused

**Action:** Validate `7f3a9c1e2b4d6a8f0c1e3b5d7a`.

**Expected:** `invalid_argument`, with
`node id "7f3a9c1e2b4d6a8f0c1e3b5d7a" does not start with "node_"`. The prefix is
what makes an identifier recognisable as one, so a value without it is a typo rather
than an address.

### TC-PAIR-4: A node id with no body is refused

**Action:** Validate `node_`.

**Expected:** `invalid_argument`, with `node id "node_" has no body after the prefix`.

### TC-PAIR-5: A node id body of the wrong length is refused

**Action:** Validate `node_abc`.

**Expected:** `invalid_argument`, with
`node id "node_abc" has a 3 character body, want 26`. A truncated identifier
addresses nothing, so accepting it would produce a Node that can never be reached
and an operator who sees `node_offline` instead of "your identifier is truncated".

**Why this case exists:** the length check is not a security control, but it turns a
truncation into a startup failure. An earlier version of this document claimed the
validator did not check the length; it does, and the claim was wrong.

### TC-PAIR-6: A character outside the alphabet is refused

**Action:** Validate a node id whose body contains `-`, then one containing `_`,
then one containing an uppercase letter.

**Expected:** `invalid_argument` in all three, with
`node id "<value>" contains "<character>", which is not a lowercase letter or digit`.
This is the rule that rejects every spelling a base64url implementation would have
accepted.

### TC-PAIR-7: A node id with leading whitespace is refused, not trimmed

**Action:** Validate ` node_7f3a9c1e2b4d6a8f0c1e3b5d7a`.

**Expected:** `invalid_argument`, with
`node id " node_7f3a9c1e2b4d6a8f0c1e3b5d7a" has leading or trailing whitespace`.
Trimming would hide a copy-paste error that would otherwise surface as a confusing
routing failure later.

### TC-PAIR-8: A node id with trailing whitespace is refused, not trimmed

**Action:** Validate the same value with a trailing space.

**Expected:** `invalid_argument`, with the same message.

### TC-PAIR-9: A node id with an embedded newline is refused

**Action:** Validate the same value with a trailing `\n`.

**Expected:** `invalid_argument`. A newline is the classic result of copying a value
out of a file, and accepting it would make the value depend on how it was copied.

### TC-PAIR-10: A node id with a path separator is refused

**Action:** Validate `node_7f3a/9c1e2b4d6a8f0c1e3b5d7a`.

**Expected:** `invalid_argument`. A node id is an identifier, never a path.

### TC-PAIR-11: A node id with a dot is refused

**Action:** Validate `node_7f3a.9c1e2b4d6a8f0c1e3b5d7a`.

**Expected:** `invalid_argument`. A dot is not in the alphabet. This is the rule
that makes the retired `node-id.node-token` shape impossible to reintroduce by
accident: a value containing a dot is refused rather than split.

### TC-PAIR-12: The node id is safe to log

**Action:** Serve a request and inspect the audit record and the log lines.

**Expected:** The audit record names the node id and the operation. The node id is
an address, so naming it is the point of the record.

## The node credential

A credential is `key_id.secret`. The key id is public and appears in logs and in the
proof header. The secret is private and never travels.

| Part | Alphabet | Length |
|---|---|---|
| `key_id` | `a-z`, `0-9`, `-`, `_`; first character not `-` or `_` | 1 to 64 |
| `secret` | `a-z`, `A-Z`, `0-9`, `-`, `_` | at least 32 |

### TC-PAIR-13: A well-formed credential is accepted

**Action:** Parse `operator-dawson.XMUThHjCFvpOjShS1-krCLj-k-k5nl93uEUAXqBZbX4`.

**Expected:** Accepted, with key id `operator-dawson` and the secret as written.

### TC-PAIR-14: A credential with no dot is refused

**Action:** Parse `operator-dawson`.

**Expected:** `invalid_argument`, with
`malformed key_id.secret credential: no dot separating the key id from the secret`.

### TC-PAIR-15: A credential with an empty key id is refused

**Action:** Parse `.XMUThHjCFvpOjShS1-krCLj-k-k5nl93uEUAXqBZbX4`.

**Expected:** `invalid_argument`, with
`malformed key_id.secret credential: key id half is empty`.

### TC-PAIR-16: A credential with an empty secret is refused

**Action:** Parse `operator-dawson.`.

**Expected:** `invalid_argument`, with
`malformed key_id.secret credential: secret half is empty`.

### TC-PAIR-17: A credential with a second dot is refused

**Action:** Parse `operator-dawson.abc.def`.

**Expected:** `invalid_argument`, with
`malformed key_id.secret credential: secret half contains a second dot`. The pair is
split on the first dot, and neither half's alphabet contains a dot, so a second dot
means the value was mangled in transit.

**Why this case exists:** splitting on the **last** dot would parse this as a
different key id and a different secret, silently shifting the boundary.

### TC-PAIR-18: A key id with an uppercase letter is refused

**Action:** Parse `Operator-dawson.<secret>`.

**Expected:** `invalid_argument`, naming the character. Uppercase is excluded because
Windows compares paths case-insensitively, so a key id that differs only in case
would be a key id two filesystems disagree about.

### TC-PAIR-19: A key id starting with `-` or `_` is refused

**Action:** Parse `-operator.<secret>`, then `_operator.<secret>`.

**Expected:** `invalid_argument`, with
`key id "-operator" starts with "-", which makes it look like a flag`. A key id that
begins with a dash is a value a shell will read as an option.

### TC-PAIR-20: A key id over 64 characters is refused

**Action:** Parse a credential whose key id is 65 characters.

**Expected:** `invalid_argument`, with
`key id is 65 bytes, want at most 64`. The bound exists so a key id cannot be used
to occupy an unbounded amount of a log line.

### TC-PAIR-21: A secret under 32 characters is refused

**Action:** Parse `operator-dawson.short`.

**Expected:** `invalid_argument`, with
`credential secret is 5 bytes, want at least 32`. The bound is on the secret, not on
the whole string, because the key id is public and adds no entropy.

### TC-PAIR-22: A secret with a character outside the alphabet is refused

**Action:** Parse a credential whose secret contains `+`, then one containing `/`,
then one containing `=`.

**Expected:** `invalid_argument` in all three, naming the character. The alphabet is
deliberately narrow so the value survives a shell argument, a URL and a Windows file
name without escaping.

### TC-PAIR-23: A credential with leading or trailing whitespace is refused

**Action:** Parse ` operator-dawson.<secret>` and `operator-dawson.<secret> `.

**Expected:** `invalid_argument`, with
`malformed key_id.secret credential: value has leading or trailing whitespace`.

### TC-PAIR-24: The secret is never logged

**Action:** Serve a request and inspect every log line from both processes.

**Expected:** The key id may appear. The secret appears nowhere, at any level. The
`Redacted` output renders it as `<redacted>`.

## The credential file

### TC-PAIR-25: A credential file is created with restrictive permissions

**Precondition:** No credential file exists.

**Action:** Start the Node, then inspect the file mode.

**Expected:** `0600` on POSIX. On Windows the file inherits the parent directory's
default descriptor, which grants `BUILTIN\Users` read access, so the expectation
there is "readable by every local account" rather than "owner-only". The file holds
secrets that never expire, so on POSIX a group-readable file is a leaked credential;
on Windows the protection is the operator's responsibility, as stated in
`docs/Environment_Variables.md`.

### TC-PAIR-26: A credential file with group or other access is refused

**Precondition:** A credential file with mode `0644`.

**Action:** Start the Node.

**Expected:** Startup fails with
`credential file "<path>" has mode 0644, want no group or other access; it holds secrets that never expire`.

### TC-PAIR-27: The config directory is created with restrictive permissions

**Action:** Start the Node with a fresh config directory, then inspect the mode.

**Expected:** `0700` on POSIX. On Windows the directory inherits its parent's default
descriptor, which grants `BUILTIN\Users` read access; the Node sets no ACL there, so
the operator must choose a parent directory with a restrictive ACL.

### TC-PAIR-28: The identity file and the credential file are separate

**Precondition:** A Node that has started once.

**Action:** Inspect the config directory.

**Expected:** Two files: `identity`, holding the node id, and `credentials.yaml`,
holding the credentials. Regenerating the identity does not touch the credentials,
and adding a credential does not touch the identity.

**Why this case exists:** the two values were one file before the credential work.
Keeping them separate is what lets an operator change where a Node is reachable
without reissuing every caller's credential.

## Generation and storage

### TC-PAIR-29: The Node generates a node id on first start

**Precondition:** No identity file exists.

**Action:** Run `connector-node id`.

**Expected:** A node id is written to `<config>/identity` and printed. It starts with
`node_` and its body is 26 characters.

### TC-PAIR-30: The Node reuses its node id on later starts

**Precondition:** An identity file exists.

**Action:** Run `connector-node id` twice.

**Expected:** The same node id both times. A Node that regenerated on every start
would need its address copied to the CLI on every start.

### TC-PAIR-31: The Node generates a credential on first start

**Precondition:** No credential file exists.

**Action:** Start the Node.

**Expected:** A credential is written to `<config>/credentials.yaml`. The startup
summary announces `a new credential was generated by this start` and then prints the
key id and the secret under `key id` and `secret`. The key id is generated when the
operator does not name one.

### TC-PAIR-32: `connector-node id` prints only the node id

**Precondition:** A Node that has started once.

**Action:** Run `connector-node id`.

**Expected:** One line, the node id, and nothing else. It prints no secret, so its
output can be pasted into a ticket.

**Why this case exists:** the command used to print the whole pair, which meant its
output was a credential. Splitting the values is what makes the address safe to
share.

## Regeneration

### TC-PAIR-33: Regeneration produces a new node id

**Precondition:** A node id exists.

**Action:** Run `connector-node regenerate`.

**Expected:** A new node id is written and printed. The credentials are unchanged.

### TC-PAIR-34: Regeneration does not invalidate a credential

**Precondition:** A node id and a credential exist, and the CLI holds the credential.

**Action:** Run `connector-node regenerate`, then send a request addressed to the new
node id with the same credential.

**Expected:** The request succeeds. The credential authenticates a caller, not an
address, so changing the address does not change who may call.

**Why this case exists:** the retired design invalidated the secret on regeneration,
because the secret was half of the address. Now the two are independent, and a case
that still expected the credential to stop working would be wrong.

### TC-PAIR-35: Regeneration drops the live channel

**Precondition:** A Node is connected.

**Action:** Run `connector-node regenerate`.

**Expected:** The channel closes and the Node reconnects under the new node id. A
channel that survived would be registered under an address that no longer exists.

### TC-PAIR-36: `--keep-id` is refused

**Precondition:** A node id exists.

**Action:** Run `connector-node regenerate --keep-id`.

**Expected:** The command fails with a flag refusal naming `keep-id`. The flag
existed when the identity and the credential were one value, where keeping the
address while changing the secret was meaningful. Now the credential is changed by
`credential add` and `credential remove`, so the flag has no meaning and is refused
rather than silently ignored.

### TC-PAIR-37: The Server cannot trigger regeneration

**Precondition:** A Node is connected.

**Action:** Send a frame from the Server that asks the Node to regenerate.

**Expected:** The Node ignores it. A Server that could force regeneration could force
a denial of service by invalidating the operator's address repeatedly.

### TC-PAIR-38: Regeneration does not change `tunnel_token` or the client credentials

**Precondition:** A node id exists and both Server secrets are set.

**Action:** Run `connector-node regenerate`.

**Expected:** The Node reconnects with the same `tunnel_token`, and the CLI still
works with the same client credential. Regeneration is a Node-local operation, so it
must not require a Server change.

## Binding

### TC-PAIR-39: A credential from one Node does not work on another

**Precondition:** Two Nodes, `node_a` and `node_b`, both connected, each with its own
credential file.

**Action:** Send a request addressed to `node_a` carrying a node proof signed with
`node_b`'s secret.

**Expected:** `unauthenticated` from `node_a`. A credential is per-Node, so it is not
a portable credential.

### TC-PAIR-40: The node id in the URL is the address the Server routes by

**Precondition:** Two Nodes connected.

**Action:** Send a request to `/v1/nodes/node_a/operations` with a node proof signed
for `node_a`.

**Expected:** The request reaches `node_a`. The Server routes by the URL and does not
compare it with anything in the proof, because the proof carries no address: the
node id is inside the canonical operation, so a proof signed for `node_b` simply
fails to verify at `node_a`.

**Why this case exists:** the retired design compared the URL's `node-id` with the
first half of the pair and refused a mismatch. There is no pair to compare now, so
the agreement is enforced by the signature instead of by a comparison.

### TC-PAIR-41: The Node reports its node id when it connects

**Precondition:** A Node with an identity file.

**Action:** Connect and inspect the `hello` frame.

**Expected:** The node id is present, so the Server can route to it. No credential is
present in `hello`, because the channel is gated by `tunnel_token` and a node
credential is only ever presented as a proof on an operation.

### TC-PAIR-42: The Server never assigns a node id

**Precondition:** A Node with no identity file.

**Action:** Connect to the Server.

**Expected:** The Node generates its own node id before connecting. The Server sends
no identifier and has no endpoint that issues one.
