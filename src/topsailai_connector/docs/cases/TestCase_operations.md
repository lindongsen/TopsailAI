---
maintainer: AI
author: DawsonLin
---

# Test Cases: Operations

The first version is read-only: `file.list`, `file.stat`, `file.read`. These cases
check the semantics of each, and check that the operations the first version
excludes are actually excluded.

## `file.list`

### TC-OP-1: List a directory

**Precondition:** A scope with `inside.txt` and `sub/`.

**Action:** `file.list` on `""` or on the scope root.

**Expected:** The entries are returned with their names and types.

### TC-OP-2: List a subdirectory

**Action:** `file.list` on `sub`.

**Expected:** The entries of `sub` are returned.

### TC-OP-3: List an empty directory

**Precondition:** An empty directory inside the scope.

**Action:** `file.list` on it.

**Expected:** An empty list, not an error. An empty directory is a normal result.

### TC-OP-4: List a file

**Action:** `file.list` on `inside.txt`.

**Expected:** `invalid_argument`. `list` requires a directory.

### TC-OP-5: List a missing directory

**Action:** `file.list` on `missing`.

**Expected:** `not_found`.

### TC-OP-6: List a large directory

**Precondition:** A directory with 100 000 entries.

**Action:** `file.list` on it.

**Expected:** The response is bounded, and the truncation is reported. A listing that
buffered every entry would let one request exhaust memory.

### TC-OP-7: List a directory with an unreadable entry

**Precondition:** A directory containing an entry the Node's user cannot stat.

**Action:** `file.list` on it.

**Expected:** The readable entries are returned and the unreadable one is reported as
unknown rather than failing the whole listing. One bad entry must not hide the rest.

### TC-OP-8: List does not follow symlinks

**Precondition:** A directory containing a symlink to an outside directory.

**Action:** `file.list` on it.

**Expected:** The symlink is reported as a symlink. Its target is not listed, because
listing the target would be following it.

### TC-OP-9: List reports the type of each entry

**Action:** `file.list` on a directory containing a file, a directory and a symlink.

**Expected:** Each entry carries its type, so a caller can tell them apart without a
second `stat` per entry.

### TC-OP-10: List is ordered deterministically

**Action:** `file.list` twice on the same directory.

**Expected:** The same order both times. An unordered listing makes a test flaky and
a diff noisy.

## `file.stat`

### TC-OP-11: Stat a file

**Action:** `file.stat` on `inside.txt`.

**Expected:** Size, mode and modification time are returned.

### TC-OP-12: Stat a directory

**Action:** `file.stat` on `sub`.

**Expected:** The result reports a directory.

### TC-OP-13: Stat a missing path

**Action:** `file.stat` on `missing`.

**Expected:** `not_found`.

### TC-OP-14: Stat a symlink reports the link

**Precondition:** `link` is a symlink to `inside.txt`.

**Action:** `file.stat` on `link`.

**Expected:** The result reports a symlink, not the target. The Node uses `Lstat`,
because `Stat` would follow the link.

### TC-OP-15: Stat an escaping symlink reports the link

**Precondition:** `outlink` is a symlink to an outside file.

**Action:** `file.stat` on `outlink`.

**Expected:** The result reports a symlink and says nothing about the target.

### TC-OP-16: Stat does not reveal the absolute path

**Action:** `file.stat` on `inside.txt`.

**Expected:** The result contains the relative path the caller sent, not the absolute
path on the Node. An absolute path leaks the filesystem layout, which the design
deliberately keeps from the Server.

### TC-OP-17: Stat does not reveal the owner

**Action:** `file.stat` on `inside.txt`.

**Expected:** The result contains no user name or user id. The caller asked about a
file, not about the machine's accounts.

### TC-OP-18: Stat a fifo

**Precondition:** A fifo inside the scope.

**Action:** `file.stat` on it.

**Expected:** The result reports a fifo. `stat` does not read, so a fifo is safe to
describe; only `read` must refuse it.

## `file.read`

### TC-OP-19: Read a file

**Action:** `file.read` on `inside.txt`.

**Expected:** The content is returned.

### TC-OP-20: Read an empty file

**Precondition:** An empty file inside the scope.

**Action:** `file.read` on it.

**Expected:** An empty payload, not an error.

### TC-OP-21: Read a binary file

**Precondition:** A file with a NUL byte in its content.

**Action:** `file.read` on it.

**Expected:** The bytes are returned unchanged. The content is opaque, so a NUL in
the content is not a NUL in a path.

### TC-OP-22: Read a file larger than the cap

**Precondition:** A 1 MiB file.

**Action:** `file.read` on it.

**Expected:** The response is capped at 256 KiB and the truncation is reported.

### TC-OP-23: Read a missing file

**Action:** `file.read` on `missing`.

**Expected:** `not_found`.

### TC-OP-24: Read a directory

