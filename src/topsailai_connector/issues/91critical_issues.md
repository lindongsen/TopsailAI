---
maintainer: AI
author: DawsonLin
status: open
severity: critical
created: 2026-11-13
---

# Critical incidents

## INC-001: A cleanup script deleted the whole `Documents` folder on a test host

### What happened

While cleaning up a Windows test environment, a cleanup script deleted
`C:\Users\Administrator\Documents` entirely, including a pre-existing folder
named `My Own Folder` that had nothing to do with this project.

The folder was not recoverable: `Remove-Item -Force` bypasses the Recycle Bin,
the host has no volume shadow copies, and it has no restore points.

### Root cause

The cleanup script built its target list like this:

```powershell
$name = -join ([char]26032, [char]32, [char]25991, [char]20214, [char]22841)
$targets = @(
  "C:\final-test",
  "C:\Users\Administrator\Documents\" + $name,
  ...
)
```

PowerShell parses `"C:\Users\Administrator\Documents\" + $name` as a single
expression inside the array literal, but the trailing backslash before the
closing quote escapes the quote. The resulting first element is the string
`C:\Users\Administrator\Documents\` with the `+ $name` part dropped, so the
array held the parent directory instead of the child.

The deletion loop then ran `Remove-Item -LiteralPath $t -Recurse -Force` on
that parent path.

### Why it was not caught

1. The script printed `removed C:\Users\Administrator\Documents\` and the
   non-ASCII child name was invisible in the console, so the log line looked
   like it named the child folder.
2. The residue check that followed only asked whether connector processes,
   scheduled tasks and the port were gone. It never asserted that unrelated
   directories still existed.
3. The deletion was performed with `-Force`, which removes the Recycle Bin as a
   safety net, on a host that is not the developer's own machine.

### Impact

A pre-existing user folder on a shared test host was destroyed permanently.
No project data was lost, because the folder was unrelated to this project, but
the loss is real and irreversible.

### What was done

- `C:\Users\Administrator\Documents` was recreated as an empty directory so the
  profile is not left in a broken state.
- The lost contents were reported to the human rather than silently omitted.

### Prevention

These rules apply to every future cleanup script, on any host:

1. **Never build a path by string concatenation inside an array literal.** Use
   `Join-Path`, which cannot silently drop a component.
2. **Delete only paths this task created.** Record each created path when it is
   created and delete exactly that list. Never delete a parent directory that
   existed before the task started.
3. **Assert before deleting.** For every target, print the resolved absolute path
   and its codepoints, and refuse to delete a path whose parent is a known user
   directory such as `Documents`, `Desktop` or the profile root.
4. **Never use `-Force` on a directory this task did not create.** `-Force`
   removes the Recycle Bin as a recovery path.
5. **Verify unrelated data survived.** A cleanup check must assert that
   pre-existing directories still exist, not only that the task's own artifacts
   are gone.
6. **Prefer a dedicated scratch root.** Create one directory such as
   `C:\connector-verify-<timestamp>` and put every artifact under it, so cleanup
   is a single deletion of a directory this task created.
