---
maintainer: AI
author: DawsonLin
---

# Adversarial Cases: Node Authority

The Node is the only authority for permissions. These cases attack that authority
from every direction that is not the path fence: a caller trying to reach a scope
it was not given, a caller trying to obtain a permission it was not granted, a
Server trying to speak for the Node, and a policy file trying to grant more than
its author intended.

The path fence has its own file. A case belongs here when the interesting failure
is "the Node decided wrongly", not "the Node resolved a path wrongly".

## Reaching a scope that was not given

### AC-NODE-1: Guess a scope name

**Precondition:** A policy defining `project` only.

**Action:** Send requests for `scratch`, `tool`, `home`, `root`, `tmp`, `etc` and
`private` in turn.

**Expected:** Every one is `denied`. A guessed name is not a scope, and the
refusal is identical for every guess so the responses do not reveal which names
exist.

### AC-NODE-2: Enumerate scope names by timing

**Precondition:** A policy defining one scope.

**Action:** Send a defined scope and an undefined scope, and compare response times
over many samples.

**Expected:** The two are indistinguishable. A lookup that returns early on a miss
turns the scope list into something a caller can enumerate by measuring.

### AC-NODE-3: Enumerate scope names by error text

**Action:** Send a defined scope with no grant and an undefined scope, and compare the
two responses.

**Expected:** Both are `denied` with the same message. Distinguishing "no such
scope" from "no grant on that scope" tells a caller which names exist.

### AC-NODE-4: Use a scope name that is a path

**Action:** Send `scope: /home/me/project`.

**Expected:** `invalid_argument`. A path is not a name, so it is refused before the
policy is consulted.

### AC-NODE-5: Use a scope name with a traversal

**Action:** Send `scope: ../project`.

**Expected:** `invalid_argument`.

### AC-NODE-6: Use a scope name with an encoded separator

**Action:** Send `scope: project%2f..%2foutside`.

**Expected:** `invalid_argument`. The name is not decoded, because decoding would turn
a refused name into an accepted one.

### AC-NODE-7: Use a scope name with a NUL byte

**Action:** Send `scope: project\x00scratch`.

**Expected:** `invalid_argument`. A NUL byte truncates a name in some filesystem
calls, so a name containing one is not a name.

### AC-NODE-8: Use a scope name with a newline

**Action:** Send `scope: project\nscratch`.

**Expected:** `invalid_argument`. A newline in a name is a log-injection vector as
well as a malformed name.

### AC-NODE-9: Use a scope name that differs only in case

**Action:** Send `scope: PROJECT` when the policy defines `project`.

**Expected:** `denied`. A case-insensitive match would make the policy mean one
thing on Windows and another on Linux.

### AC-NODE-10: Use a scope name with a trailing dot

**Action:** Send `scope: project.`.

**Expected:** `invalid_argument`. On Windows a trailing dot is stripped by the
filesystem, so the name would address a different scope than the one written.

### AC-NODE-11: Use a scope name with a trailing space

**Action:** Send `scope: project `.

**Expected:** `invalid_argument`. Trimming would make two wire values address one
scope, so the name is refused rather than repaired.

### AC-NODE-12: Use a scope name that is a Windows reserved device name

**Action:** Send `scope: CON` when the policy defines `con`.

**Expected:** `denied` or `invalid_argument`. A reserved device name is not a
directory, so it cannot be a scope even if the policy names it.

### AC-NODE-13: Use a scope name longer than the filesystem allows

**Action:** Send a scope name of 5000 characters.

**Expected:** `invalid_argument`. A name that cannot be a directory name is refused
before it reaches a filesystem call.

### AC-NODE-14: Reuse a scope name from another Node

**Precondition:** Node A defines `project`, Node B defines `scratch`.

**Action:** Send `scope: project` to Node B.

**Expected:** `denied`. A scope name is local to a Node, so a name that works
elsewhere does not work here.

## Obtaining a permission that was not granted

### AC-NODE-15: Ask for a stronger permission on a granted scope

**Precondition:** `project: [list]`.

**Action:** Send `file.read` on `project`.

**Expected:** `denied`. `list` is not a weaker `read`, so holding one does not
imply the other.

### AC-NODE-16: Ask for a permission granted on a different scope

**Precondition:** `project: [read]`, `scratch: [list]`.

**Action:** Send `file.read` on `scratch`.

**Expected:** `denied`. A grant is a pair, so a permission held elsewhere is not
held here.

### AC-NODE-17: Ask for a permission by naming it in the request

