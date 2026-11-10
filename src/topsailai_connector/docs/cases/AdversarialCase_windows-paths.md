---
maintainer: AI
author: DawsonLin
---

# Adversarial Cases: Windows Paths

Windows is a supported platform in the first version. The fence is the same
`os.Root` handle, so what differs is the set of names that mean something other
than they appear.

These cases run on Windows only. A case that cannot run on the current platform is
skipped with a reason, never silently passed.

## Reserved device names

### AC-WIN-1: `NUL`

**Action:** `file.read` on `NUL`.

**Expected:** `invalid_argument`. `NUL` resolves to a device regardless of
directory, so a path component named `NUL` is not a file in the scope.

### AC-WIN-2: `CON`

**Action:** `file.read` on `CON`.

**Expected:** `invalid_argument`.

### AC-WIN-3: `COM1`

**Action:** `file.read` on `COM1`.

**Expected:** `invalid_argument`.

### AC-WIN-4: `LPT1`

**Action:** `file.read` on `LPT1`.

**Expected:** `invalid_argument`.

### AC-WIN-5: A reserved name with an extension

**Action:** `file.read` on `NUL.txt`.

**Expected:** `invalid_argument`. Windows resolves `NUL.txt` to the device, so the
extension does not make it a file.

### AC-WIN-6: A reserved name in a subdirectory

**Action:** `file.read` on `sub/NUL`.

**Expected:** `invalid_argument`. The name is reserved in every directory.

### AC-WIN-7: A reserved name in lower case

**Action:** `file.read` on `nul`.

**Expected:** `invalid_argument`. Windows is case-insensitive, so `nul` is `NUL`.

### AC-WIN-8: A reserved name with trailing spaces

**Action:** `file.read` on `NUL `.

**Expected:** `invalid_argument`. Windows strips the space, so the checked name and
the opened name would differ.

## Alternate data streams

### AC-WIN-9: A named stream

**Action:** `file.read` on `inside.txt:hidden`.

**Expected:** `invalid_argument`. A colon introduces a stream, which is a hidden
file attached to a visible one.

### AC-WIN-10: The default stream

**Action:** `file.read` on `inside.txt::$DATA`.

**Expected:** `invalid_argument`.

### AC-WIN-11: A stream on a directory

**Action:** `file.read` on `sub:stream`.

**Expected:** `invalid_argument`.

## Trailing dots and spaces

### AC-WIN-12: A trailing dot

**Action:** `file.read` on `inside.txt.`.

**Expected:** `invalid_argument`. Windows strips the dot, so `inside.txt.` opens
`inside.txt`.

### AC-WIN-13: Multiple trailing dots

**Action:** `file.read` on `inside.txt...`.

**Expected:** `invalid_argument`.

### AC-WIN-14: A trailing space

**Action:** `file.read` on `inside.txt `.

**Expected:** `invalid_argument`.

### AC-WIN-15: A trailing dot on a directory

**Action:** `file.list` on `sub.`.

**Expected:** `invalid_argument`.

### AC-WIN-16: A dot-only component

**Action:** `file.read` on `sub/./inside.txt`.

**Expected:** `invalid_argument`. The `.` component is rejected on every platform.

## Case insensitivity

### AC-WIN-17: A deny-list entry bypassed by case

**Precondition:** The identity file is `Identity` inside a scope.

**Action:** `file.read` on `identity`.

**Expected:** `unauthorized`. A case-sensitive deny-list comparison would be
bypassed by changing the case, and on Windows the two names are the same file.

### AC-WIN-18: A deny-list entry bypassed by mixed case

**Action:** `file.read` on `IdEnTiTy`.

**Expected:** `unauthorized`.

### AC-WIN-19: A legitimate file read with different case

**Precondition:** `inside.txt` exists.

**Action:** `file.read` on `INSIDE.TXT`.

**Expected:** Allowed, and the content is returned. Case insensitivity is a
filesystem property, not an attack, so the fence must not refuse a legitimate file.

## Junctions and reparse points

### AC-WIN-20: A junction to an outside directory

**Precondition:** `<tmp>\scope\junc` is a junction to `<tmp>\outside`.

**Action:** `file.read` on `junc\secret.txt`.

**Expected:** Refused by the fence. A junction is a directory symlink, so the same
`os.Root` rule applies.

### AC-WIN-21: A junction that stays inside

**Precondition:** `<tmp>\scope\junc` is a junction to `<tmp>\scope\sub`.

**Action:** `file.read` on `junc\inside.txt`.

**Expected:** Allowed. A junction that does not escape is a legitimate directory.

### AC-WIN-22: A symlink to an outside file

**Precondition:** `<tmp>\scope\outlink` is a symlink to `<tmp>\outside\secret.txt`.

**Action:** `file.read` on `outlink`.

**Expected:** Refused by the fence.

## Path prefixes

### AC-WIN-23: A drive-relative path

**Action:** `file.read` on `C:inside.txt`.

**Expected:** `invalid_argument`. A drive-relative path resolves against the current
directory on that drive, which is not the scope.

### AC-WIN-24: An absolute path with a drive letter

**Action:** `file.read` on `C:\Windows\win.ini`.

**Expected:** `invalid_argument`.

