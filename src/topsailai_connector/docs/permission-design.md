---
maintainer: AI
author: DawsonLin
status: decided
created: 2026-11-09
updated: 2026-11-10
---

# Permission and Token Design

## Hard constraints

These are not preferences. A change that violates one of them is a design
regression, not a trade-off.

### The Server never stores a Node token

The Server forwards the `node-token` on the request it arrives with and keeps no
copy. This is the single rule the whole three-secret design rests on: if the
Server stores a Node's token, then compromising the Server yields every stored
Node credential at once, and the separation between the channel authority and the
operation authority collapses into one authority.

"Never stores" is enforced by four concrete prohibitions, because a vague promise
is how this rule gets broken by accident:

1. **No persistence.** No database row, no file, no cache directory, no
   in-memory map keyed by token. A `node-token` exists only as a field of the
   request being forwarded.
2. **No logging.** The token is never written to a log, a trace, an audit record
   or an error message. An audit record names the `node-id`, never the token.
3. **No retention after forwarding.** The request buffer holding the token is
   released when the response is written. A retry re-reads the token from the
   caller, it does not replay a stored copy.
4. **No derived storage.** The Server does not store a hash, a prefix, a
   fingerprint or any other value that would let it recognize a token later. A
   stored fingerprint is still a stored credential index.

The Server does hold its own two secrets, `tunnel_token` and `client_token`,
because it is the party that validates them. That is not a violation: those are
the Server's own credentials, and holding them is what lets the Server be the
authority for the channel. The prohibition is specifically about holding a
credential that belongs to a Node.

### The same rule covers the Server's own secrets

The Server's two secrets are read from the environment once at startup and are
never copied anywhere else:

- They are not written to a config file, a cache, a log or an audit record.
- They are not echoed by a configuration dump, a `--print-config` command or a
  startup banner. A startup log line may say that a secret is set, never what it
  is.
- They are not retained in a request-scoped struct after the comparison. The
  comparison reads the configured value and the presented value, returns a
  boolean, and the presented value is released with the request.

The reason is the same as for the Node's token: a stored secret is a stored
credential, and a Server that stores one collapses the separation between the
channel authority and the operation authority into a single authority.

### The Node is the only authority for permissions

The Server may request an operation. Only the Node decides whether it happens. The
Server cannot widen its own authority, and a compromised Server cannot forge a
`node-token` because it never learns the Node's value.

This is the property the shared-secret model preserves most clearly. The Server
holds `tunnel_token` and `client_token`; it does not hold any Node's
`node-token`. So a compromised Server can refuse service and can impersonate a
caller toward itself, but it cannot make a Node perform an operation, because the
Node checks a secret the Server has never seen.

The authority has two dimensions, and the Node owns both of them. Neither is
delegated, and neither is negotiated:

| Dimension | Question it answers | Decided by | Where it is written |
|---|---|---|---|
| `scope` | Which area may be touched | The Node | The Node's policy file |
| `permission` | Which action may be taken there | The Node | The Node's policy file |

A request carries a scope name and an operation. The Node looks the scope up in its
own policy, maps it to a directory it resolved at startup, and checks that the
operation's permission is granted on that scope. Both checks happen on the Node,
after the `node-token` is validated, and both are refusals by default.

The Server has no scope list, no permission list and no way to learn either. It
cannot add a scope, cannot widen a grant, cannot translate one permission into
another, and cannot mark a request as pre-approved. A request the Server has
already authenticated is still an unauthenticated request as far as the Node is
concerned, because the Server's authentication proves only that the caller may use
the Server.

Three consequences follow, and each is a rule rather than an observation:

1. **The Server cannot answer "may this caller do this?"** It does not know the
   policy, so any answer it gave would be a guess. It forwards and reports what the
   Node said.
2. **A policy change takes effect on the Node alone.** No Server restart, no Server
   configuration change and no coordination is involved, because the Server holds
   no copy of the decision.
3. **A new scope is a Node-local act.** Adding a scope requires editing the Node's
   policy file and reloading it. Nothing on the Server changes, so an operator
   cannot widen access by editing Server configuration.

The CLI is not an authority either. It chooses which scope and operation to ask
for, and that choice is a request, not a grant. A CLI that asks for a scope the
policy does not define receives `denied` from the Node, and the CLI has no
way to make the Node agree.

### Default deny

An operation with no matching grant is refused. An empty policy refuses
everything. A missing configuration file is a startup failure, not an implicit
"allow all". A missing or empty secret is likewise a startup failure, not an
"authentication disabled" mode.

## Vocabulary

Two words, deliberately separate, because mixing them is what makes a policy
file unreadable six months later.

| Word | Meaning | Example |
|---|---|---|
| `scope` | A named area the Node exposes. A name, never a path. | `project`, `tool`, `scratch` |
| `permission` | An action allowed inside a scope. | `read`, `write`, `list`, `stat`, `exec` |

A grant is one scope plus the permissions allowed on it. A scope name must be an
identifier: letters, digits, `-` and `_` only. A name containing a path separator
is rejected, because it would let a caller address a directory the policy never
named. A name containing a space, a tab, a control character, a colon or a trailing
dot is also rejected, because such a name reaches a filesystem call in a form no
policy author intended and cannot be reasoned about by reading the file.

The current `ValidateScopeName` is too loose: it rejects only separators and `.` /
`..`, so a space, a tab, a NUL byte, a colon and a trailing dot are all accepted.
That is a defect to fix, not a documentation change.

The Node maps a scope name to a local directory. The Server never learns the real
absolute path, so a directory rename does not invalidate the policy and a leaked
policy does not leak the filesystem layout.

## Three secrets, three gates

The system has three secrets. Each one gates a different thing, and each is
validated by exactly one party. They are separate because a stolen secret must
open one gate, not all three.

| Secret | Generated by | Configured where | Presented by | Validated by | Gates |
|---|---|---|---|---|---|
| `tunnel_token` | Server operator | Server environment | Node, in `hello` | Server | The channel: may this Node connect |
| `client_token` | Server operator | Server environment | CLI, on every request | Server | The CLI's reach: may this caller use the Server |
| `node-id.node-token` | Node | Node config, copied to the CLI | CLI, forwarded by the Server | Node | One operation on one scope |

The first two are Server-wide shared secrets. The third is per-Node and is
generated by the Node itself, so the Server never learns it and never needs to.

### What each gate actually proves

The gates are deliberately narrow. A secret that passes one gate proves nothing
about the others.

- `tunnel_token` proves a Node is allowed to open a link. It does not identify
  which Node, and it grants no operation.
- `client_token` proves a caller is allowed to use the Server. It does not grant
  access to any particular Node, and it grants no operation.
- `node-token` proves a caller is allowed to talk to that one Node. It does not
  grant any particular operation either.

**No secret carries a permission.** This is the important consequence of the
shared-secret model: a token says "you may talk to me", and the policy file says
"and you may do this". Authorization lives in the Node's policy, never in a
token. A token that carried permissions would have to be reissued whenever the
policy changed, and a policy change would silently invalidate live credentials.

### Why the CLI carries two secrets

A CLI request must pass two gates, and each gate is checked by a different party.

| Question | Answered by | Checked by |
|---|---|---|
| May this caller use the Server at all? | `client_token` | Server |
| May this caller operate on this Node? | `node-id.node-token` | Node |

The Server checks the first because the Server owns it. The Node checks the
second because the Node owns it. Neither party can check the other's secret, so
neither party can widen its own authority.

A caller holding only `client_token` reaches the Server but cannot operate on any
Node, because the Node refuses a request without a valid `node-token`. A caller
holding only `node-id.node-token` cannot reach the Server at all, because the
Server refuses the request before forwarding it.

The Server must never treat a valid `client_token` as authority to perform an
operation. If it did, the Server would become an authority for operations, which
the hard constraint forbids.

