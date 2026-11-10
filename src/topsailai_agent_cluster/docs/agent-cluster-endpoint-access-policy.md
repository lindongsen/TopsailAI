---
maintainer: AI
author: DawsonLin
status: discussion-draft
created: 2026-11-10
---

# Endpoint Access Policy

## Purpose

An Endpoint decides which cluster operations it accepts. The decision belongs to the
machine that would perform the work, not to the Server that routed the request.

The Server is a router, not an authorizer. It verifies that the caller may talk to the
cluster, that the addressed Endpoint exists, and that a live channel reaches it. It then
forwards the request unchanged. It never decides whether an operation is permitted, and it
never inspects an Endpoint policy.

The policy is a directory of small files rather than one file, because different tokens need
different authority on the same machine. One file per token keeps each decision readable, and it
makes adding, changing, listing and revoking a token a single file operation that cannot disturb
another token's authority.

A token file also names the Endpoints that honour it, so one canonical file set can be deployed
across the fleet while each Endpoint applies only the entries that name it. That is what makes
unified maintenance practical: an operator maintains one set of files, not one policy per machine.

## Position in the request path

```text
CLI
  |
  |  HTTP over TLS
  |  server-token + endpoint-token + endpoint_id
  v
Server
  |
  |  verify server-token
  |  verify endpoint_id exists
  |  verify a live channel reaches it
  |
  |  WebSocket over TLS, one live channel
  |  forward unchanged, including endpoint-token
  v
Endpoint
  |
  |  verify endpoint-token
  |  select the policy file for that token
  |  decide whether this operation is permitted
  v
Provider CLI
```

The two hops have different reachability requirements, and that difference decides how a
deployment is wired.

The CLI-to-Server hop is ordinary HTTP, so the CLI's network must be able to reach the
Server. This is the only hop an operator has to arrange, and it is the same requirement as
reaching any HTTP service.

The Server-to-Endpoint hop is one WebSocket, and either side may dial it. The link is
therefore established as soon as one direction works: a machine that cannot be reached
inbound is still manageable because its Endpoint dials out, and a machine that cannot dial
out is still manageable because the Server dials it. Only a machine that can neither dial nor
be dialed is unreachable, and that is a network fact rather than a policy decision.

Three properties follow from this arrangement, and each is deliberate.

The Server cannot grant authority. A caller that the Server accepts still reaches an
Endpoint that may refuse it.

The Server cannot revoke authority. Removing a caller's access is an Endpoint-local edit,
so a compromised or misconfigured Server cannot widen what an Endpoint serves.

The Endpoint cannot be bypassed. Every operation that touches provider state arrives over
the channel, so there is no second path around the policy.

## The two tokens

A CLI presents two independent credentials, and they answer two different questions.

| Token | Verified by | Answers | Failure |
|---|---|---|---|
| `server-token` | Server | May this caller talk to the cluster at all? | `401 unauthorized`, request never reaches an Endpoint |
| `endpoint-token` | Endpoint | May this caller exercise this operation on this machine? | `policy_denied`, no provider work starts |

The `server-token` is cluster admission. It is one credential per deployment today, and it
carries no per-Endpoint meaning. It must never be treated as authority over an Endpoint,
because the Server does not know what an Endpoint serves.

The `endpoint-token` is Endpoint admission. It is provisioned by an operator and stored in the
Endpoint's policy directory, so the Endpoint is the only party that can validate it. The Server
forwards it without interpreting it, exactly as it forwards an opaque provider response.

A request that omits the `endpoint-token` is refused by the Endpoint. It is not treated as
an anonymous caller and it does not fall back to a default policy, because a missing
credential must never be weaker than a wrong one.

The two tokens travel in different places. The `server-token` stays in the HTTP
`Authorization` header, which terminates at the Server. The `endpoint-token` travels inside
the request body and then inside the channel frame, because it must survive past the Server
to reach the Endpoint.

### How each token is carried

The two tokens need different carriage because they terminate at different parties.

| Hop | `server-token` | `endpoint-token` |
|---|---|---|
| CLI to Server | HTTP `Authorization: Bearer <server-token>` | Request body field `endpoint_token` |
| Server to Endpoint | Not forwarded; it terminated at the Server | Channel frame field `endpoint_token`, forwarded verbatim |
| Endpoint to provider | Never present | Never present; it is consumed by the policy check |

