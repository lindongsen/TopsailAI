---
maintainer: AI
author: DawsonLin
---
# Empty payload parents retained during cutover

Move and creating/ceased cleanup tests expose empty classification directories left behind after payload deletion. The new local Delete removed the whole payload but omitted the former bounded parent cleanup; obsolete test paths initially hid this omission. Restore RemoveEmptyParents bounded by object/, log each successful removal, propagate failures so lifecycle metadata remains retryable, and verify local and manager regressions.

Status: resolved. `RemoveEmptyParents` is restored and called from the local `Delete` path, bounded by `{root}/object`, logging every removed parent and propagating failures so lifecycle metadata stays retryable. Verified by `TestRemoveEmptyParents`, `TestRemoveEmptyParentsStopsAtRoot` and `TestRemoveEmptyParentsNeverRemovesRoot`, plus a live check where a `deepobj` object created under classify `a/b/c` left no empty classification directory after delete and finalization; only the `object/` root itself remained.
