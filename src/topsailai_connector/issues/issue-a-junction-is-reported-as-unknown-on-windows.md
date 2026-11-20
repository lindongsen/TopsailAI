---
maintainer: AI
author: DawsonLin
status: open
severity: low
created: 2026-11-20
---

# A junction is reported as `unknown` instead of a link on Windows

## Symptom

`file.stat` on a junction returns `success` with `type unknown` and
`is_symlink false`, so a caller cannot tell a junction from an unreadable file.
`file.read` and `file.list` through the same junction are correctly `denied`, so the
fence holds; only the reported metadata is wrong.

Measured on the Windows host with scope `desk` covering
`C:\Users\Administrator\Desktop`, on a junction
`win-scope\plainjunc -> C:\Users\Administrator\outside-plain`:

```
file.stat  win-scope/plainjunc
  -> rc=0
     name          plainjunc
     type          unknown
     size          0
     mode          ?rw-rw-rw-
     modified_at   1795129019488
     is_symlink    false

file.read  win-scope/plainjunc/secret.txt
  -> rc=1  denied: the node refused the operation

file.list  win-scope/plainjunc
  -> rc=1  denied: the node refused the operation
```

The same result was measured on a junction at depth 4 pointing at `C:\Windows`
(`win-scope/deep/a/b/c/junc`): `type unknown`, `is_symlink false`, `size 0`,
`rc=0`, while `read` and `list` were `denied`.

`file.list` on the parent reports the junction as an entry of type `unknown`:

```
file.list  win-scope
  -> a.txt        file   36
     copy.exe     file   9607168
     deep         dir    0
     plainjunc    unknown 0
```

## Root cause

`describe` and `typeOf` in `internal/node/fence.go` classify a link by
`info.Mode()&os.ModeSymlink`. On Windows, `os.Lstat` on a junction does not set
`ModeSymlink`; it sets `ModeIrregular`, which renders as a `?` prefix in the mode
string.

Measured with a probe binary built for `windows/amd64` and run on the host:

```
C:\...\win-scope\plainjunc
  mode=?rw-rw-rw-  isDir=false isRegular=false isSymlink=false size=0
  ModeIrregular=true ModeDir=false

C:\...\win-scope\deep\a\b\c\junc
  mode=?rw-rw-rw-  isDir=false isRegular=false isSymlink=false size=0
  ModeIrregular=true ModeDir=false

C:\...\win-scope\a.txt
  mode=-rw-rw-rw-  isRegular=true isSymlink=false size=36

C:\...\win-scope\deep
  mode=drwxrwxrwx  isDir=true ModeDir=true
```

So `typeOf` reaches its `default` branch and returns `unknown`, and `IsSymlink` is
false. The `Readlink` branch in `Stat` is also skipped, because it is guarded by the
same `ModeSymlink` test, so `link_target` is never populated for a junction.

On Linux the same code is correct: `os.Lstat` on a symlink returns
`mode=Lrwxrwxrwx isSymlink=true size=10`, so `typeOf` returns `symlink` and
`IsSymlink` is true.

## Why it was not caught

- The Windows path rules are covered by a test binary that is compiled on the build
  host (`make test-windows-compile`), but the junction classification is not
  asserted there. The live Windows evidence in `docs/permission-design.md` records
  that `file.stat` on a junction "returned `success` reporting the link without
  following it", which reads as correct and does not state the reported type.
- The Linux tests assert `IsSymlink` for a symlink and pass, so the shared code
  looks covered. The defect is a platform difference in what `Lstat` reports, which
  a Linux test cannot observe.
- The design document's Windows table says "Junctions and reparse points: a junction
  is a directory symlink", which is true of the fence and not true of the metadata.

## Consequence

A caller cannot distinguish a junction from an unreadable file, and cannot see where
a junction points. The security boundary is unaffected: every operation through a
junction that escapes the scope is refused, and a junction that resolves to a denied
directory is refused as well.

The consequence is a wrong answer rather than a leak, which is why the severity is
low. It matters because `docs/permission-design.md` promises that an escaping link
"is still reported as a link without being followed", and on Windows that promise is
not kept.

## Options

| Option | Effect | Cost |
|---|---|---|
| Treat `ModeIrregular` as a link on Windows | `type symlink`, `is_symlink true`, and `Readlink` attempted | `ModeIrregular` is also set for other unusual files, so the classification would be a guess unless it is narrowed |
| Read the reparse tag through `golang.org/x/sys/windows` | Exact answer: a junction, a symlink or another reparse point | Adds the project's second third-party dependency, which needs human approval |
| Report `unknown` and document it | No code change | The documented `file.stat` behaviour stays untrue on Windows |
| Return `denied` for a junction instead of reporting it | Consistent with the deny list answering by identity | Hides a legitimate directory entry the operator created |

The second option is the only exact one. The first is cheap and approximate. The
choice depends on whether the project accepts a second dependency, which is the same
decision blocking `issues/issue-windows-identity-file-not-protected.md`.

## Verification required

- A test that asserts the reported type and `is_symlink` for a junction on Windows,
  so the answer is measured on the platform where it differs.
- A test that a junction resolving to a denied directory is still refused by all
  three operations, so a change to the classification does not weaken the fence.
- `docs/permission-design.md` must state the reported type, not only that the link is
  reported, so the document and the behaviour agree.