The `endpoint-token` must be in the body rather than a header, because the Server
re-emits the request as a channel frame and a header has no place to live there. It
must be in the frame rather than in a Server-side lookup, because the Server holds no
token table and must not acquire one: a Server-side token table would be a second
authority and would let a Server compromise widen access.

The CLI therefore needs two independent settings, and neither may default to the
other. A CLI configured with only a `server-token` can reach the cluster but is
refused by every Endpoint, which is the correct outcome: cluster admission is not
machine admission.

A token may be honoured by one Endpoint or by several, and the file's `endpoints` declaration
decides which. A CLI therefore resolves the token for the Endpoint it addresses from its own
configuration, rather than offering one token to every machine: a token that names one Endpoint is
refused by the others, so sending it everywhere gains nothing and leaks it to machines that should
never see it.

## Policy directory

The policy is a directory of files, and each file describes exactly one token. A token is the
unit of management because a token is the only thing the Endpoint can verify: the caller presents
it, the Endpoint holds it, and nothing else about the caller is provable.

```text
/etc/agent-cluster/endpoint-access.d/
  admin.conf          the operator token, full authority
  gd-dev-cli.conf     the token the gd-dev CLI uses, read-only
  monitor.conf        a monitoring token, output reads only
```

One file per token keeps each decision readable, and it makes every maintenance operation
mechanical: adding a token is adding a file, changing authority is editing one file, revoking a
token is deleting one file, and listing tokens is listing the directory. No operation touches
another token's authority.

The directory is read at startup and reloaded on `SIGHUP`.

The filename is a label for the operator, not the selector. Selection is by the `token` line
inside the file, so renaming a file changes nothing, and the token never appears in a directory
listing. The loader rejects two files that declare the same token, because the effective policy
would otherwise depend on directory read order.

### One file set for the whole fleet

The directory is Endpoint-local, but the files are meant to be identical on every Endpoint. A
token file states which Endpoints honour it, so one canonical set can be deployed fleet-wide and
each Endpoint applies only the entries that name it. This is what makes unified maintenance
practical: an operator edits one file set and distributes it, instead of maintaining a different
policy on every machine.

An Endpoint that is not named in a file's `endpoints` line refuses that token, so deploying a
file everywhere does not grant access everywhere.

### The three states

| State | How it is expressed | Effect |
|---|---|---|
| Permissive | The directory is not configured | Every caller may exercise every operation on every Endpoint |
| Restrictive | The directory contains one or more token files | Only the listed tokens, only their listed Endpoints, scopes and permissions |
| Denying | A token file declares `deny-all` | That token may exercise no operation anywhere |

Permissive is the default so an existing deployment keeps working after an upgrade. A missing
directory is not an error and must never be reported as one.

Denying is expressed per token, not per directory. A file that says `deny-all` refuses that token
while leaving every other token untouched. To refuse everyone, every token file says `deny-all`.

A configured directory with no file matching the presented token refuses that caller. The
directory is restrictive once it exists, so an unlisted token is not silently permissive:
otherwise adding one token file would leave every other caller with full authority, which is the
opposite of what an operator writing a policy intends. This is the one case where the default
flips, and it flips because the operator has stated an intent by creating the directory at all.

An empty token file is rejected at load time. A truncated or accidentally emptied file must not
silently disable a token, so the intent has to be stated with `deny-all` or `allow-all`. This
mirrors the `allow-empty` directive in the command allowlist.

## File format

The format is line-based text, matching `command-allowlist.conf` so an operator learns one style
rather than two. A file declares one token and then the three things that token may do.

```text
# /etc/agent-cluster/endpoint-access.d/gd-dev-cli.conf
#
# One token. Read at startup and reloaded on SIGHUP.

token gd-dev-cli-7f3a9c2e

endpoints gd-dev
scopes read_output
permissions output.read output.follow
```

A token that may do everything on every Endpoint:

```text
# /etc/agent-cluster/endpoint-access.d/admin.conf
token admin-4b8e1d05
allow-all
```

A token that is revoked:

```text
# /etc/agent-cluster/endpoint-access.d/revoked.conf
token old-laptop-c91f7a44
deny-all
```

A token honoured on two Endpoints, with one scope plus one operation outside that scope:

```text
# /etc/agent-cluster/endpoint-access.d/monitor.conf
token monitor-2d6b8f13

endpoints gd-dev topsailai-dev
scopes read_output
permissions agent.model.list
```

### The three declarations

