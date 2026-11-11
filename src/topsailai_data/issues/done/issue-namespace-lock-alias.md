---
maintainer: AI
author: DawsonLin
---
# Namespace lock leaf alias

Static review found AcquireNamespaceLock opens an existing symbolic link and can create a dangling link target. Namespace mutation coordination depends on a stable regular lock leaf. Validate with Lstat before opening, rejecting nonregular leaves, while preserving absent-file creation and inode reuse. Add direct live/dangling link and directory tests. Cooperative locking excludes hostile external concurrent pathname replacement. Runtime layout cutover remains pending.

Status: resolved. Local regression passed at 79.8% package coverage, and focused namespace/metadata lock race tests passed. Complete diff self-reviewed. New live/dangling link and directory fixtures preserve unsafe leaves and target contents. No production layout activation in this unit.
