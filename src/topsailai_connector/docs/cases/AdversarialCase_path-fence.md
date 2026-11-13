---
maintainer: AI
author: DawsonLin
---

# Adversarial Cases: The Path Fence

The fence is the only real security boundary in a read-only system. Every case here
is an attempt to read a file outside a scope, and every one must be refused.

## Setup

A fixture directory is created for each case:

```
<tmp>/scope/             the scope root
<tmp>/scope/inside.txt   a file that must be readable
<tmp>/outside/secret.txt a file that must never be readable
```

The scope `project` maps to `<tmp>/scope`. The policy grants `project: [read,
list, stat]`.

## The expected refusal

A refused path is `invalid_argument` when the grammar rejects it before touching the
filesystem, and `not_found` or `denied` when the fence rejects it during
resolution. The distinction matters: a grammar rejection is a cheap check, and a
fence rejection is the kernel refusing to resolve.

**No case may pass by returning the content of `secret.txt`.** That is the only
assertion that matters, and every other assertion in this file is secondary to it.

## Traversal

### AC-PATH-1: A single `..` component

**Action:** `file.read` on `../outside/secret.txt`.

**Expected:** `invalid_argument`. The grammar rejects `..` before the filesystem is
touched.

### AC-PATH-2: A `..` component in the middle

**Action:** `file.read` on `a/../../outside/secret.txt`.

**Expected:** `invalid_argument`.

### AC-PATH-3: A `..` component at the end

**Action:** `file.read` on `inside.txt/..`.

**Expected:** `invalid_argument`. A trailing `..` addresses the parent, which is
outside.

### AC-PATH-4: A `..` that resolves back inside

**Action:** `file.read` on `sub/../inside.txt`, where `sub` exists.

**Expected:** `invalid_argument`. The path is refused even though it resolves
inside, because the accepted grammar stays small and reviewable. Normalising it
would create a second grammar to reason about.

### AC-PATH-5: Many `..` components

**Action:** `file.read` on `../../../../../../etc/passwd`.

**Expected:** `invalid_argument`.

### AC-PATH-6: A `..` component that is the whole path

**Action:** `file.read` on `..`.

**Expected:** `invalid_argument`.

## Absolute paths

### AC-PATH-7: A POSIX absolute path

**Action:** `file.read` on `/etc/passwd`.

**Expected:** `invalid_argument`.

### AC-PATH-8: A Windows absolute path

**Action:** `file.read` on `C:\Windows\win.ini`.

**Expected:** `invalid_argument`. The colon rule rejects it on every platform, so
the same request means the same thing everywhere.

### AC-PATH-9: A UNC path

**Action:** `file.read` on `\\server\share\secret.txt`.

**Expected:** `invalid_argument`. The backslash rule rejects it.

### AC-PATH-10: An extended-length path

**Action:** `file.read` on `\\?\C:\Windows\win.ini`.

**Expected:** `invalid_argument`.

### AC-PATH-11: A path that is absolute only after a leading space

**Action:** `file.read` on ` /etc/passwd`.

**Expected:** `invalid_argument`. The leading space is refused, so the value is
never trimmed into an absolute path.

## Symlinks

### AC-PATH-12: A symlink to an outside directory

**Precondition:** `<tmp>/scope/escape` is a symlink to `<tmp>/outside`.

**Action:** `file.read` on `escape/secret.txt`.

**Expected:** Refused by the fence. `os.Root` reports that the path escapes from
the parent.

### AC-PATH-13: A symlink to an outside file

**Precondition:** `<tmp>/scope/outlink` is a symlink to `<tmp>/outside/secret.txt`.

**Action:** `file.read` on `outlink`.

**Expected:** Refused by the fence.

### AC-PATH-14: A relative symlink that climbs out

**Precondition:** `<tmp>/scope/rel_out` is a symlink to `../outside/secret.txt`.

**Action:** `file.read` on `rel_out`.