| Declaration | Meaning | Absent means |
|---|---|---|
| `endpoints <id...>` | The Endpoints that honour this token | Every Endpoint that holds the file |
| `scopes <name...>` | Capability classes granted, using the five operator scope names | No scope is granted |
| `permissions <op...>` | Individual operations granted, by name | No individual operation is granted |

`scopes` and `permissions` are both grants, and they combine by union: the token may exercise
every operation its scopes cover and every operation its permissions name. Neither narrows the
other, so adding a line can only add authority and never silently remove it. A file that grants
nothing is therefore a file with neither line, which is why an empty file is rejected rather than
read as "nothing granted".

The two levels exist because they answer different questions. A scope is a stable class an
operator reasons about, so `scopes read_output` survives the addition of a new read operation. A
permission is one exact operation, so `permissions output.follow` grants a tail without granting
a snapshot. Granting a class and granting one member of it are both legitimate, and forcing an
operator to enumerate every member of a class would make the common case verbose.

`endpoints` is the one declaration that narrows rather than grants. It restricts where the token
is accepted, so it can only reduce what the token reaches. A file without it is honoured by every
Endpoint that holds the file, which is the convenient default for a token meant to be fleet-wide;
a file with it is honoured only where it names.

### Parsing rules

- A blank line and a line starting with `#` are ignored.
- Exactly one `token` line is required, and it must appear before any declaration.
- `token <value>` declares the token in plain text.
- `token-sha256 <hex>` declares the SHA-256 of the token instead, so the file does not contain
  the secret. Either form identifies the token; a file may not use both.
- `endpoints`, `scopes` and `permissions` may each appear at most once.
- `allow-all` alone accepts every operation on every Endpoint for this token.
- `deny-all` alone refuses every operation for this token.
- `allow-all` and `deny-all` may not be combined with declarations, because the combination has
  no meaning and would make the effective policy depend on line order.
- A declaration with no value is rejected, because it would read as "this dimension is
  unspecified" while looking like a grant.
- An unknown scope name is rejected at load time, so a typo fails at startup instead of silently
  granting nothing.
- A permission naming a non-`ctl.` operation must be one of the known operation names, so a typo
  fails at startup. A `ctl.` permission is accepted as a pattern, because the action inventory is
  Endpoint-local configuration and may legitimately name an action this build does not know.
- A control character in a line is rejected.
- Two files declaring the same token are rejected, because the effective policy would depend on
  directory read order.

### Operation patterns

| Pattern | Matches |
|---|---|
| `output.read` | Exactly that operation |
| `ctl.*` | Every operation whose name starts with `ctl.` |
| `*` | Every operation, or every scope, depending on the declaration it appears in |

A trailing `.*` is a prefix match on the operation name. A bare `*` is a whole-dimension match.
There is no other wildcard form, because a general glob would make the effective policy hard to
read.

## Caller identity and the dimension question

A policy file is selected by the token the caller presents. The token is the only dimension that
can identify a caller, because it is the only thing the Endpoint can verify: the caller presents
it, the Endpoint holds it, and nothing else about the caller is provable.

Two candidate dimensions were considered for selecting a file.

| Dimension | Verifiable | Why it is or is not used |
|---|---|---|
| Caller token | Yes, the Endpoint holds the secret | Used. The Endpoint can prove the caller holds the token |
| Caller Endpoint ID | No, the caller asserts it | Not used. A caller can claim any ID, so a policy keyed on it would be advisory |

The "other Endpoint" dimension deserves a direct answer, because it is the natural way an operator
thinks about a fleet: this machine should accept work from that machine. It cannot select a file,
because the caller's own Endpoint ID is a claim the caller makes about itself and the Endpoint has
no way to check it. A caller that wanted more authority would simply claim a more privileged ID.

The `endpoints` declaration is a different thing, and it is verifiable. It does not describe where
the caller claims to be; it names the Endpoints that honour the token. The Endpoint reading the
file knows its own identity, so it can check the list against itself without trusting anything the
caller said. A token file that says `endpoints gd-dev` is refused by every other Endpoint, and no
claim by the caller can change that.

This is why the fleet dimension lives inside the token file rather than beside it. The token
answers "who is calling", which only the Endpoint can verify, and `endpoints` answers "may this
token be used here", which the Endpoint can also verify because it knows where it is. Both
conditions are checked locally against facts the Endpoint holds, so neither depends on a caller's
assertion.