## Flow

```
1. Provisioning (out of band, once, in this order)
   Server operator: set CONNECTOR_SERVER_TUNNEL_TOKEN and
                    CONNECTOR_SERVER_CLIENT_TOKEN, then start the Server
   Node operator:   connector-node id
                    -> node_7f3a.kq2v...   (node-id.node-token, printed once)
   Node operator:   put the node-id.node-token into the CLI's config
   Node operator:   put tunnel_token into the Node's config

2. Connect
   Node   -> Server : hello { version, node_id, tunnel_token, operations, scopes }
   Server compares tunnel_token with its configured value
   Server -> Node   : hello_confirm { version, generation }

3. Operate
   CLI    -> Server : request { node_id, client_token, node_token, scope, path, ... }
   Server compares client_token with its configured value
   Server forwards node_token unchanged; it never stores it
   Node compares node_token with its own value
   Node resolves scope -> os.Root handle, resolves path inside it, performs the work
   Node -> Server -> CLI : response
```

The Server is a pipe for the `node-token`, not a holder of it. It forwards the
value on every request and keeps no copy, so a Server restart does not preserve
authority and a Server compromise does not yield a stored Node credential.

## Node identity and the node-token pair

The Node generates a single string at first start and persists it in its config
directory. The string is two parts joined by a dot:

```
node-id.node-token
    |         |
    |         +-- the secret the Node checks on every request
    +------------ the public name the Server routes by
```

### The two halves have different jobs

| Half | Secret? | Purpose | May appear in a log |
|---|---|---|---|
| `node-id` | No | Routing and audit. Names which Node a request is for. | Yes |
| `node-token` | Yes | Authentication. Proves the caller may talk to that Node. | Never |

Keeping them in one string is a convenience for copying, not a claim that they
are the same kind of value. The `node-id` half is an address; the `node-token`
half is a credential. Code must split the pair immediately on receipt and treat
the halves differently from that point on, because a single string that is
sometimes logged and sometimes secret will eventually be logged whole.

### Format and parsing

```text
node-id    = "node_" 26( LOWER / DIGIT )     lowercase base32, no dots
node-token = 52( LOWER / DIGIT )             lowercase base32, no dots
pair       = node-id "." node-token
```

Both halves use unpadded lowercase base32: the characters `a` to `z` and `0` to
`9`, and nothing else. The alphabet is deliberately narrow. Base64url would add
`-` and `_`, and base64 would add `+`, `/` and `=`, all of which need escaping in
a URL, a shell argument or a Windows file name. Uppercase is excluded because
Windows compares paths case-insensitively, so a token that differs only in case
would be a token two filesystems disagree about.

The lengths are fixed and derived from the entropy rather than chosen:

| Half | Entropy | Characters | Derivation |
|---|---|---|---|
| `node-id` body | 128 bits | 26 | `ceil(16 * 8 / 5)` |
| `node-token` | 256 bits | 52 | `ceil(32 * 8 / 5)` |

A whole pair is therefore 84 characters: `node_` (5) + 26 + `.` (1) + 52.

The pair is split on the **first** dot, and the rule that makes this
unambiguous is that `node-id` may not contain a dot. Splitting on the last dot
would be wrong: a `node-token` that happened to contain a dot would silently
shift the boundary, and the two halves would be misidentified.

Parsing rules, all of which are refusals rather than repairs:

- No dot at all: malformed, refused.
- Empty `node-id` or empty `node-token`: malformed, refused.
- A second dot in the `node-token` half: malformed, refused. Neither half's
  alphabet contains a dot, so a dot there means the value was corrupted or
  hand-edited.
- A `node-id` that does not start with `node_`: malformed, refused.
- A `node-id` whose body is not exactly 26 characters: refused. A truncated
  identifier addresses nothing, so accepting it would produce a Node that can
  never be reached and an operator who sees `node_offline` instead of "your
  identifier is truncated".
- A character outside `a-z0-9` in either half: refused. This is what rejects
  `-`, `_`, uppercase and every other spelling a base64url implementation would
  have accepted.
- Whitespace anywhere: refused, not trimmed. Trimming hides a copy-paste error
  that would otherwise surface as a confusing authentication failure.

The token length is **not** validated, and the asymmetry with the identifier is
deliberate. A token of an unexpected length is still comparable: the comparison
fails and the request is refused, which is the correct outcome. An identifier of
an unexpected length addresses nothing, so it must fail at parse time. Checking
the token length would also break a token generated by an older build with a
different entropy size, which must remain comparable.

### Why the Node generates its own identity

The Server must never be the authority that mints identity, because an identity
authority can also deny identity. A Node that generates its own name works
without the Server being reachable, and a Server that has never seen a Node can
still route to it once the operator supplies the pair.

- The `node-id` is a random 128 bit value encoded as unpadded lowercase base32,
  prefixed `node_`. A hostname, a MAC address or an IP address is rejected as an
  identifier, because all three change and two of them leak host information.
- The `node-token` is 256 bits from a cryptographic random source, encoded as
  unpadded lowercase base32. It is compared in constant time.
- The Server keeps an in-memory registry `node_id -> connection`. The registry is
  memory only: persisting it would create a record of which Nodes exist and when
  they were last seen, which is a privacy decision this design does not make.

### Regeneration

The Node may regenerate the pair on demand:

```
connector-node regenerate
```

Regeneration is a deliberate, local, operator-initiated action. It is not
triggered by the Server, and the Server has no way to ask for it, because a
Server that could force regeneration could also force a denial of service.

What regeneration does, and what it costs:

| Action | `node-id` | `node-token` | Consequence |
|---|---|---|---|
| `connector-node regenerate` | New | New | The old pair stops working; the CLI must be given the new pair |
| `connector-node regenerate --keep-id` | Unchanged | New | The CLI keeps its routing name but must be given the new secret |

Both forms invalidate the old `node-token` immediately, because the Node compares
against the value it currently holds and keeps no history of previous values. A
Node that accepted an old token after regeneration would defeat the purpose of
regenerating.

The running Node learns about the change by reading its identity file once per
second, so "immediately" means "within one poll interval", not "before the
`regenerate` command returns". The window is bounded and short, and it is stated
here rather than left as an implied instant. Polling is used because the standard
library has no portable filesystem notification API and the design forbids a
third-party dependency; the comparison is on the file's content, because a
regenerated pair has the same byte length as the pair it replaces and can land in
the same modification-time tick.

Two consequences must be stated rather than discovered:

- **Regeneration disconnects the Node.** The live channel was authenticated with
  the old pair, so it is dropped and the Node reconnects with the new one. A
  channel that survived a credential change would be a channel authenticated by a
  credential that no longer exists.
- **Regeneration is not revocation of `tunnel_token` or `client_token`.** Those
  are Server-wide and are changed by editing the Server's environment and
  restarting it. Regenerating a Node pair does not affect them, and changing them
  affects every Node and every CLI at once.

### How the operator learns the pair

The CLI must name the Node and prove it may talk to it, so the operator needs the
pair before the first request. The order is fixed:

```
1. Node starts once, generates the pair, persists it, prints it
   connector-node id
   -> node_7f3a.kq2v...        (the operator copies this string)

2. Node is configured with tunnel_token and connects
3. CLI is configured with client_token and the pair
```

The consequence is that a Node must be started once before any CLI can reach it.
That is acceptable because the first start does no work: it generates a pair and
exits. It is stated here because the reverse order looks natural and fails with a
confusing error, since the Server cannot route to a Node whose name it has never
been told.

Two rules follow:

- `connector-node id` prints the pair and nothing else, so it can be copied into
  a script. It prints a secret, so the operator must treat the output as one: it
  must not be pasted into a ticket, a chat message or a shell history that is
  retained.