**Expected:** Refused by the fence.

### AC-PATH-15: A relative symlink that stays inside

**Precondition:** `<tmp>/scope/rel_inside` is a symlink to `inside.txt`.

**Action:** `file.read` on `rel_inside`.

**Expected:** Allowed, and the content of `inside.txt` is returned. A fence that
refused this would be refusing a legitimate file, and an over-strict fence gets
disabled by an operator.

### AC-PATH-16: A symlink chain that ends outside

**Precondition:** `a` is a symlink to `b`, `b` is a symlink to
`../outside/secret.txt`.

**Action:** `file.read` on `a`.

**Expected:** Refused by the fence. The chain is resolved by the kernel, so an
intermediate link cannot hide the escape.

### AC-PATH-17: A symlink loop

**Precondition:** `loop` is a symlink to itself.

**Action:** `file.read` on `loop`.

**Expected:** An error, not a hang. A loop that blocks a request is a denial of
service with one line of setup.

### AC-PATH-18: `stat` on an escaping symlink reports the link

**Precondition:** `<tmp>/scope/outlink` is a symlink to `<tmp>/outside/secret.txt`.

**Action:** `file.stat` on `outlink`.

**Expected:** The result describes a symlink and does not describe the target. The
Node uses `Lstat` here, because `Stat` would follow the link and the fence refuses
that.

**Why this case exists:** `os.Root`'s `Stat` refuses an escaping symlink while
`Lstat` allows it. Using `Stat` would make `file.stat` fail where it should report,
and using `Lstat` everywhere would make `file.read` follow a link it must not.

### AC-PATH-19: `stat` does not reveal whether an outside file exists

**Precondition:** `<tmp>/scope/outlink` is a symlink to a path that does not exist
outside.

**Action:** `file.stat` on `outlink`.

**Expected:** The result describes a symlink and says nothing about the target. A
`stat` that reported "target missing" would be an existence oracle for the whole
filesystem.

## Hard links

### AC-PATH-20: A hard link to an outside file

**Precondition:** `<tmp>/scope/hardlink` is a hard link to
`<tmp>/outside/secret.txt`.

**Action:** `file.read` on `hardlink`.

**Expected:** **Allowed**, and this is a known limitation rather than a bug. A hard
link is a second name for the same inode, and no path-based fence can distinguish
it from a legitimate file. The case is recorded so the behaviour is a decision
rather than a surprise.

**Mitigation:** a scope root that is writable by an untrusted party is the
precondition for this attack, so the design states that a scope should not be
world-writable. The case asserts the documented behaviour, not a refusal.

## The prefix collision

### AC-PATH-21: A sibling directory whose name starts with the scope name

**Precondition:** `<tmp>/scope` is the scope, `<tmp>/scope-secret/key` exists.

**Action:** `file.read` on `../scope-secret/key`.

**Expected:** `invalid_argument`.

**Why this case exists:** it is the case a hand-written `strings.HasPrefix` check
fails. The joined string `<tmp>/scope/../scope-secret/key` starts with `<tmp>/scope`,
so a prefix check passes while the real file is outside. This case is the reason the
fence is `os.Root` rather than a string comparison.

### AC-PATH-22: A scope root that is a prefix of the config directory

**Precondition:** The Node's config directory is `<tmp>/scope/.config`.

**Action:** Start the Node with a scope at `<tmp>/scope`.

**Expected:** Startup fails. A scope that contains the Node's own credentials is a
configuration mistake worth refusing once rather than denying per request.

## Encoding

### AC-PATH-23: A percent-encoded traversal

**Action:** `file.read` on `%2e%2e/outside/secret.txt`.

**Expected:** `invalid_argument` or `not_found`. The path is never percent-decoded,
so `%2e%2e` is a literal directory name that does not exist. Decoding would create a
second grammar, and the second grammar is where the bug lives.

### AC-PATH-24: A double-encoded traversal