The earlier design could not distinguish callers at all, because the Server overwrote the issuer
on every intent and the Endpoint received one constant value. A caller-held token removes that
limitation without requiring any Server-side authorization change, because the Server no longer
authorizes operations at all.

## Scope vocabulary

The policy reuses the five operator scopes the Server already defines
(`internal/security/scopes.go:14-18`), so an operator does not learn a second vocabulary.

| Scope | Meaning on the Endpoint |
|---|---|
| `view` | Read this Endpoint's inventory, sessions, history and launch catalog |
| `read_output` | Read session output, as a snapshot or as a follow stream |
| `send_message` | Submit user input or side context to a session |
| `control` | Lifecycle, drive, provider control and allowlisted command execution |
| `endpoint_admin` | Reserved; no Endpoint operation currently requires it |

The vocabulary is shared, but the meaning is not. On the Server a scope described what an
operator could submit. On the Endpoint a scope describes what this machine will serve to this
caller. The Server no longer evaluates these scopes, so the Endpoint is their only consumer.

## Operation inventory and enforcement points

The policy must cover every operation an Endpoint can serve. The operations split into two
groups, because they reach the Endpoint through different code paths.

### Operations already passing one hook

These are submitted as an immutable intent and already pass `PolicyHook`
(`internal/endpoint/executor.go:26-30`, invoked at `:138-140`).

| Operation | Scope | Notes |
|---|---|---|
| `message.send` | `send_message` | Delivery only, never consumption |
| `context.inject` | `send_message` | Side context, distinct from user input |
| `execution.interrupt` | `control` | Advertised only when the semantics are defined |
| `agent.start` | `control` | |
| `agent.resume` | `control` | |
| `agent.stop` | `control` | |
| `agent.drive.start` | `control` | |
| `agent.drive.stop` | `control` | |
| `agent.model.select` | `control` | Switches one session to a model profile |
| `command.exec` | `control` | Also gated by the command allowlist |
| `ctl.<action>` | `control` | One advertised action per capability |

### Operations that bypass every hook today

These arrive as their own frame type and are served directly by the Endpoint service. They
are the gap this policy has to close, because they are exactly the operations that reveal what
an Endpoint is doing.

| Operation | Scope | Current entry point | Today |
|---|---|---|---|
| `output.read` | `read_output` | `internal/endpoint/service.go:415` `outputFrame` | No policy check |
| `output.follow` | `read_output` | `internal/endpoint/follow.go:22` `startFollow` | No policy check |
| `agent.model.list` | `view` | `internal/endpoint/model.go:45` `modelCatalogFrame` | No policy check |
| `launch.query` | `view` | `internal/endpoint/launch.go:56` `launchFrame` | No policy check |
| `history.read` | `view` | `internal/endpoint/history.go:42` `historyFrame` | No policy check |
| `messages.read` | `view` | `internal/endpoint/messages.go:43` `messagesFrame` | No policy check |

`agent.model.list` already has an operation constant
(`internal/protocol/capabilities.go:28`), but it is served by its own frame
(`channel.FrameModelCatalogRequest`) rather than as an immutable intent, so it never reaches
`PolicyHook`. The policy therefore has to check it at the frame handler.

`launch.query`, `history.read` and `messages.read` are frame-level queries without an existing
operation constant. The policy needs a stable name for each, so these three names are
introduced here. They are policy identifiers, not new protocol operations, and they do not
appear on the wire.

### What the policy does not gate

Four Endpoint activities stay outside the policy, and each exclusion is deliberate.

Inventory collection and publication stay outside, because an Endpoint reports its own state
and denying that would make it invisible rather than restricted. The Server would then lose
the ability to show why it is restricted.

Heartbeat and channel liveness stay outside, because they keep the connection alive and carry
no operator intent.

Command receipt delivery stays outside, because a receipt answers a command the Endpoint
already accepted, and suppressing it would leave the Server waiting forever.

The fleet list and the session list stay outside, because a caller may see which machines and
sessions exist. Only the detail reads and the operations are gated. This is a deliberate
boundary: knowing that a session exists is not the same as reading what it said.

A `deny-all` caller therefore still sees the fleet and still sees that sessions exist. It
simply cannot read their content and cannot operate them.

## Enforcement semantics

A denied operation is rejected before any provider work starts, and the rejection is reported
as a refusal rather than as a failure.

- A denied intent is rejected in `PolicyHook`, which runs before the journal records an
  invocation. A rejection recorded after that point would be indistinguishable from a crash
  mid-invocation and would surface as a false `unknown` effect for a command that was never
  applied.
