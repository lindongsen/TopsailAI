---
maintainer: AI
author: DawsonLin
---

# Test Cases: The `node-id.node-token` Pair

The pair is one string with two halves that have different jobs. These cases check
the format, the parsing rules and the regeneration behaviour.

## Format and parsing

A pair is `node-id` `.` `node-token`. The `node-id` starts with `node_`. The
separator is the **first** dot, not the last.

### TC-PAIR-1: A well-formed pair is accepted

**Action:** Parse `node_7f3a9c1e.9f2b4d7a`.

**Expected:** `node-id` is `node_7f3a9c1e`, `node-token` is `9f2b4d7a`.

### TC-PAIR-2: A pair with no dot is refused

**Action:** Parse `node_7f3a9c1e`.

**Expected:** `invalid_argument`. There is no `node-token`, so there is nothing to
authenticate with.

### TC-PAIR-3: A pair with an empty `node-id` is refused

**Action:** Parse `.9f2b4d7a`.

**Expected:** `invalid_argument`. An empty `node-id` is not an address.

### TC-PAIR-4: A pair with an empty `node-token` is refused

**Action:** Parse `node_7f3a9c1e.`.

**Expected:** `invalid_argument`. An empty secret is not a secret.

### TC-PAIR-5: A pair with a second dot in the token half is refused

**Action:** Parse `node_7f3a9c1e.9f2b.4d7a`.

**Expected:** `invalid_argument`. Splitting on the first dot leaves `9f2b.4d7a` as
the token, which contains a dot and is therefore not a token this format produces.

**Why this case exists:** splitting on the **last** dot would parse this as
`node_7f3a9c1e.9f2b` and `4d7a`, silently shifting the boundary. A token that
contained a dot would then be truncated without an error.

### TC-PAIR-6: A `node-id` without the `node_` prefix is refused

**Action:** Parse `7f3a9c1e.9f2b4d7a`.

**Expected:** `invalid_argument`. The prefix is what makes an identifier
recognisable as one, so a value without it is a typo rather than an address.

### TC-PAIR-7: A pair with leading whitespace is refused, not trimmed

**Action:** Parse ` node_7f3a9c1e.9f2b4d7a`.

**Expected:** `invalid_argument`. Trimming would hide a copy-paste error that would
otherwise surface as a confusing authentication failure later.

### TC-PAIR-8: A pair with trailing whitespace is refused, not trimmed

**Action:** Parse `node_7f3a9c1e.9f2b4d7a `.

**Expected:** `invalid_argument`.

### TC-PAIR-9: A pair with an embedded newline is refused

**Action:** Parse `node_7f3a9c1e.9f2b4d7a\n`.

**Expected:** `invalid_argument`. A newline is the classic result of copying a value
out of a file, and accepting it would make the value depend on how it was copied.

### TC-PAIR-10: A pair with a NUL byte is refused

**Action:** Parse `node_7f3a9c1e.9f2b\x004d7a`.

**Expected:** `invalid_argument`. A NUL truncates the string at the syscall
boundary, so the checked value and the used value would differ.

### TC-PAIR-11: A pair with a control character is refused

**Action:** Parse `node_7f3a9c1e.9f2b\t4d7a`.

**Expected:** `invalid_argument`.

### TC-PAIR-12: A pair with a path separator is refused

**Action:** Parse `node_7f3a/9c1e.9f2b4d7a`.

**Expected:** `invalid_argument`. A `node-id` is an identifier, never a path.

### TC-PAIR-13: A pair longer than the limit is refused

**Action:** Parse a pair of 100 KiB.

**Expected:** `invalid_argument`. An unbounded identifier is a memory and log
problem.

### TC-PAIR-14: Parsing is not affected by the number of dots in the `node-id`

**Action:** Parse `node_a.b.9f2b4d7a`.

**Expected:** `invalid_argument`, because the `node-id` half contains a dot. The
first dot is the separator, so `node-id` is `node_a` and the token half is
`b.9f2b4d7a`, which contains a dot and is refused.

**Why this case exists:** it pins the boundary decision. A reader who assumes the
last dot is the separator would expect this to parse.

## Logging

### TC-PAIR-15: The two halves are split before any logging

**Action:** Serve a request with `node_7f3a9c1e.9f2b4d7a` and inspect every log
line.

**Expected:** `node_7f3a9c1e` may appear. `9f2b4d7a` appears nowhere. A single
string that is sometimes logged and sometimes secret will eventually be logged
whole, so the split happens on receipt.

### TC-PAIR-16: The `node-id` half is safe to log

**Action:** Serve a request and inspect the audit record.