**Action:** `file.read` on `%252e%252e/outside/secret.txt`.

**Expected:** `not_found`. The literal name does not exist.

### AC-PATH-25: A backslash traversal

**Action:** `file.read` on `..\outside\secret.txt`.

**Expected:** `invalid_argument`. The backslash rule rejects it on POSIX too, so a
request cannot mean one thing on Linux and another on Windows.

### AC-PATH-26: A mixed separator traversal

**Action:** `file.read` on `../outside\secret.txt`.

**Expected:** `invalid_argument`.

### AC-PATH-27: A URL-encoded NUL

**Action:** `file.read` on `inside.txt%00.md`.

**Expected:** `invalid_argument` or `not_found`. The value is not decoded, so no NUL
reaches the syscall.

### AC-PATH-28: A literal NUL byte

**Action:** `file.read` on `inside.txt\x00.md`.

**Expected:** `invalid_argument`. A NUL truncates the string at the syscall
boundary, so the checked name and the opened name would differ.

## Grammar

### AC-PATH-29: An empty path

**Action:** `file.read` on `""`.

**Expected:** `invalid_argument`. An empty path would resolve to the scope root.

### AC-PATH-30: A `.` component

**Action:** `file.read` on `./inside.txt`.

**Expected:** `invalid_argument`. Rejected rather than normalised.

### AC-PATH-31: A path of only dots

**Action:** `file.read` on `...`.

**Expected:** `invalid_argument` or `not_found`. `...` is not `..`, so it is a
literal name; it must not be treated as traversal.

### AC-PATH-32: A trailing dot

**Action:** `file.read` on `inside.txt.`.

**Expected:** `invalid_argument`. On Windows the filesystem strips the dot, so the
checked name and the opened name would differ.

### AC-PATH-33: A trailing space

**Action:** `file.read` on `inside.txt `.

**Expected:** `invalid_argument`.

### AC-PATH-34: A colon in the name

**Action:** `file.read` on `inside.txt:stream`.

**Expected:** `invalid_argument`. On Windows a colon introduces an alternate data
stream, which is a hidden file attached to a visible one.

### AC-PATH-35: A control character

**Action:** `file.read` on `inside\t.txt`.

**Expected:** `invalid_argument`.

### AC-PATH-36: An over-long path

**Action:** `file.read` on a 100 KiB path.

**Expected:** `invalid_argument`. An unbounded path is a memory and log problem.

### AC-PATH-37: A path with a newline

**Action:** `file.read` on `inside.txt\n`.

**Expected:** `invalid_argument`. A newline in a path is a log-injection vector as
well as a name mismatch.

## File type

### AC-PATH-38: A fifo

**Precondition:** `<tmp>/scope/pipe` is a fifo.

**Action:** `file.read` on `pipe`.

**Expected:** `invalid_argument`. A read on a fifo with no writer blocks forever, so
the request would hang until the timeout and hold a worker.

### AC-PATH-39: A device file

**Precondition:** `<tmp>/scope/zero` is a symlink to `/dev/zero`, or the scope
contains a device node.

**Action:** `file.read` on `zero`.

**Expected:** `invalid_argument`. `/dev/zero` never ends, so a read would consume
memory until the response cap stopped it.

### AC-PATH-40: A directory passed to `read`

**Action:** `file.read` on `sub`, where `sub` is a directory.

**Expected:** `invalid_argument`. `read` requires a regular file.

### AC-PATH-41: A file passed to `list`

**Action:** `file.list` on `inside.txt`.

**Expected:** `invalid_argument`. `list` requires a directory.

### AC-PATH-42: A socket

**Precondition:** `<tmp>/scope/sock` is a unix socket.

**Action:** `file.read` on `sock`.

**Expected:** `invalid_argument`.

## Time of check to time of use

### AC-PATH-43: A directory swapped between check and open

**Precondition:** A concurrent goroutine replaces `<tmp>/scope/sub` with a symlink
to `<tmp>/outside` while a request is in flight.

