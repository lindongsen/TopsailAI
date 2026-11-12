---
maintainer: AI
author: DawsonLin
---
# Payload interior alias containment

Source inspection found that local single-file operations validate lexical names but follow existing interior symbolic links. Object-reference validation stops at the object directory, so a manually introduced interior link can redirect reads or writes outside payload custody. Archive extraction also needs safe existing-node validation. This is source-confirmed risk, not an executed exploit report.

The coherent cutover must reject unsafe existing path components, preserve source-equals-destination errors, and verify outside sentinel preservation. Caller-held locks serialize cooperative processes; this check does not defend against hostile concurrent filesystem replacement.

Status: resolved. `resolvePayloadFile` walks every existing path component with `Lstat` and rejects symbolic links, non-directory parents and special nodes before any file access. Single-file read and write, the mandatory marker check, move and archive extraction all route through it, so archive entries are validated before they are written. Source-equals-destination rejection is preserved and covered by `TestActualDataAdapterWriteFileRejectsSameFileAliases` for exact, symlink and hard-link aliases. `TestActualCutoverInteriorAlias` and `TestActualCutoverArchiveMarkerAlias` cover the interior alias cases. A live check placed a symlink inside an object payload pointing at an outside directory; both `put` and `get` through that link were rejected with `payload alias ... invalid path` and the outside file content was unchanged.
