---
maintainer: AI
author: DawsonLin
---

# Test Cases: Policy and Scope

The policy file is the only place a permission is granted. These cases check that a
bad policy fails startup rather than silently granting or silently denying.

## Startup validation

### TC-POL-1: A valid policy starts

**Action:** Start the Node with a policy defining one scope and one grant.

**Expected:** The Node starts and serves the granted operation.

### TC-POL-2: A missing policy file fails startup

**Action:** Start the Node with no policy file.

**Expected:** Startup fails with a message naming the path. A missing file is not an
implicit allow-all.

### TC-POL-3: An empty policy file fails startup

**Action:** Start the Node with an empty file.

**Expected:** Startup fails. An empty file is a typo, not a policy that grants
nothing; a policy that grants nothing is written explicitly.

### TC-POL-4: A policy with no `version` fails startup

**Action:** Omit `version`.

**Expected:** Startup fails. The version is what makes a future format change
detectable.

### TC-POL-5: An unknown `version` fails startup

**Action:** Set `version: 2`.

**Expected:** Startup fails. A version the binary does not understand is not a
version it may guess at.

### TC-POL-6: A malformed YAML file fails startup

**Action:** Write a file with a tab where YAML forbids one.

**Expected:** Startup fails with the line number.

### TC-POL-7: An unknown top-level key fails startup

**Action:** Add `allow_all: true`.

**Expected:** Startup fails. A typo in a security config that is silently ignored is
worse than a crash, and `allow_all` is exactly the key an operator would try.

### TC-POL-8: An unknown key inside a scope fails startup

**Action:** Add `mode: rw` to a scope.

**Expected:** Startup fails.

### TC-POL-9: An unknown key inside a grant fails startup

**Action:** Add `expires: never` to a grant.

**Expected:** Startup fails.

## Scopes

### TC-POL-10: A scope without a path fails startup

**Action:** Define a scope with no `path`.

**Expected:** Startup fails.

### TC-POL-11: A scope with a relative path fails startup

**Action:** Set `path: ./project`.

**Expected:** Startup fails. A relative path resolves differently per working
directory.

### TC-POL-12: A scope with a missing path starts and refuses every request

**Action:** Set `path: /does/not/exist`, then start the Node and request
`file.read`, `file.list` and `file.stat` on that scope.

**Expected:** Startup succeeds. The startup log names the scope and its path at
WARN, and the ready line lists it in `absent_scopes`. Every request on the scope
returns `not_found`, and the process stays alive. A policy is written before the
machine is ready, so one absent directory must not stop a Node that serves
several; the scope stays defined so the operator does not believe a grant exists
that does not.

### TC-POL-12b: A policy mixing present and absent scopes serves the present ones

**Action:** Define three scopes whose directories exist and three whose directories
do not, grant `read`, `list` and `stat` on all six, then start the Node and request
each operation on each scope.

**Expected:** Startup succeeds. The ready line lists all six scopes and names only
the three absent ones in `absent_scopes`, with one WARN per absent scope carrying
its path. Every operation on a present scope succeeds and returns that scope's own
content, including a file several directories deep. Every operation on an absent
scope returns `not_found`. A malformed path on an absent scope still returns
`invalid_argument`, because the grammar is a property of the request and not of the
directory. A missing file inside a present scope returns `not_found` with a
different reason, so the two causes stay distinguishable in the log. The process
stays alive, and a present scope still serves after every refusal.

### TC-POL-12c: A Windows policy mixing a present drive and absent drives starts