**Action:** `file.read` on `sub/secret.txt`, repeated many times.

**Expected:** Every attempt is either refused or reads a file inside the scope.
**No attempt reads `secret.txt`.** The open is the check, so there is no window
between them.

**Why this case exists:** it is the case a hand-written fence fails. A check that
resolves a path and an open that resolves it again are two resolutions, and the
attacker only needs them to disagree once.

### AC-PATH-44: The scope root is renamed during a request

**Precondition:** The scope directory is renamed while a request is in flight.

**Action:** `file.read` on `inside.txt`.

**Expected:** The request either succeeds against the original directory or fails.
It never reads a file from whatever now occupies the old name, because the `os.Root`
handle references the directory that was validated.

### AC-PATH-45: A file is replaced by a symlink during a read

**Precondition:** A concurrent goroutine replaces `inside.txt` with a symlink to
`<tmp>/outside/secret.txt`.

**Action:** `file.read` on `inside.txt`, repeated many times.

**Expected:** No attempt returns the content of `secret.txt`.

## Response size

### AC-PATH-46: A file larger than the response cap

**Precondition:** `<tmp>/scope/big.bin` is 1 MiB.

**Action:** `file.read` on `big.bin`.

**Expected:** The response is capped at 256 KiB and the truncation is reported. A
read that buffered the whole file would let one request exhaust memory.

### AC-PATH-47: A file that grows during the read

**Precondition:** A concurrent writer appends to `big.bin` during the read.

**Action:** `file.read` on `big.bin`.

**Expected:** The response is capped. The cap is applied to what is read, not to the
size reported before the read.

## Scope mapping

### AC-PATH-48: A scope root of `/`

**Action:** Start the Node with a scope at `/`.

**Expected:** Startup fails. The blast radius is the whole machine. The one
exception is a policy that states `allow_filesystem_root: true`, which is the
operator writing that blast radius down on purpose; the case then succeeds and the
deny list carries the protection instead. See AC-PATH-64.

### AC-PATH-49: A scope root of the home directory

**Action:** Start the Node with a scope at the user's home directory.

**Expected:** Startup fails.

### AC-PATH-50: A scope root that is a symlink

**Action:** Start the Node with a scope at a path that is a symlink to a directory.

**Expected:** Startup fails. The root is resolved once, so the link would be
followed at startup and the operator would not know what the scope means.

### AC-PATH-51: A scope root that does not exist

**Action:** Start the Node with a scope at a missing path.

**Expected:** Startup fails. A scope that silently appears later is a scope nobody
validated.

### AC-PATH-52: A scope root that is a file

**Action:** Start the Node with a scope at a regular file.

**Expected:** Startup fails.

### AC-PATH-53: A relative scope root

**Action:** Start the Node with a scope at `./project`.

**Expected:** Startup fails. A relative path resolves differently per working
directory, which is a different meaning per launch.

### AC-PATH-54: A scope name containing a path separator

**Action:** Define a scope named `../project` in the policy file.

**Expected:** Startup fails. A scope name is an identifier, never a path.

### AC-PATH-55: A scope name containing a space

**Action:** Define a scope named `my project`.

**Expected:** Startup fails. The identifier rule is letters, digits, `-` and `_`
only.

### AC-PATH-56: A scope name containing a NUL byte

**Action:** Define a scope named `pro\x00ject`.

**Expected:** Startup fails. The current `ValidateScopeName` accepts this, which is
the defect recorded in `issues/issue-scope-name-validation-too-loose.md`.

### AC-PATH-57: A scope name with a trailing dot

**Action:** Define a scope named `project.`.

**Expected:** Startup fails.

### AC-PATH-58: A scope name with a colon

**Action:** Define a scope named `pro:ject`.

**Expected:** Startup fails.

## The deny list

### AC-PATH-59: Reading the Node's policy file through a scope

**Precondition:** The policy file is inside a scope directory.

