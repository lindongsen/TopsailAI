---
maintainer: AI
author: DawsonLin
---

# Test Cases: Node Authority

The Node is the only authority for permissions. It controls both dimensions: the
access scope and the concrete action allowed there. These cases check that the
authority is real, that it is exercised on the Node, and that nothing outside the
Node can move it.

A case that only checks "the operation was refused" is not enough here. The
interesting question is *which* check refused it, because a request refused by the
fence has not tested the grant and a request refused because the Node was offline
has tested nothing at all.

## Scope control

### TC-NODE-1: A scope defined in the policy is addressable

**Precondition:** A policy defining `project` with `read`.

**Action:** Send `file.read` with `scope: project`.

**Expected:** The read succeeds. The scope name is a key into the policy, and the
policy defines it.

### TC-NODE-2: A scope not defined in the policy is refused

**Precondition:** A policy defining only `project`.

**Action:** Send `file.read` with `scope: scratch`.

**Expected:** `unauthorized`. The Node's scope list is the whole list, so a name
outside it does not exist.

### TC-NODE-3: A scope defined but with no grant is refused

**Precondition:** A policy defining `project` and `scratch`, with a grant only on
`project`.

**Action:** Send `file.read` with `scope: scratch`.

**Expected:** `unauthorized`. Defining a scope exposes a directory to the policy, not
to a caller.

### TC-NODE-4: The Node's scope list is not published to the Server

**Action:** Connect a Node, then inspect every frame the Server receives and every
field the Server stores.

**Expected:** No scope name appears. The Server cannot enumerate scopes, so it cannot
report them to a caller and cannot check a scope itself.

### TC-NODE-5: A scope name is matched exactly

**Precondition:** A policy defining `project`.

**Action:** Send `scope: project ` with a trailing space.

**Expected:** `unauthorized`. The name is not trimmed, because trimming would make
two different wire values address the same scope.

### TC-NODE-6: A scope name differing in case is refused

**Precondition:** A policy defining `project`.

**Action:** Send `scope: Project`.

**Expected:** `unauthorized`. A case-insensitive match would make the policy mean
something different on Windows than on Linux.

### TC-NODE-7: A scope name with a path separator is refused before lookup

**Action:** Send `scope: ../project`.

**Expected:** `invalid_argument`. The name is rejected as malformed before the policy
is consulted, so a path can never be a scope.

### TC-NODE-8: An empty scope is refused

**Action:** Send `scope: ""`.

**Expected:** `invalid_argument`. An empty name is a missing name, not a scope.

### TC-NODE-9: A missing scope field is refused

**Action:** Send a request with no `scope` key.

**Expected:** `invalid_argument`. A missing field is not a default scope.

### TC-NODE-10: Two scopes with the same path are independently authorized

**Precondition:** `project` and `alias` both mapped to the same directory, with
`read` granted on `project` only.

**Action:** Send `file.read` with `scope: alias`.

**Expected:** `unauthorized`. The grant is attached to the name, so sharing a
directory does not share a grant.

## Permission control

### TC-NODE-11: A granted permission allows the operation

**Precondition:** `project: [read]`.

**Action:** Send `file.read`.

**Expected:** The read succeeds.

### TC-NODE-12: A permission not granted on that scope is refused

**Precondition:** `project: [list]`.

**Action:** Send `file.read`.

**Expected:** `unauthorized`. `list` and `read` are separate permissions, so one does
not imply the other.

### TC-NODE-13: A permission granted on another scope does not apply

**Precondition:** `project: [read]`, `scratch: [list]`.

**Action:** Send `file.read` with `scope: scratch`.

**Expected:** `unauthorized`. A grant is a pair of scope and permission, so a
permission held elsewhere is not held here.

### TC-NODE-14: An empty permission list refuses every operation

**Precondition:** `project: []`.

**Action:** Send `file.list`, `file.stat` and `file.read` in turn.

**Expected:** All three are `unauthorized`. An empty list is a scope that exists and
grants nothing.

### TC-NODE-15: `read` does not imply `list`

**Precondition:** `project: [read]`.

**Action:** Send `file.list`.

**Expected:** `unauthorized`. Reading a known file and enumerating a directory are
different exposures, so the policy keeps them separate.

### TC-NODE-16: `read` does not imply `stat`

**Precondition:** `project: [read]`.

**Action:** Send `file.stat`.

**Expected:** `unauthorized`. Metadata is an exposure of its own: a name, a size and
a modification time leak information a read of a known file does not.

### TC-NODE-17: `list` does not imply `read`

**Precondition:** `project: [list]`.