**Action:** On a Windows host where only `C:` exists, define one scope on a
directory under `C:`, one scope on `D:\` and one on `E:\`, grant the three read
permissions on all of them, then start the Node and request each operation.

**Expected:** Startup succeeds. `absent_scopes` names `D:` and `E:` and not the
present scope. The present scope serves its files. Every operation on `D:` and
`E:` returns `not_found`, and the log reason says the scope has no directory rather
than that the path was refused. A path containing a backslash or a colon on an
absent drive returns `invalid_argument`. The process stays alive.

The same policy with `C:\` itself as a scope root requires
`allow_filesystem_root: true`; with the opt-in the drive root serves files and the
Node's config directory is still refused and omitted from a listing.

### TC-POL-12d: An absent drive is refused once the drive appears

**Action:** Start the Node with a scope on `D:\` while `D:` does not exist, then
create `D:` and start the same policy again without `allow_filesystem_root`.

**Expected:** The first start succeeds and names the scope in `absent_scopes`. The
second start fails with `path "D:\\" is a filesystem root; its blast radius is the
whole machine`. Adding `allow_filesystem_root: true` makes the second start succeed
and the scope serve. The absence is tolerated, but it never becomes a silent grant
of a whole volume: the volume is refused the moment it exists, unless the operator
wrote the opt-in down.

### TC-POL-13: A scope path that is a file fails startup

**Action:** Set `path` to a regular file.

**Expected:** Startup fails.

### TC-POL-14: A scope path that is a symlink fails startup

**Action:** Set `path` to a symlink to a directory.

**Expected:** Startup fails. The root is resolved once, so the link would be
followed at startup and the operator would not know what the scope means.

### TC-POL-15: A scope path of `/` fails startup

**Action:** Set `path: /` and omit `allow_filesystem_root`.

**Expected:** Startup fails. The blast radius is the whole machine.

### TC-POL-15b: A scope path of `/` starts when the policy opts in

**Action:** Set `path: /` and `allow_filesystem_root: true`.

**Expected:** Startup succeeds. The scope serves files inside the root, and a path
that leaves the root is still refused. The Node's config directory is refused and
omitted from a listing, because it is on the deny list.

### TC-POL-16: A scope path of the home directory fails startup

**Action:** Set `path` to the user's home directory.

**Expected:** Startup fails.

### TC-POL-17: A scope path that is a mount point fails startup

**Action:** Set `path` to a mount point.

**Expected:** Startup fails. A scope containing a bind mount to `/` is readable
through the fence, so a mount root is refused.

### TC-POL-18: A scope path inside the config directory fails startup

**Action:** Set `path` to a directory inside the Node's config directory.

**Expected:** Startup fails. A scope that can read its own credentials is a
configuration mistake.

### TC-POL-19: A scope path containing the config directory fails startup

**Action:** Set `path` to a directory that contains the config directory.

**Expected:** Startup fails.

### TC-POL-20: Two scopes with the same path are allowed

**Action:** Define `project` and `alias` with the same path.

**Expected:** Startup succeeds. Two names for one directory is a legitimate
configuration, and refusing it would be an arbitrary restriction.

### TC-POL-21: Two scopes with the same name fail startup

**Action:** Define `project` twice.

**Expected:** Startup fails, or the last definition wins with a warning. A duplicate
name is ambiguous, and an ambiguous policy is one nobody can review.

## Scope names

### TC-POL-22: A valid scope name is accepted

**Action:** Define scopes named `project`, `my-project`, `my_project`, `project2`.

**Expected:** All are accepted.

### TC-POL-23: A scope name with a space is refused

**Action:** Define `my project`.

**Expected:** Startup fails.

### TC-POL-24: A scope name with a tab is refused

**Action:** Define `my\tproject`.

**Expected:** Startup fails.

### TC-POL-25: A scope name with a NUL byte is refused

**Action:** Define `pro\x00ject`.

**Expected:** Startup fails. The current `ValidateScopeName` accepts this, which is
the defect recorded in `issues/issue-scope-name-validation-too-loose.md`.

### TC-POL-26: A scope name with a colon is refused

**Action:** Define `pro:ject`.

**Expected:** Startup fails.

### TC-POL-27: A scope name with a trailing dot is refused

**Action:** Define `project.`.

**Expected:** Startup fails.

### TC-POL-28: A scope name with a path separator is refused

**Action:** Define `../project`.

**Expected:** Startup fails. A scope name is an identifier, never a path.

### TC-POL-29: A scope name with a leading dot is refused

**Action:** Define `.project`.

**Expected:** Startup fails. A leading dot is a hidden name on POSIX, which is a name
the operator would not see in a listing.

### TC-POL-30: An empty scope name is refused

**Action:** Define `""`.

**Expected:** Startup fails.

### TC-POL-31: A scope name that is only digits is accepted

**Action:** Define `123`.

**Expected:** Startup succeeds. A name is an identifier, and digits are identifiers.

### TC-POL-32: A scope name is case-sensitive

**Action:** Define `Project` and `project` as two scopes with different paths.

**Expected:** Startup succeeds and the two are distinct. A case-insensitive name
comparison would make two scopes collide.

## Grants

### TC-POL-33: A grant naming an undefined scope fails startup

**Action:** Grant `read` on `unknown`.

**Expected:** Startup fails. A typo would otherwise look like a working policy.

### TC-POL-34: A grant with an unknown permission fails startup

**Action:** Grant `fly` on `project`.

**Expected:** Startup fails.

### TC-POL-35: A grant with an empty permission list is valid

**Action:** Grant `[]` on `project`.

**Expected:** Startup succeeds and every operation on that scope is refused.

### TC-POL-36: A policy with no grants is valid

**Action:** Define a scope and no `grants` key.

**Expected:** Startup succeeds and every operation is refused. Default deny.

### TC-POL-37: A grant with a duplicate permission is accepted

**Action:** Grant `[read, read]`.

**Expected:** Startup succeeds, or the duplicate is collapsed with a warning. A
duplicate is harmless, so refusing it would be pedantic.

### TC-POL-38: A grant on a scope with no path fails startup

**Action:** Grant `read` on a scope that has no `path`.

**Expected:** Startup fails.

### TC-POL-39: `write` is a known permission but grants nothing in the first version

**Action:** Grant `write` on `project`, then send `file.write`.

**Expected:** Startup succeeds, and the operation is refused with
`unsupported_operation`. The permission is known so a second-version policy parses,
and the operation is refused because it is not implemented.

**Why this case exists:** it separates "the policy allows it" from "the binary
implements it". A policy that grants `write` on a read-only binary must not make
`write` work.

### TC-POL-40: `exec` is a known permission but grants nothing in the first version

**Action:** Grant `exec` on `project`, then send `command.exec`.

**Expected:** Startup succeeds, and the operation is refused with
`unsupported_operation`.

## Reload

### TC-POL-41: `SIGHUP` reloads a valid policy

**Precondition:** A policy granting `project: [read]`.

**Action:** Add `list`, send `SIGHUP`, then send `file.list`.

**Expected:** The listing succeeds. The new policy is in force without a restart.

### TC-POL-42: `SIGHUP` with an invalid policy keeps the old one

**Precondition:** A valid policy in force.

**Action:** Write an invalid policy, send `SIGHUP`, then send a granted operation.

**Expected:** The operation still succeeds and the rejection is logged. Reload is
all-or-nothing, so a bad file does not leave the Node with no policy.

### TC-POL-43: `SIGHUP` with a missing file keeps the old one

**Action:** Delete the policy file, send `SIGHUP`.

**Expected:** The old policy stays in force and the failure is logged. A reload that
failed open would be a reload that removed the fence.

### TC-POL-44: `SIGHUP` does not drop live channels

**Action:** Send `SIGHUP` while a Node is connected.

**Expected:** The channel stays open. A policy reload is not a credential change, so
it must not disconnect.

### TC-POL-45: A reload does not change a scope's resolved path

**Precondition:** A scope at `<tmp>/scope`.

**Action:** Move the directory, then reload the policy with the same path.

**Expected:** The reload fails, because the path no longer exists. The `os.Root`
handle keeps referencing the original directory, so the scope means the directory
that was validated rather than whatever now occupies the name.

## Scope to directory mapping

### TC-POL-46: The resolved path is stored at startup

**Action:** Start the Node, then rename the scope directory.

**Expected:** Requests still address the original directory, because the handle
references it. A scope that followed the name would change meaning when a directory
was renamed.

### TC-POL-47: The Server never learns the absolute path

**Action:** Serve a request and inspect every frame the Server receives.

**Expected:** No absolute path appears. The Server sees the scope name and the
relative path, so a leaked policy does not leak the filesystem layout.

### TC-POL-48: A scope name is not a path

**Action:** Send a request with `scope: /home/me/project`.

**Expected:** `denied`. A scope is a name, so a path is not a scope.

### TC-POL-49: A scope name is not resolved against the filesystem

**Action:** Send a request with `scope: project` when a directory named `project`
exists in the working directory but is not the configured scope.

**Expected:** The configured scope is used. The name is a key into the policy, not a
path to resolve.

## Configuration interaction

### TC-POL-50: A missing config directory is created

**Action:** Start the Node with a config directory that does not exist.

**Expected:** The directory is created with `0700` on POSIX. On Windows the Node
sets no ACL, so the directory inherits its parent's default descriptor, which
grants `BUILTIN\Users` read access; the operator must choose a parent directory
with a restrictive ACL.

### TC-POL-51: A config directory readable by a group is accepted

**Precondition:** The config directory is `0755` and the files inside it are `0600`.

**Action:** Start the Node.

**Expected:** Startup succeeds. The mode check is on the two files that hold
secrets, not on the directory: `identity` and `credentials.yaml` each refuse
`mode&0o077 != 0`, and a directory that is merely traversable discloses nothing by
itself. Measured on Linux: a `0755` config directory holding `0600` files reached
`connector-node ready`.

**Why this case is written this way:** an earlier version expected startup to
fail, on the reasoning that a group-readable config directory leaks the node
credential. That reasoning was wrong twice: the directory holds no secret of its
own, and the check that actually protects the secret is the file mode. A case that
expects a refusal the code does not perform is a case that gets the code "fixed" to
match the document.

### TC-POL-51b: A credential file readable by a group is refused

**Precondition:** `credentials.yaml` is `0644`.

**Action:** Start the Node.

**Expected:** Startup fails with `credential file "<path>" has mode 0644, want no
group or other access; it holds secrets that never expire`. The message names the
file and the mode, and never the secret.

### TC-POL-52: The policy file may live outside the config directory

**Action:** Set `CONNECTOR_NODE_POLICY_FILE` to a path elsewhere.

**Expected:** Startup succeeds. The policy is not a secret, so it does not have to
live beside the identity.

### TC-POL-53: A policy file readable by a group is accepted

**Precondition:** The policy file is `0644`.

**Action:** Start the Node.

**Expected:** Startup succeeds. The policy contains no secret, so a group-readable
policy is not a leak. Refusing it would train an operator to loosen permissions on
the file that does hold a secret.