**Action:** `file.read` on the policy file's relative path.

**Expected:** `denied`. The deny list is computed from resolved paths at
startup, so the file is refused by identity rather than by name.

### AC-PATH-60: Reading the Node's identity file through a scope

**Precondition:** The identity file is inside a scope directory.

**Action:** `file.read` on the identity file's relative path.

**Expected:** `denied`. This is the case that matters most: the identity file
holds the `node-token`, so reading it would hand the caller the secret that
authorises the read.

### AC-PATH-61: Reaching the identity file through a symlink

**Precondition:** A symlink inside the scope points at the identity file.

**Action:** `file.read` on the symlink.

**Expected:** `denied`. The deny list is compared against the resolved path,
so a symlink does not rename the file.

### AC-PATH-62: Reaching the identity file by a different spelling

**Precondition:** The identity file is at `<tmp>/scope/.config/identity`.

**Action:** `file.read` on `.config/./identity` and on `.config//identity`.

**Expected:** `invalid_argument` for the `.` component, and `denied` for the
double separator if it is accepted. A deny list compared against the raw string
would be bypassed by any spelling the filesystem accepts.

### AC-PATH-63: The deny list is compared case-insensitively on Windows

**Precondition:** Windows, the identity file is `Identity`.

**Action:** `file.read` on `identity`.

**Expected:** `denied`. On Windows the two names are the same file, so a
case-sensitive comparison would be bypassed by changing the case.

### AC-PATH-64: A filesystem-root scope that opted in still hides the credentials

**Precondition:** A policy with `allow_filesystem_root: true` and a scope rooted at
a volume, such as `C:\` or `/`. The Node's config directory sits inside that
volume.

**Action:** `file.list` on the scope root, then `file.read`, `file.stat` and
`file.list` on the config directory and on each of `identity`, `policy.yaml` and
`tunnel_token` inside it.

**Expected:** The listing omits the config directory entirely, so its name and
size are not reported. Every read, stat and list of the directory or of a file
inside it is `denied`. The opt-in relaxes the startup refusal, not the deny list:
the deny list is what carries the protection once a scope may contain the config
directory.

**Why this case exists:** the opt-in removes the startup refusal that used to make
this situation impossible, so the deny list becomes load-bearing rather than
redundant. A listing that reported the config directory's name and size would leak
metadata the refusal used to hide, and a read of `identity` would hand the caller
the `node-token` that authorizes every operation on this Node.

### AC-PATH-65: A filesystem-root scope that opted in still refuses an escape

**Precondition:** The same opted-in policy, with an outside directory reachable
from the volume root.

**Action:** `file.read` on a path that climbs out of the root, and on a symlink
inside the root that points outside it.

**Expected:** `invalid_argument` for the traversal, and a fence refusal for the
symlink. The opt-in changes which roots are allowed, not how a path is resolved, so
`os.Root` still refuses every name whose resolution leaves the root.

### AC-PATH-66: A sibling of the config directory is not denied

**Precondition:** The config directory is `<volume>/config`, and
`<volume>/config-backup` exists.

**Action:** `file.read` on `config-backup/notes.txt` through the opted-in scope.

**Expected:** Allowed. The deny comparison uses a separator boundary, so a sibling
whose name merely starts with the denied directory's name is not refused. A prefix
comparison without the boundary would deny a legitimate directory, and an
over-broad deny list is one an operator works around by widening the scope.

## What these cases do not cover

- A bind mount inside a scope. `os.Root` documents that it does not prohibit
  traversal of filesystem boundaries, so a scope containing a bind mount to `/` is
  readable through the fence. The mitigation is the startup check that refuses a
  mount point as a scope root, and the limitation is stated in the residual risks.
- A `/proc` file that is a regular file. The regular-file rule refuses the ones that
  are not, and the rest are accepted.
- A compromised Node host. The fence is gone entirely, and nothing in the design
  helps.
