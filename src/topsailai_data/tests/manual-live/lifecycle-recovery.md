---
maintainer: AI
author: DawsonLin
status: planned-not-executed
---

# Lifecycle and recovery

Apply [execution rules](README.md). All variants NOT RUN. Destructive scenarios use I/C/F only, never P.

| ID | Priority / environment | Given | When | Then |
|---|---|---|---|---|
| LIFE-01 | P0 I | Active object and unrelated controls | Delete once | Deleted metadata, payload/tags/stat retained; normal list/search hide, include-deleted exposes |
| LIFE-02 | P0 I | Deleted object with intact data | Recover and restart | Active with same ID/CreatedAt/content/tags, no source needed; counters resume |
| LIFE-03 | P0 I | Deleted object | Delete again | Whole payload removed, ceased Hash record/tags/lock retained until purge; controls intact |
| LIFE-04 | P0 I/F | All four states | Expand complete operation matrix below | Each command respects state; invalid operation preserves content/status |
| LIFE-05 | P0 F | Creating/deleted/fresh ceased/expired ceased/active controls | Default GC dry-run then execution | Dry-run no business mutation; default removes creating and expired ceased only |
| LIFE-06 | P0 I/F | Mixed states in fresh case root | Targeted GC creating/deleted/ceased variants | Only selected state affected; deleted finalizes; explicit ceased ignores retention; controls intact |
| LIFE-07 | P1 F | Retention 0/default 30; boundary and clearly expired timestamps | Default GC | Fixed timestamp oracle from actual expiry contract; no waiting days or changing system clock |
| LIFE-08 | P1 I | Invalid status/retention, unknown IDs | GC/delete/recover | Clear error, no unintended sweep |
| LIFE-09 | P0 F | Proven write failure after creating publication | Inspect and scoped GC | Invisible incomplete record retained; partial payload and metadata removable without harming controls |
| LIFE-10 | P0 F | Failure before creating record publication | Observe and GC | Recordless remnants not misrepresented as normal candidates; preserve evidence for explicit reconciliation |
| LIFE-11 | P0 F | Payload removal or ceased publication fault | Finalize, remove fault, retry | Error surfaced and deleted retry record retained; retry handles already-missing payload; no false success |
| LIFE-12 | P1 F | Deleted object missing payload and valid external archive | Recover without source, then --from file/in-memory stdin | Missing source refuses unavailable data; valid archive restores intended identity/data; invalid archive does not falsely activate |
| LIFE-13 | P1 I/F | Active/creating/ceased states | Recover with/without source | Refuses nondeleted states, preserves source and record |
| LIFE-14 | P0 C | Verified legacy clone, moved object tree, empty meta | Invoke new CLI, rehearse separately authorized conversion | CLI refuses unsupported layout; no auto-migration claim; conversion checked on copy only |
| LIFE-15 | P0 C | Absolute refs, schema 1/2, old tags/stat and lifecycle records | Convert copy, compare original manifest | Current Hash records/relative refs; preserved tags/status/descriptions/timestamps/stat; no resurrection or original-file overwrite |
| LIFE-16 | P0 C | Complete backup and converted copy | Read via actual skill; rehearse restore on another copy | Counts/IDs/status/tags and every accessible file hash match; backup itself verified; never roll back over subsequent user writes |
| LIFE-17 | P1 I | Purged ceased ID | List/show/get/stat then recreate | Old identity unavailable; fresh create works without stale lock/stat leakage |

## Required state-operation expansion

| State | List/search | Show | Actual reads | Write/update/tag/move | Delete | Recover | GC |
|---|---|---|---|---|---|---|---|
| creating | Hidden in normal discovery | Hidden | Refuse public reads | Internal creation only; no public edits | Refuse | Refuse | Remove partial data/record |
| active | Visible | Metadata/Markdown/tree | Allowed | Allowed under custody | Soft delete | Refuse | Preserve |
| deleted | Include-deleted only | Metadata only | Allowed if payload exists; test file-family reads separately | Refuse | Finalize | Restore with intact payload or valid source | Explicit deleted finalizes |
| ceased | Include-deleted only | Metadata only | Refuse | Refuse | Refuse beyond finalized state | Refuse | Retention or explicit purge |

Expand reads into get/get-archive/file readers; writes into put/put-archive/file writers; include stat inspection. Pin whether creating is exposed in administrative list results from the actual public contract before execution. If docs and public behavior disagree, record an issue, not a pass. Creating/aged states need reviewed fixture setup, not an invented status command. Include unrelated controls in the same isolated root for every GC case.

Traceability: lifecycle-gc.feature, archive-overlap.feature and negative state cases in tag-move/show-update. Added coverage: incomplete publication, retry boundaries, complete public operation matrix and clone recovery. No real-store migration is performed by this plan.