**Action:** Send `file.read`.

**Expected:** `unauthorized`. Seeing that a file exists is not reading it.

### TC-NODE-18: `stat` does not imply `read`

**Precondition:** `project: [stat]`.

**Action:** Send `file.read`.

**Expected:** `unauthorized`.

### TC-NODE-19: `write` granted does not enable `file.write` in the first version

**Precondition:** `project: [write]`.

**Action:** Send `file.write`.

**Expected:** `unsupported_operation`. The permission is known so a second-version
policy parses, and the operation is refused because the binary does not implement
it. The grant cannot create an implementation.

### TC-NODE-20: `exec` granted does not enable `command.exec` in the first version

**Precondition:** `project: [exec]`.

**Action:** Send `command.exec`.

**Expected:** `unsupported_operation`.

### TC-NODE-21: An unknown permission in a request is refused

**Action:** Send an operation whose permission is not in the vocabulary.

**Expected:** `invalid_argument`. An unknown permission is not a permission the Node
may guess at.

### TC-NODE-22: An unknown operation is refused before permission lookup

**Action:** Send `operation: file.delete`.

**Expected:** `unsupported_operation`, and no policy lookup is performed. An unknown
operation has no permission to look up.

## Evaluation order

### TC-NODE-23: An invalid node-token is refused before the scope is looked up

**Precondition:** A valid policy.

**Action:** Send a request with a wrong `node-token` and an unknown scope.

**Expected:** `unauthorized` for the token, and the scope is never consulted. The
order matters because a scope error would tell an unauthenticated caller which scope
names exist.

### TC-NODE-24: A valid node-token with an unknown scope is refused

**Action:** Send a valid `node-token` with `scope: unknown`.

**Expected:** `unauthorized`, and the refusal names the scope check rather than the
token check.

### TC-NODE-25: A valid node-token with a known scope and no grant is refused

**Action:** Send a valid `node-token`, a defined scope, and an operation whose
permission is not granted.

**Expected:** `unauthorized`, and the refusal names the permission check.

### TC-NODE-26: A valid node-token with a grant and an escaping path is refused

**Precondition:** `project: [read]`.

**Action:** Send `file.read` with `path: ../outside/secret.txt`.

**Expected:** `invalid_argument` from the fence. Authorization succeeded and the path
was still refused, which proves the two checks are independent.

### TC-NODE-27: The fence is checked after authorization, not instead of it

**Precondition:** `project: [list]`.

**Action:** Send `file.read` with a path that would also escape the fence.

**Expected:** `unauthorized` for the permission, not a fence error. A fence error
would tell a caller that the path was well formed enough to reach the fence.

### TC-NODE-28: A refusal at any step produces no partial work

**Action:** Send a request that fails at the permission check, then inspect the
filesystem and the response.

**Expected:** No file is opened, no directory is read, and the response carries no
data field. A refusal that had already opened the file would be a refusal that
leaked.

## Default deny

### TC-NODE-29: A policy with no grants refuses everything

**Precondition:** A policy defining `project` and no `grants` key.

**Action:** Send `file.list`, `file.stat` and `file.read`.

**Expected:** All three are `unauthorized`.

### TC-NODE-30: A policy with no scopes refuses everything

**Precondition:** A policy with `version` and an empty `scopes` map.

**Action:** Send any operation.

**Expected:** `unauthorized`. An empty policy is a valid policy that grants nothing.

### TC-NODE-31: A missing policy file fails startup

**Action:** Start the Node with no policy file.

**Expected:** Startup fails. A missing file is not an allow-all mode.

### TC-NODE-32: An empty policy file fails startup

**Action:** Start the Node with a zero-byte policy file.

**Expected:** Startup fails. An empty file is a typo, and a policy that grants nothing
is written explicitly.

### TC-NODE-33: A policy that fails to parse fails startup

**Action:** Start the Node with a malformed policy.

**Expected:** Startup fails with the line number. A policy the Node cannot read is not
a policy it may approximate.

### TC-NODE-34: A failed reload keeps the previous policy

**Precondition:** A valid policy in force.

**Action:** Replace it with an invalid one, send `SIGHUP`, then send a granted
operation.

**Expected:** The operation still succeeds and the rejection is logged. A reload that
failed open would be a reload that removed the authority.

## The Server cannot influence the decision

### TC-NODE-35: The Server cannot add a scope

**Action:** Modify the Server to append a scope name to a forwarded request, then
send a request for that scope.

**Expected:** `unauthorized`. The Node's policy is the only scope list, so a scope the
Server invented does not exist.

### TC-NODE-36: The Server cannot widen a grant

