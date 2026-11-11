---
maintainer: AI
author: DawsonLin
status: planned-not-executed
---

# Statistics and concurrency

Apply [execution rules](README.md). All cases NOT RUN. Use real independent CLI processes and readiness barriers, not sleep-only race scheduling. Capture exact successful operations and expected counter deltas first.

| ID | Priority / environment | Given | When | Then |
|---|---|---|---|---|
| STAT-01 | P1 I | New tracked object | Create then show/get/get-archive separately | Create write +1; documented read delta once per opened operation; valid timestamps and parseable stat |
| STAT-02 | P1 I | Known counters | Put/archive/update/tag/move separately | Contracted successful-write deltas without nested double counts; no-op/duplicate variants pinned separately |
| STAT-03 | P1 I | Single and mixed-success batched file-tool calls | Read/write/list/exists across subcommands | Per-stream/per-write cardinality pinned beforehand; do not assume one event per top-level batch |
| STAT-04 | P0 I | TRACK_STAT=0 baseline | Read/write/list/search/stat then reenable | Stat bytes unchanged while disabled; resumes when enabled; list/search/stat/with-stat do not count |
| STAT-05 | P1 I | Varying counts, ties and missing read times | stat/top read/write/last_read asc/desc, status/limit, YAML/JSON | Correct ranking/filter/output; tie/missing policy pinned; invalid options rejected |
| STAT-06 | P1 F | Missing/corrupt stat | Stat/with-stat/read | Zero fallback, corruption WARN, no crash/data loss; future successful updates usable |
| STAT-07 | P1 I | Tracked object through deleted/recovered/ceased | Inspect counter changes | Nonactive counters frozen; recovery preserves/resumes; finalization/purge follow retention contract |
| STAT-08 | P0 I | 48 independent reads, healthy store | Barrier-release subprocesses, wait all | Exact +48 read count, correct bytes, no corrupt JSON/lost updates |
| STAT-09 | P0 I | Competing writers with distinct complete byte patterns | Write one file concurrently, control object usable | Final bytes equal one complete allowed version, no mixed/truncated data; statuses/errors captured |
| STAT-10 | P0 I | Two creators with same ID | Simultaneous release | One active success, other collision; coherent payload/record |
| STAT-11 | P0 I | Actual project-compatible exclusive Hash lock held | Put/tag/update/move/delete/recover/GC applicable variants | Serialized or contracted lock error, no unsafe mutation; progress after release |
| STAT-12 | P0 I | READ_LOCK=1 slow open reader | Mutate before/after stream Close/EOF | Shared custody held until stream closure; no leaked lock |
| STAT-13 | P1 I | READ_LOCK=0, tracking off/on | Concurrent reader/writer | No snapshot guarantee invented; tracking may briefly need custody; no deadlock |
| STAT-14 | P0 I | Namespace holder and concurrent create/move/purge | Release controlled schedules | Namespace→object ordering and progress; no identity crossover/orphaned authoritative refs |
| STAT-15 | P0 I | Reader/stat racing with move/delete | Barrier after setup, then race | Status revalidated under custody; nonactive data not mutated/counted improperly; reference remains coherent |
| STAT-16 | P1 I | Blocked child/open archive stream | Interrupt exact owned child, close streams | Lock/process/stream cleanup; next operation works; no broad process termination |
| STAT-17 | P1 I | STAT_FLUSH sync/async, short-lived processes | Write/read then exit/reopen | Supported settings and actual flush behavior recorded; statistics not a durable event ledger |

Traceability: additional live coverage informed by local/manager lock/stat unit cases, which do not substitute for independent CLI-process evidence. Each race requires captured readiness and completion proof. Unsupported platform enforcement is BLOCKED, not a Linux-only claim of portability.