- The Server never mints, assigns or overrides a `node-id`. If an operator asks
  the Server for "the node id of my machine", the answer is that the machine must
  be asked. A Server-assigned identifier would make the Server the identity
  authority, which is the thing this design avoids.

An operator who has lost the pair reads it from the Node's config file or runs
`connector-node id` again. There is no lookup endpoint, because a lookup endpoint
would let any caller enumerate which Nodes exist.

### CLI access path

The CLI is a thin client of an HTTP JSON API on the Server. It is not a third
binary and it does not speak the channel protocol, so the channel protocol stays
private to the two components.

```
POST /v1/nodes/{node_id}/operations
  Authorization: Bearer <client_token>
  X-Connector-Node-Token: <node-token>
  Content-Type: application/json

  { "operation": "file.read", "scope": "project", "path": "notes.md",
    "offset": 0, "length": 0 }
```

The `node-id` appears twice on this path, and both occurrences must agree: once in
the URL, where the Server routes by it, and once as the first half of the
`node-id.node-token` pair the CLI holds. The Server compares them. A mismatch is
refused, because otherwise a caller could route to one Node while presenting
another Node's secret, which would turn the routing table into a way to probe
which Nodes exist.

Rules that must hold on this path:

- `client_token` travels in `Authorization`, the `node-token` in a separate
  header. Keeping them in separate headers means a log that redacts
  `Authorization` does not accidentally print the Node's secret, and a proxy that
  rewrites one header does not corrupt the other.
- The Server compares `client_token` before reading the `node-token` at all, so an
  unauthenticated caller cannot use the Server as an oracle for Node token
  validity.
- The Server forwards the `node-token` byte for byte. It does not decode it,
  re-encode it, normalise it or wrap it, because a re-encoded value would be a
  derived value and a derived value is a stored credential index in disguise.
- The Server never writes either secret to a log, an audit record or an error
  message. An audit record names the `node-id`, never a secret.
- A request for an unknown `node_id` is refused with `node_offline`, not queued.
- The Server validates shape only: the operation is known, the scope name is a
  valid identifier, the path is not absolute, and the request fits the frame cap.
  It never validates authority, because authority belongs to the Node.
- The Server does not check whether the `node-token` is correct, because it cannot:
  it does not know the value. It forwards the request and relays the Node's
  refusal. A Server that claimed to validate the Node's secret would be lying
  about a check it never performed.

The endpoint, the header names, the request body and the error codes are specified
in `docs/API.md`. This section states the rules that must hold on that path; the
API document states the shape. A change to one without the other is a defect.

The channel and the CLI API share one listener and one TLS certificate: the channel
is served at `/channel` and the CLI API at `/v1/`. The two surfaces are not
isolated by a port, because they share the routing registry anyway, so a second
listener would buy isolation that does not exist. A deployment that must keep the
CLI API unreachable from the internet blocks `/v1/` at the reverse proxy.

## How a secret is checked

A shared secret is verified by comparison, not by parsing. There is no payload to
decode, no signature to verify and no clock to consult.

```
Server: constant_time_equal(configured_tunnel_token, hello.tunnel_token)
Server: constant_time_equal(configured_client_token, request.client_token)
Node:   constant_time_equal(stored_node_token,     request.node_token)
```

### Comparison rules

- **Constant time.** A byte-by-byte comparison that returns early leaks the length
  of the matching prefix, which lets an attacker recover a secret one byte at a
  time. The comparison must run in time independent of where the first difference
  is.
- **Compare the whole value.** No prefix matching, no "first 8 characters are
  enough", no case-insensitive comparison. A prefix check turns a 256 bit secret
  into an 8 character one.
- **Refuse on absence, not on empty.** A missing header and an empty header are
  both refusals. An empty configured secret is a startup failure, never an
  "accept anything" mode, because an unset environment variable is the most likely
  way to accidentally disable authentication.
- **One error for every failure.** A wrong secret, a missing secret and a
  malformed secret all produce the same response. Distinguishing them tells an
  attacker whether a guess was close.

### What the shared-secret model gives up

This is the honest trade-off, and it is larger than it looks.

| Property | Signed token (previous design) | Shared secret (this design) |
|---|---|---|
| Expiry | Built in; a leaked token dies on its own | **None.** A leaked secret works until it is rotated |
| Per-caller identity | Carried in the token | **None.** Every holder of `client_token` is indistinguishable |
| Revocation | A list of `id` values | Rotate the secret, which affects every holder at once |
| Rotation cost | Revoke one token | Restart the Server, or regenerate the Node pair |
| Implementation | Sign, encode, parse, verify, check window | Compare two strings |

The simplification is real: there is no canonical encoding to get wrong, no clock
skew to tolerate, no signature library to misuse, and no revocation list to keep
consistent. The cost is equally real and must be stated rather than discovered:

- **A leaked `client_token` is valid forever.** There is no expiry to bound it.
  The only remedy is rotation, which invalidates every CLI at once.
- **A leaked `node-token` is valid until the Node regenerates its pair.** The
  operator can regenerate without involving the Server, which is the one advantage
  the Node keeps.
- **No audit trail distinguishes callers.** An audit record can say "a request
  arrived for node_7f3a", but not which operator sent it, because the secret is
  shared. If per-caller attribution is ever required, it needs a fourth mechanism,
  not a change to this one.

These are accepted for the first version. They are recorded in the residual risks
with the mitigation each one actually has, rather than a mitigation that sounds
reassuring and does nothing.

### Rotation

Rotation is the only revocation mechanism, so it must be a documented procedure
rather than an incident-time improvisation.

| Secret | How to rotate | Blast radius | Downtime |
|---|---|---|---|
| `tunnel_token` | Change the Server's environment, restart the Server, update every Node | Every Node | Every Node reconnects |
| `client_token` | Change the Server's environment, restart the Server, update every CLI | Every CLI | None for Nodes |
| `node-id.node-token` | `connector-node regenerate` on that Node, give the new pair to the CLI | One Node | That Node reconnects |

Two rules make rotation safe:

- **The Server accepts exactly one value per secret.** There is no "old and new
  both work" window, because a grace period is a second valid credential and the
  point of rotating is to end the first one. The cost is that rotation is a
  coordinated change, which is stated rather than softened.
- **Rotation is not a hot reload.** The Server reads its secrets once at startup.
  A `SIGHUP` that reloaded them would mean a running Server could change its own
  authority without a restart, and a restart is the cheapest possible audit trail:
  it is visible in the process table and in the logs.

### Secrets are never logged

The rule that covered tokens covers secrets unchanged, and the shared-secret model
makes it more important rather than less, because there is no expiry to bound the
damage of a leaked log line.

- No secret is written to a log, a trace, an audit record or an error message.
- An audit record names the `node-id`, which is public, and never the
  `node-token`, `tunnel_token` or `client_token`.
- A configuration dump redacts all three. A `--print-config` style command that
  echoes the environment is a credential leak with a helpful name.
- A secret is never placed in a URL, a query string or a path segment, because
  those are the parts of a request that proxies and access logs record by default.

## The path fence

The fence is the only real security boundary in a read-only system. A read cannot
corrupt data, so what stands between a caller and every file the Node's user can
read is the path check. This section is therefore the most important part of the
document, and it is stated as an algorithm rather than a principle.

### Why a string prefix check is wrong

The obvious implementation is to join the scope root with the caller's path and
check that the result starts with the root. It is wrong:

```
root = /home/me/project
path = ../project-secret/key
joined = /home/me/project/../project-secret/key
```

`strings.HasPrefix(joined, root)` passes, because the joined string starts with the
root text, while the real file is outside. The same defect appears with a symlink
inside the scope, with a hard link, and with a directory swapped between the check
and the open.

### The fence is `os.Root`

The Node does not implement the fence by hand. It opens one `os.Root` handle per
scope at startup and performs every operation through that handle.