- A denied read returns the operation's existing response shape with a distinct code, so the
  operator can tell "this Endpoint refuses to show output" from "this Endpoint cannot show
  output". The two conditions have different remedies and must not share a code.
- A denied operation never reaches an adapter, never starts a child process and never reads a
  provider file.
- The policy is checked on every request, not once per connection, because a reload must take
  effect without reconnecting.
- An unknown or missing token is refused with the same code as a denied operation, so a caller
  cannot probe which tokens exist by comparing responses.

## Reload

The directory reloads on `SIGHUP`, using the same mechanism as the command allowlist
(`internal/endpoint/allowlist_file.go:59-86`).

- The whole directory is parsed completely before the swap, so a broken edit keeps the
  previous policy in force.
- A parse failure is logged at ERROR with the file path and the failing line, and the previous
  policy stays active.
- A reload never leaves an empty or partially applied policy in force.
- `SIGHUP` is registered explicitly, because Go terminates a process on `SIGHUP` by default and
  an unregistered handler would kill the Endpoint instead of reloading it.

Startup behaves differently from reload, and the difference is intentional. A configured
directory that is missing, unreadable or invalid fails startup, because an operator who pointed
the Endpoint at a policy directory expects that policy to be in force. A reload failure keeps
the previous policy, because the Endpoint is already serving and dropping to a default would be
worse than keeping the last known good policy.

## Relationship to the command allowlist and the control catalog

Three Endpoint-local surfaces answer three different questions, and all apply.

| Surface | Question | Default when absent |
|---|---|---|
| Endpoint access policy directory | May this caller exercise this operation on this machine? | Every caller, every operation |
| Command allowlist | May this argv array run? | No command runs |
| Control action catalog | Is this provider control action configured? | No control action is available |

A `command.exec` request passes all three: the caller's policy must permit the operation, the
allowlist must permit the argv array, and the operation must be advertised. A `ctl.<action>`
request passes two: the caller's policy must permit the operation and the catalog must define
the action.

The defaults differ deliberately. The access policy fails open when absent, because an Endpoint
that refused every caller by default would break every existing deployment on upgrade. The
allowlist and the catalog fail closed when absent, because they decide which concrete program
runs, and an unconfigured surface there would execute something nobody chose.

## What changes on the Server

The Server stops authorizing operations. Five existing checks are removed.

| Surface | Current check | After |
|---|---|---|
| Command admission | Caller scope must cover the operation | Removed; the Endpoint decides |
| Output read | Caller must hold `read_output` | Removed; the Endpoint decides |
| Messages read | Caller must hold `read_output` | Removed; the Endpoint decides |
| History read | Caller must hold `view` | Removed; the Endpoint decides |
| Model catalog read | Caller must hold `view` | Removed; the Endpoint decides |

The Server keeps three checks, and they are all about reachability rather than permission.

| Check | Question | Failure |
|---|---|---|
| Caller authentication | Does the caller hold the `server-token`? | `401 unauthorized` |
| Endpoint existence | Has this `endpoint_id` ever registered? | `404 endpoint_not_found` |
| Channel liveness | Is there a live channel to it now? | `503 endpoint_offline` |

Endpoint existence and channel liveness must be reported separately. Today both surface as one
offline error, so a caller cannot tell a typo in an Endpoint ID from a machine that is merely
disconnected. A router that cannot distinguish "no such address" from "address unreachable" has
not verified the address.

The Server also stops reading an operation's declared permission from the reported inventory
for authorization. That field remains descriptive report data, and the Endpoint is its only
consumer.

Two implemented-contract documents still describe the current Server-side checks and must be
updated in the same change that removes them: `docs/API.md` states that command admission
authorizes an operation against the caller's scopes, and `docs/Environment_Variables.md`
documents `AGENT_CLUSTER_AUTH_SCOPES` as an authorization control. They are left unchanged here
because they describe behaviour that exists in the code today, and a design draft must not claim
a change that has not been made.

## What changes on the wire and in the CLI

The dual-token model is not a Server-only change. The `endpoint-token` has to reach the
Endpoint, so it must exist on the wire, and the CLI must be able to supply it.