### AC-WIN-25: A UNC path

**Action:** `file.read` on `\\server\share\secret.txt`.

**Expected:** `invalid_argument`.

### AC-WIN-26: An extended-length path

**Action:** `file.read` on `\\?\C:\Windows\win.ini`.

**Expected:** `invalid_argument`.

### AC-WIN-27: An extended UNC path

**Action:** `file.read` on `\\?\UNC\server\share\secret.txt`.

**Expected:** `invalid_argument`.

### AC-WIN-28: A device path

**Action:** `file.read` on `\\.\PhysicalDrive0`.

**Expected:** `invalid_argument`.

### AC-WIN-29: A root-relative path

**Action:** `file.read` on `\Windows\win.ini`.

**Expected:** `invalid_argument`. A leading backslash is absolute on the current
drive.

## Short names

### AC-WIN-30: A short name for a directory inside the scope

**Precondition:** `<tmp>\scope\Program Files` exists.

**Action:** `file.read` on `PROGRA~1\inside.txt`.

**Expected:** Allowed if the short name resolves inside the root, refused if it does
not. `os.Root` resolves it inside the root, so it cannot escape.

### AC-WIN-31: A short name that resolves outside

**Precondition:** A short name that resolves to a directory outside the scope.

**Action:** `file.read` on the short name.

**Expected:** Refused by the fence.

## Separators

### AC-WIN-32: A forward slash

**Action:** `file.read` on `sub/inside.txt`.

**Expected:** Allowed. Windows accepts both separators, and the fence resolves it
inside the root.

### AC-WIN-33: A backslash

**Action:** `file.read` on `sub\inside.txt`.

**Expected:** `invalid_argument`. The backslash rule rejects it on every platform, so
a request cannot mean one thing on Windows and another on POSIX.

**Note:** this is deliberately stricter than Windows itself. Accepting a backslash
on Windows and refusing it on POSIX would make the same request mean two things,
which is the defect the rule exists to prevent.

### AC-WIN-34: A mixed separator traversal

**Action:** `file.read` on `..\outside\secret.txt`.

**Expected:** `invalid_argument`.

### AC-WIN-35: A doubled separator

**Action:** `file.read` on `sub\\inside.txt`.

**Expected:** `invalid_argument` or `not_found`. A doubled separator is a name the
policy author did not write.

## Long paths

### AC-WIN-36: A path over `MAX_PATH`

**Action:** `file.read` on a path of 300 characters.

**Expected:** Either it works, because the Node uses the extended-length form
internally, or it fails with a clear error. It must not fail with a confusing
"file not found" that hides a length limit.

### AC-WIN-37: A path over the Node's own limit

**Action:** `file.read` on a 100 KiB path.

**Expected:** `invalid_argument`. The Node's limit is applied before the filesystem
is touched, so the platform limit is never reached.

## Permissions

### AC-WIN-38: A file the Node's user cannot read

**Precondition:** A file inside the scope with an ACL that denies the Node's user.

**Action:** `file.read` on it.

**Expected:** `unauthorized` or `not_found`, and the error does not reveal whether
the file exists. A "permission denied" that differs from "not found" is an existence
oracle.

### AC-WIN-39: A file with an owner-only ACL

**Precondition:** A file readable only by the Node's user.

**Action:** `file.read` on it.

**Expected:** Allowed. The fence bounds the path, not the permission, so a file the
Node's user may read is readable.

## The identity file

### AC-WIN-40: The identity file is not readable through a scope

**Precondition:** The identity file is inside a scope directory.

**Action:** `file.read` on its relative path.

**Expected:** `unauthorized`. This is the case that matters most on Windows too: the
file holds the `node-token`.

### AC-WIN-41: The identity file reached by a junction

**Precondition:** A junction inside the scope points at the config directory.

**Action:** `file.read` on the junction path.

**Expected:** `unauthorized`. The deny list is compared against the resolved path.

### AC-WIN-42: The identity file reached by a short name

**Precondition:** The config directory has a short name.

**Action:** `file.read` on the short-name path.

**Expected:** `unauthorized`. A deny list compared against the raw string would be
bypassed by any alias the filesystem accepts.

## Platform independence

### AC-WIN-43: The same request means the same thing on both platforms

**Action:** Run the traversal, absolute-path and separator cases on Windows and on
POSIX, and compare the error codes.

**Expected:** The error codes match. A request that is refused on Linux and allowed
on Windows is a defect, because the policy author wrote one policy for both.

### AC-WIN-44: A POSIX-only name is not special on Windows

**Action:** `file.read` on `a:b` on POSIX.

**Expected:** `invalid_argument`. The colon rule applies on POSIX too, so a name that
is special on Windows is refused everywhere rather than only where it matters.

## What these cases do not cover

- A Windows-specific filesystem that is not NTFS, such as a FAT32 mount. The
  reserved-name and stream rules are NTFS properties, and a FAT32 scope would behave
  differently. The design states that a scope should be on NTFS.
- A network share as a scope root. The design refuses a UNC path as a scope root,
  because the fence's guarantees depend on the local filesystem.
- A reparse point that is not a junction or a symlink, such as a deduplication
  point. `os.Root` treats it as a reparse point, and the behaviour is the platform's
  rather than this project's.