```go
root, err := os.OpenRoot(scopePath)   // once, at startup
f, err := root.Open(relPath)          // per request
```

`os.Root` is standard library, it is available on Windows as well as on POSIX, and
it refuses any name whose resolution leaves the root. The behaviour was verified on
this toolchain (Go 1.25.12) with a probe that created a scope directory, an outside
directory, and several escape attempts:

| Attempt | Result |
|---|---|
| `inside.txt` | allowed, read the file |
| `../outside/secret.txt` | refused: path escapes from parent |
| `escape/secret.txt` where `escape` is a symlink to the outside directory | refused: path escapes from parent |
| `outlink` where `outlink` is a symlink to an outside file | refused: path escapes from parent |
| `/etc/passwd` (absolute) | refused: path escapes from parent |
| `a/../../outside/secret.txt` | refused |
| `rel_inside`, a relative symlink staying inside the root | allowed |
| `rel_out`, a relative symlink climbing out | refused |
| `Lstat` on an escaping symlink | allowed, reports the link itself |
| `Stat` on an escaping symlink | refused |

The last two rows are the reason `file.stat` uses `Lstat` and never `Stat`: a
symlink must be reportable without being followed, and following it is exactly the
operation the fence refuses.

Two consequences follow from using `os.Root` rather than a hand-written check:

- The check and the use apply to the same object. There is no window between a
  path check and an open, because the open itself is the check. A hand-written
  fence has to reproduce this property, and reproducing it correctly is the hard
  part.
- The proof is auditable. A reviewer reads one call site and knows the boundary
  holds, instead of reasoning about a normalisation function and every way it can
  be bypassed.

### What `os.Root` does not do

`os.Root` bounds path resolution. It does not decide policy, and it does not stop
every hazard. The Node must add the following, because each is outside what a root
handle can know.

| Hazard | Why `os.Root` does not cover it | Node rule |
|---|---|---|
| A fifo or device file inside the scope | The path is legitimately inside the root | `read` requires a regular file; anything else is `invalid_argument` |
| A directory passed to `read` | The path is inside the root | `read` requires a regular file; `list` requires a directory |
| The Node's own config, secret and policy files | They may legitimately sit inside a scope | Deny by resolved path, computed at startup |
| A scope root that is `/`, the home directory or a mount root | The root is whatever the operator configured | Refuse at startup |
| A scope root that is a symlink | The root is resolved once, so the link is followed at startup | Refuse at startup |
| A file that grows without bound during a read | The path is inside the root | Cap a single response at 256 KiB |
| A bind mount or a `/proc` file inside the scope | `os.Root` explicitly does not prohibit traversal of filesystem boundaries | Accepted for v1 and stated in the residual risks |

The bind mount row is a real limitation, not a footnote. `os.Root` documents that
it does not prohibit traversal of filesystem boundaries, Linux bind mounts, `/proc`
special files or Unix device files. A scope that contains a bind mount to `/` is
therefore readable through the fence. The mitigation is the startup check that
refuses a scope root which is a mount point, plus the regular-file rule, which
refuses `/proc` entries that are not regular files.

### The deny list answers by identity, not by name

The deny list protects the Node's own config directory, its policy file and its
identity file. It has to answer one question: is this path one of those objects?
The answer must not depend on how the caller spelled the path, because a caller
controls the spelling.

Three rules are needed, and each one covers a gap the others leave open.

| Rule | Question it answers | Gap it closes |
|---|---|---|
| Written-path prefix | Does the path the caller wrote start with a denied directory? | Refuses `config/identity` before any open, so a denied directory is refused even when the entry inside it does not exist yet |
| File identity | Is the opened object the same inode as a denied file? | Refuses a hard link, a different spelling and a case difference, which the written path cannot see |
| Ancestor identity | Is any directory on the way to the path the same inode as a denied directory? | Refuses a symlink alias, which is a different written path and resolves to a different inode for the file inside |

The third rule exists because the first two each cover half of one case. A symlink
inside the scope pointing at the config directory is a different written path, so
the prefix rule cannot see it. A file reached through that link is a different
inode from the directory, so the file rule cannot see it either. Only resolving
each ancestor and comparing its identity closes both gaps at once.

This was measured, not reasoned about. Before the ancestor rule existed, a relative
symlink `alias -> ../node/config` inside the scope returned the real
`tunnel_token`:

```
file.read  alias/identity      -> denied
file.read  alias/policy.yaml   -> denied
file.read  alias/tunnel_token  -> success, the real secret
```

`identity` and `policy.yaml` were refused because they are named in the deny list.
`tunnel_token` lives in the same directory but is not named, so the file rule had
nothing to compare it against. Adding `tunnel_token` to the list would have closed
this one route and left the next unlisted file in that directory exposed; comparing
the identity of every ancestor closes the route itself.

Two consequences follow, and both are deliberate:

- **A directory that merely looks like the config directory stays readable.** The
  rule answers by identity, so a `config` directory at another path, a sibling
  named `config-backup`, and a look-alike nested inside a look-alike are all
  readable. A name-based rule would make a whole-volume scope useless, because
  every directory called `config` would become unreachable.
- **A look-alike nested inside the real config directory is refused**, because its
  ancestor is the real directory. That is the correct answer: the path reaches the
  Node's own directory, whatever the entry inside it is called.

A symlink that resolves to a denied directory is refused by every operation, not
reported. `file.read` refuses it, `file.list` omits it, and `file.stat` refuses it.
The rule is the identity rule applied to the link itself: `config` is refused, so an
alias that resolves to `config` is refused too, whichever name reaches it.

Reporting the link with its target withheld was the earlier behaviour, and it was
wrong twice over:

- **It answered differently depending on the scope shape.** An alias that escapes
  the scope root cannot be resolved through the handle, so the same alias was
  refused under a whole-volume scope and reported under a subdirectory scope. The
  answer depended on an unrelated configuration detail.
- **It disclosed the layout anyway.** A symlink's reported size is the length of
  its target, so withholding the target while reporting its length answered the
  question the withholding was meant to refuse.

An escaping symlink that does **not** resolve to a denied directory is still
reported as a link without being followed, which is the documented `file.stat`
behaviour and the reason `Lstat` is used rather than `Stat`.

The deny-list comparison uses the platform's case rule through `pathEqual` and
`pathHasPrefix`, because the deny list protects a directory the filesystem treats
as one directory. A byte-for-byte comparison on Windows would let `CONFIG` reach
`config`, which is the same bypass the fence refuses elsewhere.

### Path grammar accepted on the wire

The Node rejects a path before it reaches the filesystem, so the accepted grammar
stays small and reviewable. A rejected path is `invalid_argument`, never a silent
normalisation.

| Rule | Rejected example | Reason |
|---|---|---|
| Not empty | `""` | An empty path has no meaning and would resolve to the scope root |
| Not absolute | `/etc/passwd`, `C:\Windows` | An absolute path addresses something the policy never named |
| No `..` component | `../x`, `a/../../x` | Traversal is the primary escape attempt |
| No `.` component | `./x` | Rejected rather than normalised, so the accepted grammar stays small |
| No NUL byte | `a\x00b` | A NUL truncates the string at the syscall boundary, so the checked name and the opened name differ |
| No backslash | `a\b` | On Windows a backslash is a separator; accepting it on POSIX makes the same request mean two things |
| No colon | `a:b` | On Windows a colon introduces a drive or an alternate data stream |
| No leading or trailing space, no control character | `" a"`, `"a\tb"` | A name that differs from what a policy author sees is a name they cannot reason about |
| No trailing dot or space on Windows | `a.`, `a ` | Windows strips them, so the checked name and the opened name differ |
| Length bounded | a 100 KiB path | An unbounded path is a memory and log problem |