| Surface | Change | Why it is required |
|---|---|---|
| Channel frame | A new `endpoint_token` field | The Endpoint cannot verify a credential it never receives |
| Immutable intent | A new `endpoint_token` field | Every command already travels as an intent, so the token rides with it |
| Six read request structures | A new `endpoint_token` field each | These bypass the intent path and carry their own request shape |
| CLI | A new `--endpoint-token` flag and a per-Endpoint token map | A token names its Endpoints, so the CLI resolves the one for the addressed Endpoint |
| Server handlers | Forward the field verbatim | The Server must not drop or rewrite it |

The field is deliberately a plain string and not a structured credential. The Server
must be able to forward it without understanding it, and a structured value would invite
Server-side interpretation, which is exactly the authority this design removes.

The six read responses already carry an `ErrorCode` field, so a refusal needs no new
response shape. Only the request side grows.

## Boundaries and limits

| Boundary | Consequence |
|---|---|
| A token is a bearer secret | Anyone holding it has that token's authority. Rotation is an Endpoint-local edit plus a CLI configuration change |
| The fleet and session lists are not gated | A caller learns which machines and sessions exist, but not what they said |
| The Server forwards the token without interpreting it | The Server cannot audit which token reached which Endpoint, only which request did |
| A policy edit takes effect on reload, not instantly | The window is one `SIGHUP` |
| `endpoints` is checked against the Endpoint's own identity | It decides where a token is honoured, but it cannot prove where a request came from |
| The Endpoint is the only authority | A caller refused by an Endpoint has no second path, and a Server compromise cannot widen access |

The first boundary is the important one. A token is a bearer credential, so its authority is
exactly what the file grants and nothing more. It is not a signature and it does not prove which
machine sent it. An operator who needs machine-bound authority needs a client certificate, which
is a different mechanism and is out of scope here.

The `endpoints` boundary follows from the same fact. Because a request carries no proof of origin,
`endpoints` restricts where a token is accepted rather than where a request came from. That is
still the useful half: a token meant for one machine is refused by the others, so a copied token
does not silently work fleet-wide.

## Token provisioning and maintenance

Tokens are provisioned by an operator, not issued by the Endpoint or the Server. The Endpoint only
reads the files it is given, so there is no issuance path to build, no token registry to keep
consistent, and no way for a Server compromise to mint a credential.

Because the files are plain text and one file is one token, every maintenance operation is a file
operation. A script wraps them so an operator does not hand-edit files and so the fleet stays
consistent:

| Operation | Effect |
|---|---|
| `add <token-name> --endpoints <id...> --scopes <name...> --permissions <op...>` | Create one token file with a freshly generated secret |
| `list` | Show every token, its Endpoints, scopes and permissions, without printing secrets |
| `show <token-name>` | Show one token file's effective grants |
| `set <token-name> ...` | Replace one declaration on an existing token file |
| `remove <token-name>` | Delete one token file |
| `rotate <token-name>` | Replace the secret in one file and print the new value once |

The script is the recommended path but not a privileged one: it edits the same files an operator
could edit by hand, so a deployment without the script is fully supported. It must never print a
secret except on `add` and `rotate`, because a listing that prints secrets turns every terminal
scrollback and log into a credential leak.

Two properties keep the script safe to run against a live fleet. It writes a file atomically, so a
reader never observes a half-written policy. And it does not signal the Endpoint itself: the
operator reloads on `SIGHUP` as with any other policy edit, so a script run cannot silently change
what a running Endpoint serves without the operator knowing a reload happened.

## Open questions

- Should a denied read return a distinct code per operation, or one shared `policy_denied` code
  with the operation named in the message?
- Should the policy directory be a conffile in the config package, so an upgrade keeps a site's
  policy instead of replacing it? The command allowlist is already a conffile, so consistency
  argues yes.
- Should `endpoint_admin` be removed from the vocabulary until an operation needs it, or kept so
  the file format does not change later?
- Should a `permissions` entry be allowed to name an operation the Endpoint does not serve? The
  current proposal accepts it, so a policy can be written before the operation ships, but it also
  means a typo in a non-`ctl.` name is the only thing load-time validation can catch.
- Should the token script live in `scripts/` beside `agent-clusterctl`, or be a subcommand of the
  Endpoint binary so it ships with the package that owns the format?
- How does a CLI obtain the token for each Endpoint it addresses? Provisioning is settled: the
  operator creates tokens and a script maintains them. What remains open is distribution to the
  CLI, where a local per-Endpoint map is simple but hand-maintained, and a Server-side path would
  make the Server a token holder, which this design deliberately avoids.
