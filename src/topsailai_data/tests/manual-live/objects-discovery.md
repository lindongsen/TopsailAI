---
maintainer: AI
author: DawsonLin
status: planned-not-executed
---

# Objects and discovery

Apply [execution rules](README.md). All cases NOT RUN; every row expands into listed variants.

| ID | Priority / environment | Given | When | Then |
|---|---|---|---|---|
| OBJ-01 | P0 I | Markdown, explicit description, classify, repeated tags | Create/show/restart | Active object, exact marker bytes, deduplicated tags, local-time path, stable ID |
| OBJ-02 | P1 I | Leading YAML description | Create without description, then explicit override variant | String fallback works; explicit description wins |
| OBJ-03 | P1 I | Missing/malformed/non-string/empty/non-leading frontmatter and empty input | Create without explicit description | Appropriate rejection, no active object; explicit-description variants distinguish fallback failure from payload validity |
| OBJ-04 | P1 I | Frontmatter ending before/at/after 8 KiB | Create | Bounded leading-prefix extraction; byte-position expectations fixed beforehand |
| OBJ-05 | P1 I | External plain/tar source and complete in-memory stdin | Create via each source | Equivalent valid content; file sources use --from; no input stream reused for prompts |
| OBJ-06 | P0 I/F | Existing active/deleted/creating ID, different classify | Create same ID | Global duplicate rejection; previous content/state/identity/tags preserved |
| OBJ-07 | P1 I | Ceased ID | Create same ID | Purges old ceased identity under custody and creates intended new active content; controls unchanged |
| OBJ-08 | P1 I | Empty/traversal/separator/reserved/Unicode names and classify segments | Create each | Supported spellings round-trip; invalid names rejected; document platform case semantics |
| OBJ-09 | P1 I | Proposed depth 11 and 12 | Create | 11 allowed, 12 rejected; root excluded and object included in depth |
| OBJ-10 | P0 I | Created object and authorized read-only observer | Check layout | SHA256(ID) aa/bb/cc/fullhash leaf; tag-free metadata.json and independent tags; Path=DataRef relative to object/; no meta/classify |
| OBJ-11 | P0 I | Payload metadata.json/stat.json/.stat.json/name.lock/name.tags | Put/show/get/list-dirs | Ordinary visible user data; real Hash metadata unaffected |
| OBJ-12 | P1 I | Nested marker-like Markdown inside object | List/search/get | Nested content not another object; inventory comes from Hash records |
| OBJ-13 | P1 I | Active description and timestamp baseline | Update text/clear with explicit empty/no-description variant | Correct description contract, valid UpdatedAt, stable ID/CreatedAt/tags/content |
| OBJ-14 | P1 I | Unknown/deleted/ceased object | Update | Refuses mutation and preserves data |
| OBJ-15 | P1 I | Active object with no extras, then Unicode nested extras | Show | Metadata/Markdown/tree correct; Hash internals absent; mandatory marker and actual user data presented consistently |
| OBJ-16 | P1 I | Empty and populated stores | List/search YAML/JSON | Parseable arrays, correct snake_case fields, [] for empty, diagnostics separate on stderr |
| OBJ-17 | P1 I | Distinct and tied time prefixes | List/search asc/desc/default with offset/limit/zero/unmatched pages | Correct stable-store ordering and pagination; pin tie/zero semantics before run; no lost/duplicate entries |
| OBJ-18 | P1 I | Separate terms in name/tag/classify, content-only control | Search mixed-case substring and quoted OR query | Supported fields match case-insensitively, OR union deduplicated; no claimed internal-file full-text indexing |
| OBJ-19 | P1 I | Spaces/tabs/backslashes, empty OR terms, invalid format/sort/pagination | Search/list | Supported parser semantics or clear rejection; no business mutation; quote OR so shell does not create pipeline |
| OBJ-20 | P1 I | Overlapping object tags | List --tag single/multiple | Expected filter semantics fixed from contract before run; correct pagination/format |
| OBJ-21 | P0 I | Object tags and former classify tag fixture | Add duplicate/remove present/remove absent; move | Idempotence and stable tags; no inherited classify tags; other objects unchanged |
| OBJ-22 | P1 I | Empty/whitespace/comment/control/oversized tag candidates | Create/tag | Valid tags round-trip; invalid stored-line values rejected without malformed tag record |
| OBJ-23 | P0 I | Object with byte manifest and tags/stat | Move then restart | ID/Name/CreatedAt/tags/hashes preserved; new relative ref authoritative; old source cleaned after publication |
| OBJ-24 | P0 I | Occupied/invalid/deep/nested-object destination | Move | Rejection without changing source or unrelated target |

Traceability: create.feature, show-update.feature, list-search.feature, tag-move.feature, smoke.feature. New live coverage: Hash metadata, independent tags, relative references, no inheritance and user/internal name separation.