**Action:** Send a request with a `permissions: ["read"]` field.

**Expected:** `invalid_argument`. The request schema has no permission field, because
a caller does not get to state what it is allowed to do.

### AC-NODE-18: Ask for a permission by naming a role

**Action:** Send a request with `role: admin`.

**Expected:** `invalid_argument` or `denied`. There is no role vocabulary, so a
role claim is an unknown field rather than a privilege.

### AC-NODE-19: Ask for a permission by naming a subject

**Action:** Send a request with `subject: root`.

**Expected:** `invalid_argument`. The decision depends on the node proof and the
policy, not on a name the caller supplies. A request carrying a field no enabled
operation uses is refused rather than ignored, so a `subject` claim cannot be smuggled
in beside a legitimate request.

### AC-NODE-20: Ask for an operation that is not implemented

**Precondition:** `project: [write, exec]`.

**Action:** Send `file.write` and `command.exec`.

**Expected:** `unsupported_operation` for both. A grant cannot create an
implementation, so a policy that grants a future operation does not enable it.

### AC-NODE-21: Ask for an operation by an alias

**Action:** Send `operation: read` instead of `file.read`.

**Expected:** `unsupported_operation`. An alias would be a second name for one
operation, and a policy reviewer would have to know both.

### AC-NODE-22: Ask for an operation with a case variation

**Action:** Send `operation: FILE.READ`.

**Expected:** `unsupported_operation`. Operation names are exact, so a case variation
is a different name.

### AC-NODE-23: Ask for an operation with a path suffix

**Action:** Send `operation: file.read/../../write`.

**Expected:** `unsupported_operation`. An operation name is an identifier, never a
path.

### AC-NODE-24: Ask for an operation with an empty name

**Action:** Send `operation: ""`.

**Expected:** `invalid_argument`.

### AC-NODE-25: Ask for two operations in one request

**Action:** Send `operation: file.list` with a second operation field.

**Expected:** `invalid_argument`. One request is one operation, so a request cannot
smuggle a second one past the check.

### AC-NODE-26: Ask for a permission by sending a batch

**Action:** Send a request containing an array of operations, one granted and one not.

**Expected:** `invalid_argument`, or the whole batch is refused. A batch that
partially succeeds would let a caller learn which element was refused and would make
the audit record ambiguous.

### AC-NODE-27: Ask for a permission on a scope defined after the request was built

**Precondition:** A policy without `scratch`.

**Action:** Build a request for `scratch`, add the scope to the policy, reload, then
send the request.

**Expected:** The request succeeds if the reload happened before the request arrived,
and is refused otherwise. The decision is made when the request is evaluated, not
when it was built.

## Making the Server speak for the Node

### AC-NODE-28: A compromised Server invents a scope

**Action:** Modify the Server to append a scope to the forwarded request.

**Expected:** `denied`. The Node's policy is the only scope list.

### AC-NODE-29: A compromised Server invents a grant

**Action:** Modify the Server to add an approval field to the forwarded request.

**Expected:** `invalid_argument` or `denied`. The Node's schema has no approval
field, so an unknown field is refused rather than ignored.

### AC-NODE-30: A compromised Server rewrites the operation

**Action:** Modify the Server to change `file.list` into `file.read`.

**Expected:** `denied`. The rewritten operation is checked against the same
grant, and the grant does not cover it.

### AC-NODE-31: A compromised Server rewrites the scope

**Action:** Modify the Server to change `scratch` into `project`.

**Expected:** `denied` if `project` lacks the permission, and a successful read
of `project` if it has it. This case is expected to succeed when the grant exists,
and that is the honest result: the Server is a pipe, so it can send any request a
caller could have sent. What it cannot do is make the Node grant something the policy
does not.

**Why this case is written this way:** a case that expected a refusal here would be
testing a property the design does not claim. The design claims the Server cannot
widen authority, not that it cannot relay a request.

### AC-NODE-32: A compromised Server replays a captured request

**Action:** Capture a valid request and replay it byte for byte within the replay
window.

**Expected:** `unauthenticated`, with the reason `authentication proof was already
used`. The nonce is recorded only after the signature verifies, so the first request
reserves it and the replay finds it taken. The replay cache is per `key_id`, so a
replay of one caller's request cannot be laundered through another caller's nonce
space.

**Why this case is written this way:** the earlier version of this case expected the
replay to succeed, because a shared secret with no nonce has nothing to distinguish
two identical requests. That was the accepted cost of the shared-secret model, and the
HMAC model removes it. A case that still expected success would direct a future change
to delete the replay cache, so the expectation is inverted here rather than softened.

