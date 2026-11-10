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
                    -> node_7f3a.kQ2v...   (node-id.node-token, printed once)
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

```
node-id    = "node_" 1*( ALPHA / DIGIT / "-" )      no dots, no underscores
node-token = 32*64 ( ALPHA / DIGIT / "-" / "_" )   base64url, no dots
pair       = node-id "." node-token
```

The pair is split on the **first** dot, and the rule that makes this
unambiguous is that `node-id` may not contain a dot. Splitting on the last dot
would be wrong: a `node-token` that happened to contain a dot would silently
shift the boundary, and the two halves would be misidentified.

Parsing rules, all of which are refusals rather than repairs:

- No dot at all: malformed, refused.
- Empty `node-id` or empty `node-token`: malformed, refused.
- A second dot in the `node-token` half: malformed, refused. A `node-token` is
  base64url, so a dot there means the value was corrupted or hand-edited.
- A `node-id` that does not start with `node_`: malformed, refused.
- Whitespace anywhere: refused, not trimmed. Trimming hides a copy-paste error
  that would otherwise surface as a confusing authentication failure.

### Why the Node generates its own identity

The Server must never be the authority that mints identity, because an identity
authority can also deny identity. A Node that generates its own name works
without the Server being reachable, and a Server that has never seen a Node can
still route to it once the operator supplies the pair.

- The `node-id` is a random 128 bit value encoded as lowercase hex or base32,
  prefixed `node_`. A hostname, a MAC address or an IP address is rejected as an
  identifier, because all three change and two of them leak host information.
- The `node-token` is 256 bits from a cryptographic random source, base64url
  encoded. It is compared in constant time.
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
   -> node_7f3a.kQ2v...        (the operator copies this string)

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
- The path is not `/`, not the user's home directory, and not a filesystem or mount
  root, because the blast radius of those is the whole machine.
- The path is not inside the Node's own config directory, and the config directory
  is not inside the path. A scope that can read its own credentials is a
  configuration mistake worth refusing at startup rather than denying per request.
- The `os.Root` handle is opened once and reused. If the directory is moved, the
  handle keeps referencing the original directory in its new location, which is the
  behaviour the fence wants: the scope means the directory that was validated, not
  whatever now occupies that name.

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
| A leaked `node-token` never expires | Anyone holding it can operate on that Node until the pair is regenerated | `connector-node regenerate` invalidates it immediately and needs no Server involvement |
| A leaked `tunnel_token` never expires | Anyone holding it can open a channel and impersonate a Node | Rotate the Server's environment and restart; the blast radius is every Node |
| No per-caller attribution | An audit record cannot say which operator sent a request | Accepted; per-caller identity needs a fourth mechanism, not a change to this one |
| Server sees the `node-token` in transit | A compromised Server can replay it while it holds the request | The Server never stores it; the value lives only for the request being forwarded |
| Node host compromised | The fence is gone entirely | Host security; nothing in this design helps |
| Secret in a shell history or log | Credential leak with no expiry to bound it | Never log a secret; audit records name the `node-id` only; `connector-node id` prints a secret, so its output must not be pasted into a ticket or a retained history |
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
| May the Node regenerate the pair? | Yes, on local operator command | `connector-node regenerate` issues a new pair and invalidates the old one immediately. The Server cannot trigger it, because a Server that could force regeneration could also force a denial of service. |
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
- [ ] A target that is not a regular file is refused for `read`, and a target that
      is not a directory is refused for `list`.
- [ ] The Node's own config, secret and policy files are denied by resolved path,
      not by file name.
- [ ] The `node-id.node-token` pair is split on the first dot, and a pair with no
      dot, an empty half, a second dot in the token half, a missing `node_` prefix
      or any whitespace is refused rather than repaired.
- [ ] The `node-id` in the URL is compared with the `node-id` half of the pair, and
      a mismatch is refused.
- [ ] `file.write` and `command.exec` are refused at dispatch even when a caller
      sends one, so the refusal does not depend on the advertisement.
- [ ] `connector-node regenerate` invalidates the previous `node-token`
      immediately, and the Node keeps no history of accepted values.
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