**Action:** `file.read` on `sub`.

**Expected:** `invalid_argument`.

### TC-OP-25: Read a fifo

**Precondition:** A fifo inside the scope.

**Action:** `file.read` on it.

**Expected:** `invalid_argument`. A read on a fifo with no writer blocks forever.

### TC-OP-26: Read a device file

**Action:** `file.read` on a device node inside the scope.

**Expected:** `invalid_argument`.

### TC-OP-27: Read a file the Node's user cannot read

**Precondition:** A file with mode `0000`.

**Action:** `file.read` on it.

**Expected:** `unauthorized` or `not_found`, and the error does not distinguish the
two. A distinguishable error is an existence oracle.

### TC-OP-28: Read does not follow a symlink out

**Precondition:** `outlink` is a symlink to an outside file.

**Action:** `file.read` on `outlink`.

**Expected:** Refused by the fence.

### TC-OP-29: Read a file that changes during the read

**Precondition:** A concurrent writer truncates and rewrites the file.

**Action:** `file.read` on it.

**Expected:** The response is either the old content, the new content, or a mixture,
and it is capped. It is never a crash and never an unbounded read.

### TC-OP-30: Read reports the encoding as opaque

**Action:** `file.read` on a file with invalid UTF-8.

**Expected:** The bytes are returned unchanged. The Node does not validate the
encoding, because a file is bytes and a caller that wants text can decode it.

## Excluded operations

### TC-OP-31: `file.write` is refused in the first version

**Action:** Send `file.write`.

**Expected:** `unsupported_operation`. The operation is not implemented, so it is
refused by name rather than by a missing permission.

**Why this case exists:** the current `protocol` package declares `file.write` and
maps it to a permission, which means a dispatch that trusts the declaration would
accept it. The case pins the refusal.

### TC-OP-32: `command.exec` is refused in the first version

**Action:** Send `command.exec`.

**Expected:** `unsupported_operation`.

**Why this case exists:** a command allowlist is not a sandbox, so the operation is
excluded rather than restricted. The case pins the exclusion.

### TC-OP-33: An unknown operation is refused

**Action:** Send `file.delete`.

**Expected:** `unsupported_operation`. An unknown name is refused, not ignored.

### TC-OP-34: An empty operation is refused

**Action:** Send `""`.

**Expected:** `invalid_argument`.

### TC-OP-35: An operation name is case-sensitive

**Action:** Send `FILE.READ`.

**Expected:** `unsupported_operation`. A case-insensitive dispatch would accept a
name the policy never mentioned.

## Permission mapping

### TC-OP-36: `file.list` requires `list`

**Precondition:** The policy grants `project: [read]`.

**Action:** `file.list` on `project`.

**Expected:** `unauthorized`. `list` is a separate permission from `read`, so a
read-only grant does not list.

### TC-OP-37: `file.stat` requires `stat`

**Precondition:** The policy grants `project: [read]`.

**Action:** `file.stat` on `project`.

**Expected:** `unauthorized`.

### TC-OP-38: `file.read` requires `read`

**Precondition:** The policy grants `project: [list, stat]`.

**Action:** `file.read` on `project`.

**Expected:** `unauthorized`.

### TC-OP-39: A grant on one scope does not apply to another

**Precondition:** The policy grants `project: [read]` and `scratch: []`.

**Action:** `file.read` on `scratch`.

**Expected:** `unauthorized`.

### TC-OP-40: An undefined scope is refused

**Action:** `file.read` on `unknown`.

**Expected:** `unauthorized`. An undefined scope is not a directory, so it is refused
before any path resolution.

### TC-OP-41: An empty grant refuses everything

**Precondition:** The policy has a scope with an empty permission list.

**Action:** Every operation on that scope.

**Expected:** `unauthorized` for all of them. An empty grant is a valid policy that
grants nothing.

## Response shape

### TC-OP-42: A successful response has the documented shape

**Action:** `file.read` on `inside.txt`.

**Expected:** The response carries the operation, the scope, the relative path and
the payload, in the documented field names.

### TC-OP-43: A refused response has the documented shape

**Action:** `file.read` on a path outside the scope.

**Expected:** The response carries an error code and a message, and no payload.

### TC-OP-44: An error message contains no absolute path

**Action:** Trigger every refusal.

**Expected:** No message contains an absolute path. A message that named
`/home/me/project/...` would leak the layout the design keeps from the Server.

### TC-OP-45: An error message contains no secret

**Action:** Trigger every refusal.

**Expected:** No message contains a secret.

### TC-OP-46: A refusal does not distinguish "denied" from "missing" for an outsider

**Precondition:** A path outside the scope that exists, and a path outside the scope
that does not.

**Action:** `file.read` on both.

**Expected:** The same error code. A distinguishable error tells a caller which
paths exist outside the scope, which is an existence oracle for the whole machine.