**What is still not covered:** a replay that arrives before the original. The nonce is
recorded when the first request is admitted, so two copies racing each other can both
pass if they are verified before either is recorded. That window is bounded by the
verification path and is stated in `AdversarialCase_secrets.md` rather than claimed
here as closed.

### AC-NODE-33: A compromised Server claims a Node is offline

**Action:** Modify the Server to report a refusal without forwarding.

**Expected:** The caller sees a refusal. The Server can deny service, which the design
states plainly; it cannot cause an operation.

### AC-NODE-34: A compromised Server forges a response

**Action:** Modify the Server to return a fabricated success without forwarding.

**Expected:** The caller receives a success with no data, or a response that fails
validation. This is a real residual risk: a caller that trusts the Server's word
cannot distinguish a fabricated response from a real one. The mitigation is that the
Server never holds the data it would have to fabricate convincingly, and the case is
recorded so the risk is not forgotten.

### AC-NODE-35: A compromised Server drops the node proof

**Action:** Modify the Server to forward a request with an empty `NodeAuth`.

**Expected:** `unauthenticated`. A missing proof is a refusal, not an anonymous
request. The Node answers `unauthenticated` rather than `denied` because the caller
never proved it may talk to this Node at all, which is a different answer from "you
may talk to this Node but not do that".

### AC-NODE-36: A compromised Server substitutes its own client credential

**Action:** Modify the Server to forward a request whose `NodeAuth` carries the
Server's own client `key_id` and a signature the Server can compute.

**Expected:** `unauthenticated`. The Node looks the `key_id` up in its own credential
set, and the Server's key id is not there, so the lookup fails before any signature is
checked. The two credential namespaces are separate: a Server credential is not a Node
credential even when both use the same `key_id.secret` shape.

### AC-NODE-37: A compromised Server asks the Node to reveal its policy

**Action:** Send an operation that would return the policy file.

**Expected:** `unsupported_operation` or `denied`. There is no operation that
reads the policy, and the config directory is refused as a scope at startup.

### AC-NODE-38: A compromised Server asks the Node to regenerate its identity

**Action:** Send a control frame requesting regeneration.

**Expected:** The frame is refused as unknown. The Server cannot force a credential
change, because a Server that could would also be able to force a denial of service.

## Attacking the policy file

### AC-NODE-39: A policy that grants everything by wildcard

**Action:** Write `project: ["*"]` and start the Node.

**Expected:** Startup fails. A wildcard is not a permission, and a policy that grants
everything by one character is a policy nobody reviews.

### AC-NODE-40: A policy that grants everything by an empty scope name

**Action:** Write a scope named `""` with `[read]`.

**Expected:** Startup fails. An empty name is a missing name.

### AC-NODE-41: A policy that grants everything by a scope named `..`

**Action:** Write a scope named `..` with `[read]`.

**Expected:** Startup fails. A scope name is an identifier, so a traversal is refused.

### AC-NODE-42: A policy that grants everything by a scope named `/`

**Action:** Write a scope named `/` with `[read]`.

**Expected:** Startup fails.

### AC-NODE-43: A policy with an unknown key that looks like a grant

**Action:** Add `allow_all: true` at the top level.

**Expected:** Startup fails. A typo in a security config that is silently ignored is
worse than a crash, and `allow_all` is exactly the key an operator would try.

### AC-NODE-44: A policy with a grant on an undefined scope

**Action:** Grant `read` on `unknown`.

**Expected:** Startup fails. A typo would otherwise look like a working policy.

### AC-NODE-45: A policy with a duplicate scope name

**Action:** Define `project` twice with different paths.

**Expected:** Startup fails, or the last definition wins with a warning. An ambiguous
policy is one nobody can review, and the ambiguity is exactly where a hidden grant
would live.

### AC-NODE-46: A policy with a scope pointing at the config directory

**Action:** Set a scope path to the Node's config directory.

**Expected:** Startup fails with
`scope "project": path "<config>" overlaps the Node's config directory "<config>"; a scope that can list its own credentials is a configuration mistake`.
A scope that can list its own credential files discloses their names and sizes even
when their contents are denied, so the refusal is at startup rather than per request.

### AC-NODE-47: A policy with a scope containing the config directory

**Action:** Set a scope path to a directory that contains the config directory.

**Expected:** Startup fails with the same message. The comparison is on path
components rather than on a string prefix, so a sibling named `config-backup` is not
mistaken for a child of `config`.

