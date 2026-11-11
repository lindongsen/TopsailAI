---
maintainer: AI
author: DawsonLin
status: planned-not-executed
---

# Files and archives

Apply [execution rules](README.md). All variants NOT RUN. Relative paths in CLI object arguments are deliberately object-relative, not host paths.

| ID | Priority / environment | Given | When | Then |
|---|---|---|---|---|
| FILE-01 | P0 I | Binary/NUL/Unicode/empty fixtures | Put/get through binary-safe files | Exact bytes, length and SHA256; marker writable; restart reads same bytes |
| FILE-02 | P1 I | Nested target, missing object/file, invalid path | Get/put | Nested valid path works; failures do not create stray objects or touch sentinel |
| FILE-03 | P1 I | Known bytes including multibyte text | file read full/seek/negative seek/size -1/zero/beyond EOF | Byte-offset oracle, not character slicing; correct bounds |
| FILE-04 | P1 I | Unknown extension at limit−1/limit/limit+1; whitelisted control | file read default/custom FILE_MAX_BYTES and whitelist *, !* | Correct truncation suffix/limits; get remains raw/untruncated |
| FILE-05 | P1 I | Numbered LF/CRLF/no-final-newline files | read-lines start/end absent/0/-1/positive/invalid negative | One-based numbered output; absent/0 one line, -1 to EOF; boundary errors/empty result match contract |
| FILE-06 | P1 I | Known matches and overlapping contexts | read-around/read-context default/case-sensitive | Colon target/match, hyphen context, clipped bounds, deduplication and case behavior |
| FILE-07 | P1 I | Invalid regex/line/context and empty files | Context readers | Defined empty/error behavior, no panic or mutation |
| FILE-08 | P1 I | Present/missing/empty file mixture | read-files YAML/JSON | Successful entries retained with per-item failures; no whole-batch hiding |
| FILE-09 | P1 I | Known text/bytes | write whole/seek/insert/negative seek; append | Independent byte-model result and size; supported offsets validated |
| FILE-10 | P1 I | --from file/- plus --content and stdin alternatives | write/append/overwrite-lines/insert | --from wins; explicit empty --content wins over stdin; interactive no-source stays empty rather than hangs |
| FILE-11 | P0 I | Freshly read numbered file | overwrite-lines single/range/-1/empty; insert before/after | Exact content and unified diff; reread between edits; invalid boundaries leave data unchanged |
| FILE-12 | P1 I | Present/missing file and folder paths | exists/size; malformed name=path | Per-path booleans, exact byte sizes, useful errors |
| FILE-13 | P1 I | Missing nested folders/existing AGENTS.md/root path | mkdirs/list-dirs | Created levels discoverable; old marker untouched; root skipped; sorted immediate listings, no invented recursive walk |
| FILE-14 | P0 I | Missing/empty/unknown --object, leading slash and escaping path | All file command categories | No host-FS fallback; leading slash object-relative; traversal rejected and outside sentinel unchanged |
| FILE-15 | P1 I | File created with put or file write | Read using other family | Same object data and marker semantics |
| FILE-16 | P0 I | Object with all user fixture names | get-archive and restore to isolated fixture | Byte manifest preserved; actual Hash metadata/locks/stats not exported |
| FILE-17 | P0 I | Tar containing/omitting/replacing marker | put-archive | Supplied marker replaces, absent marker preserved; explicitly verify stale-file replacement contract; no full-object transaction claim |
| FILE-18 | P1 F | Empty/malformed/truncated archive | Create/put-archive | Clear failure; record partial in-object effects without assuming rollback |
| FILE-19 | P0 F | Tar traversal/absolute/link/special-node entries | Apply each archive | No external write/traversal; unsupported entries rejected; capture actual partial effects |
| FILE-20 | P0 F | Destination used as --from, symlink/hardlink aliases | put and applicable file writers | Rejected before truncation; previous destination/status unchanged |
| FILE-21 | P0 F | Archive inside/aliased into target object | put-archive/recover --from | Reject before cleanup/extraction/status changes; original data preserved |
| FILE-22 | P0 F | Fresh/expired nested reserved temp files plus ordinary controls | Show/archive/exists/move then scoped cleanup boundary | Reserved files excluded; only expired reserved files cleaned per contract; fresh/unrelated files and directory symlinks preserved |
| FILE-23 | P1 I/F | Empty directories, long/Unicode names, duplicate tar entries | Archive roundtrip | Supported-format policy and duplicate-entry semantics explicit; no silent payload-loss claim |

Traceability: file-tool.feature, file-archive-marker.feature, same-file-input.feature, archive-overlap.feature. All 13 subcommands appear above. Cross-check source options, formats and negative cases as separate variants, not one aggregate pass.