The path is treated as an opaque byte string and is never percent-decoded. A caller
that sends `%2e%2e` gets a literal `%2e%2e` component, which is not `..` and is not
a traversal. Decoding would create a second grammar to reason about, and the second
grammar is where the bug lives.

### Depth and path length

Depth is not a separate rule. A path is bounded by two numbers and nothing else:
`MaxPathLength` (4096 bytes for the whole path) and `maxComponentLength` (255
bytes for one component). There is no component count limit, and `os.Root` imposes
none either, so a deeply nested tree is readable exactly as a shallow one is.

That is the intended behaviour, because depth is a dimension a caller actually
uses. A real project tree is many levels deep, so a depth limit would be a limit on
the product rather than on an attack. The fence does not need one: an escape is
refused wherever it happens, because the check is the open rather than a scan of
the path.

The measured ceilings, with the measurement stated rather than implied:

| Platform | Deepest tree that could be created | Absolute path length | Limit that stopped it | How it was measured |
|---|---|---|---|---|
| Linux | 2025 levels | 4096 bytes | `PATH_MAX` | Measured on the build host by creating nested directories until `mkdir` failed with `ENAMETOOLONG` |
| Windows | 114 levels | 246 characters | `MAX_PATH` (260) | Measured twice on a real Windows Server 2022 host: level 115 failed with `Could not find a part of the path` |

The Windows figure cannot be reproduced on a Linux build host, and wine is not a
substitute: wine resolves paths through the Linux filesystem, so it does not
enforce `MAX_PATH` and a 500 level tree passes there. The Windows number therefore
comes from a real Windows host, and a change to it must be re-measured on one.

The two platforms differ by an order of magnitude, and the difference is the
kernel's, not the Node's. On Windows the default `MAX_PATH` is 260 characters, so a
tree that Linux accepts is refused by Windows long before the grammar limit is
reached. The extended-length `\\?\` prefix would raise the Windows limit, but the
grammar rejects it as an absolute path, which is the correct trade: a prefix that
changes how the rest of the path is interpreted is exactly the kind of second
grammar this design refuses to add.

Two consequences follow, and both are stated rather than discovered:

- **A path the grammar accepts can still be refused by the kernel.** `MaxPathLength`
  and `PATH_MAX` are the same order of magnitude, so the grammar is not a promise
  that the filesystem will accept the path. The security property is that such a
  path never succeeds; the refusal code depends on how the kernel reports it.
- **Beyond the filesystem ceiling the refusal is `not_found`, not
  `invalid_argument`.** The kernel reports an over-long path as missing, and
  `classifyOpenError` relays that classification rather than inventing a different
  one. A caller therefore cannot tell "too long" from "absent" at that boundary,
  which is consistent with the rule that a refusal does not become an existence
  oracle.

Depth does not weaken the fence. A symlink or junction planted at the bottom of a
deep tree is refused exactly as one at the root is, because `os.Root` resolves the
whole path rather than a prefix of it.

The Linux case is covered by a test and by the live script: a symlink at depth 20
pointing outside the scope returns `denied` for `file.read`, and `file.stat`
reports the link without following it.

The Windows case was measured on a real Windows Server 2022 host, not inferred. A
junction at depth 20 pointing at the Node's own config directory returned `denied`
for `file.read` with the reason `path escapes from parent`, and `file.stat` on the
junction returned `success` reporting the link without following it. The same run
read a file at every depth from 1 to 114 and compared the decoded content with the
payload that level was written with, so a successful open returning the wrong file
would have failed rather than passed. Depth 115 returned `not_found`, which is the
filesystem ceiling rather than a grammar refusal.

That run is reproducible only on a Windows host. The Linux build host cannot
execute the Windows path rules, and wine is not a substitute because it resolves
paths through the Linux filesystem. The automated coverage that does run on the
build host is the Windows test binary compiled by `make test-windows-compile`; the
live Windows evidence is recorded here rather than asserted by a test that cannot
run.

### Windows specifics

Windows is supported in the first version, and the fence is the same `os.Root`
handle. What differs is the set of names that mean something other than they appear.

| Hazard | Behaviour | Rule |
|---|---|---|
| Reserved device names | `NUL`, `CON`, `COM1`, `LPT1` and friends resolve to devices regardless of directory | Rejected as a path component. `os.Root` also refuses them on Windows, so this is defence in depth |
| Alternate data streams | `file.txt:stream` addresses a hidden stream | Rejected by the colon rule |
| Trailing dot and space | `a.` and `a ` are stripped by the filesystem, so `a.` opens `a` | Rejected, so the checked name equals the opened name |
| Case insensitivity | `Notes.md` and `notes.md` are the same file | Accepted as-is. The fence is unaffected, but a deny-list entry must be compared case-insensitively on Windows |
| Short names | `PROGRA~1` is an alias for `Program Files` | Accepted as-is; `os.Root` resolves it inside the root, so it cannot escape |
| UNC and extended-length prefixes | `\\?\C:\...`, `\\server\share` | Rejected by the absolute-path rule |
| Junctions and reparse points | A junction is a directory symlink | Refused when it escapes, by the same `os.Root` rule as a symlink |
| Drive-relative paths | `C:file` is relative to the current directory on drive C | Rejected by the colon rule |

The deny-list comparison is the one place where platform behaviour changes a
decision rather than a rule: on Windows a path comparison must be case-insensitive,
otherwise a deny-list entry for `config.yaml` is bypassed by `CONFIG.YAML`.

### Scope to directory mapping

A scope name maps to a directory. The mapping is validated once at startup, and the
resolved path is stored, so a rename during runtime does not silently change what a
scope means.

- The path is absolute. A relative path would resolve differently depending on the
  working directory, which is a different meaning per launch.
- The path exists and is a directory.
- The path is not a symlink or a junction.
- The path is not `/`, not the user's home directory, and not a mount root, because
  the blast radius of those is the whole machine. A filesystem root such as `C:\` is
  refused for the same reason, unless the policy states `allow_filesystem_root: true`
  and the operator has therefore written the blast radius down.
- The path is not inside the Node's own config directory, and the config directory
  is not inside the path. A scope that can read its own credentials is a
  configuration mistake worth refusing at startup rather than denying per request.
  This rule is relaxed together with the filesystem-root rule, because a scope
  rooted at a volume necessarily contains the config directory; the deny list then
  refuses the directory and everything inside it, and a listing omits it.
- The `os.Root` handle is opened once and reused. If the directory is moved, the
  handle keeps referencing the original directory in its new location, which is the
  behaviour the fence wants: the scope means the directory that was validated, not
  whatever now occupies that name.

The overlap rule is a startup refusal, not a per-request deny, because the deny list
protects the contents of the credential files while the scope still lets a caller
list the directory and learn their names and sizes. The comparison is on path
components rather than on a string prefix, so a sibling named `config-backup` is not
mistaken for a child of `config`, and on Windows it is case-insensitive because the
filesystem is. A scope that equals the config directory, contains it, or sits inside
it is refused with a message naming both paths.

When the policy opts in to a filesystem root, the overlap refusal is relaxed and the
deny list takes over. The config directory is then a deny entry, so the directory
itself and every path inside it are refused before they are opened, and a listing
omits the entry rather than reporting its name and size. The deny list is what
protects the credential in that case; the startup refusal is not available.

### Policy file

The policy file is the only place a scope is defined. It is YAML, it is required,
and a missing file is a startup failure rather than an implicit allow-all.

```yaml
version: 1
scopes:
  project:
    path: /home/me/project
  scratch:
    path: /home/me/scratch
grants:
  - scope: project
    permissions: [read, list, stat]
```

A policy that must expose a whole volume states the opt-in explicitly:

```yaml
version: 1
allow_filesystem_root: true
scopes:
  cdrive:
    path: C:\
grants:
  - scope: cdrive
    permissions: [read, list, stat]