**Expected:** The audit record names `node_7f3a9c1e` and the operation, and
contains no secret. The `node-id` is an address, so naming it is the point of the
record.

## Generation and storage

### TC-PAIR-17: The Node generates a pair on first start

**Precondition:** No identity file exists.

**Action:** Start the Node.

**Expected:** A pair is written to `<config>/identity` and printed once. The
`node-id` starts with `node_` and the token half is long enough to be
unguessable.

### TC-PAIR-18: The Node reuses its pair on later starts

**Precondition:** An identity file exists.

**Action:** Start the Node twice.

**Expected:** The same pair is used both times. A Node that regenerated on every
start would need its pair copied to the CLI on every start.

### TC-PAIR-19: The identity file is created with restrictive permissions

**Precondition:** No identity file exists.

**Action:** Start the Node, then inspect the file mode.

**Expected:** `0600` on POSIX. On Windows the file inherits the parent directory's
default descriptor, which grants `BUILTIN\Users` read access, so the expectation
there is "readable by every local account" rather than "owner-only". The file holds
the `node-token`, so on POSIX a group-readable file is a leaked secret; on Windows
the protection is the operator's responsibility, as stated in
`docs/Environment_Variables.md`.

### TC-PAIR-20: The config directory is created with restrictive permissions

**Action:** Start the Node with a fresh config directory, then inspect the mode.

**Expected:** `0700` on POSIX. On Windows the directory inherits its parent's
default descriptor, which grants `BUILTIN\Users` read access; the Node sets no ACL
there, so the operator must choose a parent directory with a restrictive ACL.

## Regeneration

### TC-PAIR-21: Regeneration produces a new pair

**Precondition:** A pair exists.

**Action:** Run `connector-node regenerate`.

**Expected:** Both halves change, the new pair is written, and the new pair is
printed.

### TC-PAIR-22: Regeneration invalidates the old `node-token` immediately

**Precondition:** A pair exists and the CLI holds it.

**Action:** Run `connector-node regenerate`, then send a request with the old
`node-token`.

**Expected:** `denied` on the very next request. There is no grace period,
because a grace period would keep the leaked value working.

### TC-PAIR-23: Regeneration drops the live channel

**Precondition:** A Node is connected.

**Action:** Run `connector-node regenerate`.

**Expected:** The channel closes and the Node reconnects with the new pair. A
channel that survived would be authenticated by a credential that no longer exists.

### TC-PAIR-24: `--keep-id` keeps the `node-id` and changes the token

**Precondition:** A pair exists.

**Action:** Run `connector-node regenerate --keep-id`.

**Expected:** The `node-id` half is unchanged and the token half is new. This is the
case where an operator wants to rotate the secret without re-addressing the Node.

### TC-PAIR-25: The Server cannot trigger regeneration

**Precondition:** A Node is connected.

**Action:** Send a frame from the Server that asks the Node to regenerate.

**Expected:** The Node ignores it. A Server that could force regeneration could
force a denial of service by invalidating the operator's pair repeatedly.

### TC-PAIR-26: Regeneration does not change `tunnel_token` or `client_token`

**Precondition:** A pair exists and both Server secrets are set.

**Action:** Run `connector-node regenerate`.

**Expected:** The Node reconnects with the same `tunnel_token`, and the CLI still
works with the same `client_token`. Regeneration is a Node-local operation, so it
must not require a Server change.

## Binding

### TC-PAIR-27: A pair from one Node does not work on another

**Precondition:** Two Nodes, `node_a` and `node_b`, both connected.

**Action:** Send a request addressed to `node_a` carrying `node_b`'s `node-token`.

**Expected:** `denied` from `node_a`. The `node-token` is per-Node, so a pair
is not a portable credential.

### TC-PAIR-28: The `node-id` in the URL and in the pair must agree

**Precondition:** Two Nodes connected.

**Action:** Send a request to `/v1/nodes/node_a/operations` carrying
`node_b.token_b`.

**Expected:** `invalid_argument` from the Server, before forwarding. The Server can
see both halves of the address, so a disagreement is a malformed request rather
than an authentication failure.

### TC-PAIR-29: The Node reports its `node-id` when it connects

**Precondition:** A Node with a pair.

**Action:** Connect and inspect the `hello` frame.

**Expected:** The `node-id` is present, so the Server can route to it. The
`node-token` is not present in `hello`, because the channel is gated by
`tunnel_token` and the `node-token` is only ever presented on an operation.

### TC-PAIR-30: The Server never assigns a `node-id`

**Precondition:** A Node with no identity file.

**Action:** Connect to the Server.

**Expected:** The Node generates its own pair before connecting. The Server sends
no identifier and has no endpoint that issues one.