**Action:** Modify the Server to rewrite the operation from `file.list` to
`file.read` on a scope granted only `list`.

**Expected:** `unauthorized`. The Node checks the operation it received against its
own grant, so a rewritten operation is a different request that is also refused.

### TC-NODE-37: The Server cannot mark a request pre-approved

**Action:** Modify the Server to add an approval field to the forwarded request.

**Expected:** `invalid_argument` or `unauthorized`. The Node's request schema has no
approval field, so an unknown field is refused rather than ignored.

### TC-NODE-38: The Server cannot translate a permission

**Action:** Modify the Server to send `list` where the caller asked for `read`.

**Expected:** `unauthorized`. The Node has no translation table, so a permission is
only the one the policy names.

### TC-NODE-39: The Server does not receive the policy

**Action:** Start a Node with a policy, connect it, and inspect every byte the Server
receives.

**Expected:** No policy content, no scope list and no permission list appears. The
Server cannot check a decision it has never seen.

### TC-NODE-40: A Server restart does not change the Node's decision

**Precondition:** A policy granting `project: [read]`.

**Action:** Restart the Server, reconnect the Node, then send a granted operation and
a refused one.

**Expected:** The granted operation succeeds and the refused one is still refused. The
decision lives on the Node, so a Server restart cannot change it.

### TC-NODE-41: A Node restart re-reads its own policy and nothing else

**Action:** Restart the Node with the same policy, then send a granted operation.

**Expected:** The operation succeeds. The Node's authority survives its own restart
because the policy is a local file, not a Server-supplied value.

## The CLI cannot influence the decision

### TC-NODE-42: The CLI cannot request a scope the policy lacks

**Action:** Send a request for an undefined scope through the CLI.

**Expected:** `unauthorized`. The CLI's choice of scope is a request, and the Node
refuses it.

### TC-NODE-43: The CLI cannot request a permission the grant lacks

**Precondition:** `project: [list]`.

**Action:** Ask the CLI for `file.read`.

**Expected:** `unauthorized`. The CLI has no way to make the Node agree.

### TC-NODE-44: The CLI's claimed identity does not affect the decision

**Action:** Send a request with a `subject` or `user` field naming an administrator.

**Expected:** `invalid_argument` or `unauthorized`. The Node's decision depends on the
`node-token` and the policy, not on a name the caller supplies.

### TC-NODE-45: Two CLIs with the same `client_token` get the same decision

**Action:** Send the same operation from two CLI instances holding the same
`client_token` and the same `node-token`.

**Expected:** Both receive the same result. The Node cannot distinguish them, so it
cannot treat them differently.

## Reload

### TC-NODE-46: A reload that adds a grant takes effect

**Precondition:** `project: [list]`.

**Action:** Add `read`, send `SIGHUP`, then send `file.read`.

**Expected:** The read succeeds. The Node's authority is live, so a policy change does
not need a restart.

### TC-NODE-47: A reload that removes a grant takes effect

**Precondition:** `project: [read]`.

**Action:** Remove `read`, send `SIGHUP`, then send `file.read`.

**Expected:** `unauthorized`. Narrowing takes effect as promptly as widening, because
a delay on narrowing is a window of excess authority.

### TC-NODE-48: A reload does not affect a request already authorized

**Action:** Send a request, and send `SIGHUP` while it is being served.

**Expected:** The in-flight request completes under the policy it was authorized
against, and the next request uses the new policy. A request is authorized once, not
re-authorized halfway through.

### TC-NODE-49: A reload does not change a resolved scope path

**Precondition:** A scope at `<tmp>/scope`.

**Action:** Move the directory, then reload the policy with the same path.

**Expected:** The reload fails because the path no longer exists. The `os.Root` handle
keeps referencing the directory that was validated, so a scope means that directory
rather than whatever now occupies the name.

## Audit

### TC-NODE-50: A refusal is logged with the scope and operation

**Action:** Send a request for an undefined scope, then read the Node's log.

**Expected:** The log names the scope, the operation and the refusal reason. A refusal
that cannot be diagnosed is a refusal an operator will disable.

### TC-NODE-51: A refusal log does not contain the `node-token`

**Action:** Send a request with a wrong `node-token`, then search the log for the
value.

**Expected:** The value does not appear. The log may name the `node-id`, because that
half is public.

### TC-NODE-52: A refusal names the reason code

**Action:** Trigger each refusal reason in turn and read the log.

**Expected:** Each entry names its own reason: token, scope, permission or fence. A
single "denied" for all four would make the log useless for telling a misconfigured
policy from an attack.