**Exception:** with `allow_filesystem_root: true` the overlap refusal is relaxed,
because a scope rooted at a volume necessarily contains the config directory. The
deny list then carries the protection: the directory and everything inside it are
refused, and a listing omits the entry. AC-PATH-64 measures that state.

### AC-NODE-48: A policy with a scope pointing at `/`

**Action:** Set `path: /`.

**Expected:** Startup fails. The blast radius is the whole machine. The one
exception is a policy that states `allow_filesystem_root: true`, which is the
operator writing that blast radius down on purpose. See AC-NODE-66.

### AC-NODE-49: A policy with a scope pointing at a mount point

**Action:** Set `path` to a mount point.

**Expected:** Startup fails. A scope containing a bind mount to `/` is readable
through the fence, so a mount root is refused.

### AC-NODE-50: A policy replaced by a symlink

**Action:** Replace the policy file with a symlink to a different file.

**Expected:** Startup fails, or the link is refused. A policy that can be redirected
is a policy whose content is not the content that was reviewed.

### AC-NODE-51: A policy that grows a grant between review and reload

**Action:** Review a policy, then add a grant, then send `SIGHUP`.

**Expected:** The new grant takes effect and the change is logged. The case exists
because a reload is the moment a reviewed policy can become an unreviewed one, so the
log entry is the control.

### AC-NODE-52: A policy reload that fails open

**Action:** Replace the policy with an unreadable file, send `SIGHUP`.

**Expected:** The previous policy stays in force and the failure is logged. A reload
that failed open would be a reload that removed the authority.

### AC-NODE-53: A policy file readable by another user

**Precondition:** The policy file is `0644`.

**Action:** Start the Node.

**Expected:** Startup succeeds. The policy contains no secret, so a group-readable
policy is not a leak. Refusing it would train an operator to loosen permissions on the
file that does hold a secret.

### AC-NODE-54: A config directory readable by another user

**Precondition:** The config directory is `0755`; `identity` and `credentials.yaml`
are `0600`.

**Action:** Start the Node.

**Expected:** Startup succeeds. The directory mode is not checked, because the
directory holds no secret of its own: the two files inside it are checked
individually, and each refuses startup when a group or other user can read it.
Measured on Linux: a `0755` config directory holding a `0600` identity and a `0600`
credential file reached `connector-node ready`.

**Why the check is on the files rather than the directory:** a directory mode is
inherited by nothing and grants nothing by itself. Refusing a `0755` directory would
refuse a layout that discloses nothing, while a `0600` file inside a `0755` directory
is still unreadable to another user. The check that changes the outcome is the one on
the file.

### AC-NODE-54b: A credential file readable by another user

**Precondition:** The config directory is `0700`; `credentials.yaml` is `0644`.

**Action:** Start the Node.

**Expected:** Startup fails with
`credential file "<path>" has mode 0644, want no group or other access; it holds secrets that never expire`.
Measured on Linux. The message names the file and the mode, so the operator can fix
it without guessing which of the two files is wrong.

## Attacking the decision by racing it

### AC-NODE-55: Change the policy between authorization and the read

**Precondition:** `project: [read]`.

**Action:** Send a read, and remove the grant while the read is in progress.

**Expected:** The in-flight read completes under the policy it was authorized against.
A request is authorized once, so a mid-flight change cannot revoke a decision already
made, and cannot widen one either.

### AC-NODE-56: Change a scope's directory between authorization and the read

**Precondition:** A scope at `<tmp>/scope`.

**Action:** Replace the directory with a symlink to `/etc` while a read is in progress.

**Expected:** The read either completes from the original directory or fails. The
`os.Root` handle references the directory that was validated, so the replacement does
not become the scope.

### AC-NODE-57: Send many requests while a reload is in progress

**Action:** Send a stream of requests while sending `SIGHUP` repeatedly.

**Expected:** Every request is decided under exactly one policy version, and no
request is decided under a half-loaded policy. A policy that is swapped field by field
would have a window where a grant is absent and a window where it is present twice.

### AC-NODE-58: Send a request during startup before the policy is loaded

**Action:** Connect and send a request as soon as the port accepts.

**Expected:** The request is refused or the connection is not accepted until the policy
is loaded. A Node that serves before its policy is loaded serves under no policy.

### AC-NODE-59: Send a request during shutdown

**Action:** Send a request while the Node is shutting down.