```

`allow_filesystem_root` is absent by default, and its absence is the refusal. It
relaxes exactly two startup rules: a scope rooted at a filesystem root, and a scope
that contains the Node's config directory. The second follows from the first rather
than being a separate permission, because a scope rooted at `C:\` necessarily
contains the config directory. Every other rule still applies: the path must be
absolute, real, a directory and not a symlink, and the fence still refuses every
path that leaves the root.

The opt-in is safe only because the config directory is on the deny list. Once the
startup refusal is relaxed, the deny list carries the protection: the directory and
everything inside it are refused, and a listing omits it rather than reporting its
name and size. Without that deny entry the opt-in would hand a caller the identity
file, which is the credential that authorizes every operation on the Node.

### How a bundle expresses the opt-in

A bundle is a zip that someone else unzips and starts, so the opt-in is decided by
the person who builds the bundle, not by the person who receives it. The decision
is a packaging-time variable:

```
make package PACKAGE_SERVER_URL=... PACKAGE_SCOPES=... PACKAGE_ALLOW_FILESYSTEM_ROOT=1
```

It is unset by default, and unset means off. The value is validated strictly: `1`
enables it, an empty value or `0` disables it, and anything else fails packaging
rather than being read as "off". A value such as `true` is refused because a
security switch that silently accepts a spelling it does not understand is a switch
whose state nobody can state.

The decision is recorded in the bundle as a file named `allow_filesystem_root`
holding `0` or `1`, and the start scripts read that file. It is deliberately not an
environment variable: an environment variable would let whoever runs the bundle
widen the blast radius without touching a file, which is exactly the control this
split exists to prevent. The file is always written, so "not enabled" is a recorded
decision rather than a missing file that could mean either.

Under the opt-in the start scripts skip two refusals, the same two the Node relaxes:
a scope rooted at a volume, and a scope that contains the config directory. The
home-directory refusal is never skipped, because the Node refuses it unconditionally
and a bundle that allowed it would fail on the recipient's machine instead of at
packaging time. The deny list still protects the credential, so a bundle that
exposes a whole volume still cannot read `config/identity`.

Validation rules, all of which fail startup rather than warn:

- `version` is required, so a future format change is detectable.
- Every scope needs an absolute `path`.
- A scope name must pass the identifier rule: letters, digits, `-` and `_` only.
  `security.ValidateScopeName` is a whitelist, so a space, a tab, a NUL byte, a
  colon and a trailing dot are refused because they are not in the alphabet
  rather than because someone remembered to list them.
- A `grants` entry naming an undefined scope is an error, not a silent no-op,
  because a typo would otherwise look like a working policy.
- An unknown permission string is an error.
- A permission listed twice in one grant is an error, because a policy that says
  the same thing twice is a policy whose author was not reading what they wrote.
- An empty `grants` list is valid and refuses everything.
- An unknown key is an error, because a typo in a security config that is silently
  ignored is worse than a crash.
- A file holding more than one YAML document is an error, because the second
  document would be silently ignored and a policy that is half-read is a policy
  nobody can reason about.
- An empty file is an error rather than an empty policy. An empty policy refuses
  everything, which looks like a working Node that denies every request.
- The file is capped at 1 MiB and the cap is applied before decoding, because
  reading an oversized file into memory before deciding it is oversized is the
  wrong order.
- Reload on `SIGHUP` is all-or-nothing: a file that fails validation leaves the
  previous policy in force and logs the rejection.

The policy file is parsed with `gopkg.in/yaml.v3`, the project's only third-party
dependency. A hand-written parser was rejected: a security configuration parser
that disagrees with every other YAML reader about quoting, anchors or duplicate
keys is a parser whose mistakes are invisible in review. Decoding is strict
(`KnownFields(true)`), so an unknown key is refused rather than ignored.

The policy file is the only place a permission is granted. A secret proves the
caller may talk to the Node; the policy decides what the caller may do once it has
been admitted. There is no second source of authority to reconcile, so there is no
"which one wins" question: a request for an operation the policy does not grant is
refused, regardless of which secret the caller holds.

## Embedded configuration

A second packaging mode compiles the configuration into the Node binary, so the
recipient runs one executable and the Node is reachable with no configuration file
and no environment variable. The zip bundle and the embedded binary are two
deliveries of the same Node; the permission model does not change between them.

### What is compiled in

| Piece | Embedded | Reason |
|---|---|---|
| Server URL | Yes | Static, no secret |
| Policy document | Yes, base64 | A YAML document does not survive a shell, Makefile or linker flag; base64 is a quoting decision, not a secrecy one |
| `tunnel_token` | Yes, by operator decision | The Node cannot dial without it, so "start it and it works" is unmet otherwise |
| `node-id.node-token` pair | **No** | Generated on first start, polled every second, rewritten by `regenerate` |

The identity pair is excluded for two reasons, and both are refusals rather than
limitations to work around:

- **Regeneration has no file to rewrite.** `connector-node regenerate` writes the
  identity file and the running Node adopts it by polling. An embedded pair has no
  file, so regeneration would either be unavailable or would silently disagree with
  the value in memory.
- **Two copies would share one `node-id`.** The Server keeps an in-memory registry
  `node_id -> connection`, so a second machine running the same binary would evict
  the first. An identity that is not unique per machine is not an identity.

The binary therefore still generates its own pair on first start and prints it
once, exactly as a normal build does. "Start it and it works" holds: the Node
connects without configuration, and the operator runs `<binary> id` once to learn
the pair the CLI must present.

### Precedence

Environment wins over embedded, field by field, so an operator can repoint the same
binary without a rebuild.

The policy is the deliberate exception. A build that embedded a policy **refuses**
`CONNECTOR_NODE_POLICY_FILE`, because an embedded policy is a whole document: a
file path would silently replace every scope and every grant, and the operator
would be looking at a policy file that is not the one in force. A refusal is
visible; a silent replacement is not.

### The binary becomes a credential

Embedding the `tunnel_token` makes the executable a Server-wide credential. The
residual-risk table already states the consequence: a leaked `tunnel_token` lets
anyone open a channel and impersonate a Node, with every Node in the blast radius.
Embedding it moves that secret from a file the operator controls to a file the
recipient can copy.

Two rules follow, and the first is not optional:

1. **A build that carries the `tunnel_token` adds its own executable to the deny
   list.** Without this, a scope that contains the binary serves it: a whole-volume
   scope such as `C:\` contains the install directory, so `file.read` on the binary
   would return the token to a remote caller. The deny entry is what keeps the
   embedded secret from becoming a remotely extractable one.
2. **The deny entry is conditional on the token being present.** A normal build
   discloses nothing by being read, and refusing it would break serving the install
   directory for no gain. The condition is `embedded.CarriesSecret()`, not "the
   build is embedded", because a build with only a Server URL and a policy carries
   no secret.

The deny entry uses `os.Executable()`, not `os.Args[0]`. The latter is whatever the
launcher typed — a relative path, a symlink, or a bare name resolved through
`PATH` — and the deny list compares by file identity, so a name that does not
resolve to the running file would not match.

### What embedding does not protect

`-X` stores the value as plain text in the binary's data section, so
`strings connector-node` recovers it. This is stated rather than implied, and it is
not a defect to fix by encoding: base64, compression or obfuscation all decode with
the same command, and encryption would need a key that the binary must also carry.
A secret compiled into a binary is readable by anyone who holds the binary. The
protection that matters is the deny list, which stops a *remote* caller from
reading it; a local user with the file already has the secret.

### Scope paths are fixed at build time

The zip bundle resolves scope paths when it starts, because it runs on the target
machine. An embedded policy is fixed when the binary is built, so the paths are
written exactly as the packaging step received them and are never resolved on the
build host. Resolving them would bake the build host's filesystem into a binary
meant for another machine, which fails on the recipient's host with a path that
never existed there.

The consequence is stated in the packaging summary: an embedded build suits a fixed
path such as `C:\` or `/srv/data`, and a build whose scope paths differ per machine
should use the zip bundle.

### Same validation on both paths

An embedded policy is decoded by `policy.ParseBytes`, the same strict decoder the
file path uses: unknown keys refused, an empty document refused, a grant naming an
undefined scope refused, the 1 MiB cap applied. A second, looser parser for the
embedded path was rejected, because two parsers that disagree about a security
configuration is the defect the strict decoder exists to prevent.

The scope-opening rules live in one function shared by both paths, so the fence
cannot be configured differently depending on how the policy arrived.

## First version scope

The first version is read-only. This is a deliberate risk decision, not a
scheduling shortcut.

| Version | Operations | Reason |
|---|---|---|
| First | `file.list`, `file.stat`, `file.read` | Read-only cannot corrupt data; the path fence is the only risk to get right |
| Second | `file.write` | Adds size limits, atomic replace and a backup before overwrite |
| Third | `command.exec` | Only if a real need appears; the risk surface is an order of magnitude larger |

`command.exec` is excluded from the first version because a command allowlist is
not a sandbox. `find -exec`, `git -c core.pager=...`, `tar --to-command` and
`less` shell escapes all reach an interpreter through a program that looks
harmless. Getting the file fence right first is worth more than adding a second
escape surface early.

## Residual risks

These are accepted for the first version and must be stated rather than hidden.

| Risk | Consequence | Mitigation |
|---|---|---|
| A leaked `client_token` never expires | Every CLI is compromised until the secret is rotated | Rotate the Server's environment and restart; audit every request. This is the accepted cost of the shared-secret model |
| A leaked `node-token` never expires | Anyone holding it can operate on that Node until the pair is regenerated | `connector-node regenerate` invalidates it within one poll interval and needs no Server involvement; a running Node adopts the new pair without a restart |
| A leaked `tunnel_token` never expires | Anyone holding it can open a channel and impersonate a Node | Rotate the Server's environment and restart; the blast radius is every Node |
| No per-caller attribution | An audit record cannot say which operator sent a request | Accepted; per-caller identity needs a fourth mechanism, not a change to this one |
| Server sees the `node-token` in transit | A compromised Server can replay it while it holds the request | The Server never stores it; the value lives only for the request being forwarded |
| Node host compromised | The fence is gone entirely | Host security; nothing in this design helps |
| Secret in a shell history or log | Credential leak with no expiry to bound it | Never log a secret; audit records name the `node-id` only; `connector-node id` prints a secret, so its output must not be pasted into a ticket or a retained history |
| A secret passed as a CLI flag | The value is visible in `argv` to every account on the host and is written to shell history by default | Accepted trade-off, decided by the human on 2026-11-13. The environment variable is the recommended form and keeps the secret out of both; the flag exists so a script that already holds the secret can pass it without exporting it. Removing the flag would not remove the exposure, because `/proc/<pid>/environ` is readable by the same accounts that can read `argv` |
| A bind mount or `/proc` entry inside a scope | `os.Root` does not prohibit traversal of filesystem boundaries, so such a path is readable | Refuse a scope root that is a mount point; refuse a non-regular file for `read` |
| Windows path comparison is case-insensitive | A deny-list entry for `config.yaml` is bypassed by `CONFIG.YAML` | Compare deny-list paths case-insensitively on Windows |
| A hard link inside a scope to a file outside it | The link is a legitimate directory entry, so the fence allows it | Accepted; a hard link cannot be created without write access to the target, so it is not a remote escalation |
| The CLI holds both secrets at once | A compromised CLI host yields both credentials | The `node-token` is per-Node and regenerable; the `client_token` is Server-wide, so a compromised workstation affects every Node that workstation can reach |
| The Server sees both secrets on the CLI path | A compromised Server can replay either | The Server stores neither; `client_token` is compared and dropped, `node-token` is forwarded and released |
| Rotation is a coordinated change | Rotating `client_token` breaks every CLI at once, with no grace period | Accepted; a grace period would be a second valid credential, which defeats the purpose of rotating. The procedure is documented rather than improvised |

## Decisions

These were open questions and are now settled. The reasoning is recorded so a
later change has to argue against it rather than silently reverse it.

| Question | Decision | Reasoning |
|---|---|---|
| Signed tokens with expiry, or shared secrets? | Shared secrets | The human specified `tunnel_token`, `client_token` and a Node-generated `node-id.node-token`. A shared secret removes the canonical encoding, the signature library, the clock window and the revocation list, which is a large reduction in the code that can be wrong. The cost is that no secret expires, which is recorded in the residual risks rather than softened. |
| Does any secret carry a permission? | No | A token says "you may talk to me"; the policy file says "and you may do this". A token that carried permissions would have to be reissued whenever the policy changed, and a policy change would silently invalidate live credentials. |
| Who generates the `node-id.node-token` pair? | The Node, at first start | The Server must never be the identity authority, because an identity authority can also deny identity. A Node that names itself works without the Server being reachable. |
| May the Node regenerate the pair? | Yes, on local operator command | `connector-node regenerate` issues a new pair and invalidates the old one within one poll interval. A running Node watches its identity file and adopts the new pair, dropping the channel authenticated with the retired one. The Server cannot trigger it, because a Server that could force regeneration could also force a denial of service. |
| Does regeneration keep the `node-id`? | Optional, via `--keep-id` | Keeping the name avoids reconfiguring the CLI's routing target; changing it avoids a name that has been exposed. Both forms always change the `node-token`, because a regeneration that kept the secret would not be a regeneration. |
| Where do `tunnel_token` and `client_token` live? | Server environment | The human specified environment variables. They are read once at startup, never written to a config file, never logged, and an empty value is a startup failure rather than an "authentication disabled" mode. |
| Is there a grace period during rotation? | No | A grace period is a second valid credential, and the point of rotating is to end the first one. Rotation is therefore a coordinated change, which is documented rather than improvised. |
| Let the Node issue a token over the channel? | No | It would make the Server a token courier, which weakens the separation the three-secret design exists to create. The pair is generated locally on the Node. |
| Include `command.exec` in the first version? | No | See "First version scope". A command allowlist is not a sandbox. |
| Support Windows in the first version? | Yes | The human required it. The fence is implemented with `os.Root`, which is standard library and enforces the boundary on Windows as well as on POSIX, so the platform cost is a set of path rules rather than a second fence implementation. |
| Does the CLI carry two secrets? | Yes | The CLI presents `client_token` and the `node-id.node-token` pair together. The Server compares `client_token` to prove the caller may use the Server, forwards the pair unchanged, and the Node compares the `node-token` to decide whether the operation happens. Each side checks only the secret it owns. |
| Does the Server keep `client_token` after comparing it? | No, beyond the request | It is compared per request and released when the response is written. It is never cached between requests, so a retry re-reads it from the caller. |
| Does the Server store the `node-token` from a CLI request? | No | It is forwarded on the request it arrived with and released when the response is written. The Server never learns the correct value, so it could not validate it even if it wanted to. |
| Is the `node-id` a secret? | No | It is an address, not a credential. It appears in `hello`, in audit records and in the CLI, so it must never be usable as an authenticator. Knowing a `node-id` grants nothing without the `node-token`. |
| Is the `node-token` a secret? | Yes | It is the only thing that authorizes an operation on that Node. It must never be logged, and `connector-node id` prints it, so that output must be handled as a credential. |
| How does the operator learn the pair? | The Node prints it; the Server never assigns it | The Node must start once before any CLI can reach it, because the Server cannot route to a name it has never been told. `connector-node id` prints the pair and nothing else. There is no lookup endpoint, because a lookup endpoint would let any caller enumerate which Nodes exist. |
| Does the CLI API get its own listener? | No, one listener serves both surfaces | The two surfaces share the routing registry, so a second port would not isolate state. One listener means one TLS certificate, one firewall rule and one proxy entry. A deployment that must hide the CLI API blocks `/v1/` at the proxy. |
| Who decides whether an operation is permitted? | The Node, on both dimensions | The human stated that all permissions are controlled by the Node, covering the access scope and the concrete read/write/exec permission. The Server holds no scope list and no permission list, so it cannot answer "may this caller do this?" and does not try. A policy change and a new scope are therefore Node-local acts, which is what makes access impossible to widen by editing Server configuration. |
| May the Server pre-approve a request? | No | The Server's authentication proves only that the caller may use the Server. A request the Server has already authenticated is still unauthenticated as far as the Node is concerned, so there is no approval field and an unknown field is refused rather than ignored. |
| May a request state its own permission or role? | No | A caller that could state its own permission would be granting itself one. The request carries a scope name and an operation; the permission is derived from the operation and looked up in the Node's policy. |

## Enforcement checklist

A reviewer checks these before accepting a change that touches the channel or the
request path.

- [ ] No code path writes `tunnel_token`, `client_token` or a `node-token` to a
      log, trace, audit record or error message.
- [ ] No code path stores a `node-token` in a struct field that outlives the
      request being forwarded.
- [ ] No code path stores a hash, prefix or fingerprint of a `node-token`.
- [ ] A retry re-reads the secret from the caller instead of replaying a stored
      copy.
- [ ] Every secret comparison is constant time and compares the whole value. No
      prefix match, no case-insensitive match, no early return.
- [ ] An empty or missing `tunnel_token` or `client_token` fails startup instead
      of disabling authentication.
- [ ] A wrong secret, a missing secret and a malformed secret produce the same
      error, so a caller cannot tell whether a guess was close.
- [ ] An operation with no matching grant is refused.
- [ ] An empty policy refuses everything.
- [ ] A missing policy file fails startup instead of allowing everything.
- [ ] Every file operation goes through an `os.Root` handle opened once at
      startup. No code path joins a scope root with a caller-supplied path and
      then opens the result.
- [ ] A wire path containing `..`, `.`, a backslash, a colon, a NUL byte or a
      leading `/` is rejected before it reaches the filesystem.
- [ ] A symlink that escapes the scope is refused, and `file.stat` reports a
      symlink without following it.
- [ ] A deeply nested path is readable, and a symlink or junction at depth is
      refused exactly as one at the root is. Depth is not a separate rule, so a
      depth limit would be a limit on the product rather than on an attack.
- [ ] A path over `MaxPathLength` is refused as `invalid_argument` before it
      reaches the filesystem, and a path the kernel refuses is never a success.
- [ ] A target that is not a regular file is refused for `read`, and a target that
      is not a directory is refused for `list`.
- [ ] The Node's own config, secret and policy files are denied by resolved path,
      not by file name.
- [ ] The deny list answers by identity, not by name: a symlink inside the scope
      that points at the config directory is refused for every file inside it,
      including a file the deny list does not name, because every ancestor is
      compared by identity.
- [ ] A directory that merely looks like the config directory stays readable, and
      a sibling whose name shares the prefix (`config-backup`) stays readable, so
      the rule does not over-refuse.
- [ ] A symlink that resolves to a denied directory is refused by every operation:
      `file.read` refuses it, `file.list` omits it, and `file.stat` refuses it, so
      the answer does not depend on the scope shape and the link's target length
      does not disclose the layout.
- [ ] An escaping symlink that does not resolve to a denied directory is still
      reported as a link without being followed, so `file.stat` keeps its
      documented behaviour.
- [ ] A scope whose resolved path equals, contains or sits inside the Node's
      config directory is refused at startup, so the names and sizes of the
      credential files are not listable even though their contents are denied.
- [ ] A scope rooted at a filesystem root is refused at startup unless the policy
      states `allow_filesystem_root: true`, and the opt-in is absent by default.
- [ ] When the opt-in is set, the config directory is on the deny list, so the
      directory and everything inside it are refused and a listing omits it. The
      deny list, not the startup refusal, is what protects the credential in that
      case.
- [ ] The opt-in relaxes the filesystem-root and config-overlap rules and nothing
      else: a relative path, a symlink root, a mount point, the home directory and
      every escaping path are still refused.
- [ ] A bundle records the opt-in as a file named `allow_filesystem_root` holding
      `0` or `1`, never as an environment variable, so the recipient cannot widen
      the blast radius without editing a file the packaging step wrote.
- [ ] The packaging variable is unset by default, and a value other than `1`, `0`
      or empty fails packaging instead of being read as "off".
- [ ] Under the opt-in the start scripts skip the volume-root and config-overlap
      refusals and never the home-directory refusal, because the Node refuses the
      home directory unconditionally.
- [ ] The `node-id.node-token` pair is split on the first dot, and a pair with no
      dot, an empty half, a second dot in the token half, a missing `node_` prefix
      or any whitespace is refused rather than repaired.
- [ ] The `node-id` in the URL is compared with the `node-id` half of the pair, and
      a mismatch is refused.
- [ ] `file.write` and `command.exec` are refused at dispatch even when a caller
      sends one, so the refusal does not depend on the advertisement.
- [ ] `connector-node regenerate` invalidates the previous `node-token` within one
      poll interval, and the Node keeps no history of accepted values.
- [ ] A running Node adopts a regenerated pair from its identity file, so
      regeneration does not require a restart.
- [ ] Regeneration drops the live channel, so a connection cannot survive the
      credential that authenticated it.
- [ ] The Windows build compiles, and the Windows-specific path rules are covered
      by a test that does not depend on the host platform.
- [ ] `client_token` is compared before the `node-token` is read, so an
      unauthenticated caller cannot use the Server as an oracle for Node token
      validity.
- [ ] A request for an unknown `node_id` is refused rather than queued.
- [ ] The Server forwards the `node-token` byte for byte. No code path decodes,
      re-encodes, normalises or wraps it.
- [ ] The Server does not claim to validate the `node-token`, because it does not
      know the value. It relays the Node's refusal.
- [ ] `denied` and `not_found` are distinct codes, so a caller cannot probe for a
      file it may not read.
- [ ] An `internal` error carries no detail string, because a detail string is
      where an absolute path or a secret fragment reaches a caller.
- [ ] `connector-node id` prints the pair and nothing else, and the Server has no
      endpoint that assigns, overrides or looks up a `node-id`.
- [ ] The channel and the CLI API are served from one listener, and the CLI API
      path prefix is `/v1/` so a reverse proxy can block it without a second port.
- [ ] The Node's policy file is the only place a scope or a permission is
      granted. No code path on the Server reads, caches, forwards or infers a
      scope list or a permission list.
- [ ] No request field lets a caller state its own permission, role or approval,
      and an unknown field is refused rather than ignored.
- [ ] The scope check and the permission check both run on the Node, after the
      `node-token` is validated, and both refuse by default.
- [ ] A refusal names which check refused it, so a misconfigured policy is
      distinguishable from an attack in the log.
- [ ] A policy reload is all-or-nothing, and a failed reload keeps the previous
      policy in force.
- [ ] A build that carries the `tunnel_token` adds its own executable to the deny
      list, so a scope that contains the binary cannot serve it. The entry uses
      `os.Executable()`, not `os.Args[0]`, because the deny list compares by file
      identity.
- [ ] The executable deny entry is conditional on the token being present, so a
      normal build still serves its own install directory.
- [ ] An embedded policy is decoded by the same strict decoder as the policy file,
      and a build that embedded a policy refuses `CONNECTOR_NODE_POLICY_FILE`
      instead of letting a file silently replace every scope and grant.
- [ ] An embedded policy writes scope paths exactly as the packaging step received
      them, never resolved on the build host, because the binary runs on another
      machine.
