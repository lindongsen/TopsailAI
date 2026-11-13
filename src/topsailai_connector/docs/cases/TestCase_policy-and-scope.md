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

### TC-POL-12: A scope with a missing path fails startup

**Action:** Set `path: /does/not/exist`.

**Expected:** Startup fails.

### TC-POL-13: A scope path that is a file fails startup

**Action:** Set `path` to a regular file.

**Expected:** Startup fails.

### TC-POL-14: A scope path that is a symlink fails startup

**Action:** Set `path` to a symlink to a directory.

**Expected:** Startup fails. The root is resolved once, so the link would be
followed at startup and the operator would not know what the scope means.

### TC-POL-15: A scope path of `/` fails startup

**Action:** Set `path: /`.

**Expected:** Startup fails. The blast radius is the whole machine.

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

### TC-POL-51: A config directory readable by a group is refused or fixed

**Precondition:** The config directory is `0755`.

**Action:** Start the Node.

**Expected:** Startup fails, or the mode is corrected and the change is logged. A
group-readable config directory is a leaked `node-token`.

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