**Expected:** The request is refused or completed, never half-completed. A shutdown
that abandons a read mid-response leaves the caller unable to tell a refusal from a
truncation.

## Attacking the audit trail

### AC-NODE-60: Inject a newline into a logged field

**Action:** Send `scope: project\nfake audit entry: granted`.

**Expected:** `invalid_argument`, and the log contains one entry with the newline
escaped. A newline in a logged field is a forged audit record.

### AC-NODE-61: Inject a control sequence into a logged field

**Action:** Send a path containing an ANSI escape sequence.

**Expected:** The sequence is escaped in the log. A terminal that renders the escape
shows a log entry the operator did not receive.

### AC-NODE-62: Make the log grow without bound

**Action:** Send a large number of refused requests.

**Expected:** The log rotates at its configured size and old files are retired. An
unbounded log is a disk-filling denial of service that the refusal path itself enables.

### AC-NODE-63: Trigger a refusal that logs a credential secret

**Action:** Send a node proof whose signature does not verify, then search every log,
trace and error message for the secret.

**Expected:** The secret appears nowhere. The `node-id` and the `key_id` may appear,
because both are public: the `node-id` is an address and the `key_id` names which
credential was presented. Measured: a refusal logs
`msg="connector-node refused a node proof" node_id=… node_key_id=… reason="signature does not verify"`,
which names the credential without disclosing it.

### AC-NODE-64: Trigger a refusal that logs an absolute path

**Action:** Send a request that fails the fence, then read the log.

**Expected:** The log names the scope and the relative path, never the resolved
absolute path. An absolute path in a log is a filesystem layout leak.

### AC-NODE-65: Distinguish refusal reasons from the response

**Action:** Trigger the token, scope, permission and fence refusals, and compare the
four responses.

**Expected:** The token refusal is indistinguishable from the scope refusal. The
permission and fence refusals may differ, because a caller that has already
authenticated is not being told anything it could not learn by trying. The distinction
is deliberate: an unauthenticated caller learns nothing, an authenticated one learns
why its own request failed.

## The filesystem-root opt-in

### AC-NODE-66: An opted-in volume root still cannot read the Node's credentials

**Precondition:** A policy with `allow_filesystem_root: true` and a scope rooted at
a volume. The Node's config directory sits inside that volume.

**Action:** `file.read` on the config directory's relative path, on `identity`, on
`policy.yaml` and on `tunnel_token`, and `file.list` on the scope root.

**Expected:** `denied` for every read, and the listing omits the config directory.
The opt-in is a statement about the blast radius, not a grant: the deny list still
refuses the Node's own files, and the listing still hides them.

**Why this case exists:** the opt-in is the one change that lets a scope contain
the config directory, so it is the one change that could turn a startup refusal
into a credential leak. The case asserts that the protection moved rather than
disappeared.

### AC-NODE-67: The opt-in does not grant a permission

**Precondition:** A policy with `allow_filesystem_root: true`, a scope rooted at a
volume, and no grant for that scope.

**Action:** Send `file.read` on a file inside the volume.

**Expected:** `denied`. The opt-in relaxes a startup refusal about where a scope may
point; it does not add a grant. A scope with no grant still refuses every operation,
so an operator who writes the opt-in and forgets the grant gets a Node that starts
and denies everything rather than one that silently allows everything.

### AC-NODE-68: The opt-in is not inferred from the path

**Precondition:** A policy with a scope rooted at a volume and **no**
`allow_filesystem_root` key.

**Action:** Start the Node.

**Expected:** Startup fails with the filesystem-root refusal. The opt-in is never
inferred from the path being a root, because an inferred opt-in is not an opt-in: a
typo or a copied policy would widen the blast radius without anyone writing it down.

### AC-NODE-69: An unknown key near the opt-in is still refused

**Precondition:** A policy with `allow_filesystem_root: true` and a second key such
as `allow_all: true`.

**Action:** Start the Node.

**Expected:** Startup fails. Decoding is strict, so a key that looks like a wider
version of the opt-in is refused rather than ignored. The opt-in is one named key,
not the start of a family of allow-everything switches.

### AC-NODE-70: The opt-in does not relax the other scope rules

**Precondition:** A policy with `allow_filesystem_root: true`.

**Action:** Set a scope path to a relative path, to a symlink, to a regular file, to
a missing path, or to the home directory.

**Expected:** Startup fails for each. The opt-in relaxes exactly two refusals, the
filesystem root and the config-directory overlap, because the second follows from
the first. Every other rule about what a scope root may be still applies.
