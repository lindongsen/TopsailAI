---
maintainer: AI
workspace: /TopsailAI/src/topsailai_data
ProjectFolder: /TopsailAI/src/topsailai_data
ProjectRootFolder: /TopsailAI/src/topsailai_data
ProjectCode: topsailai_data
programming_language: go
---
# Object Stat Observability Design

## Background

The user (DawsonLin) reviewed the "myidea" memory-observability note
(`myidea-memory-observability-hook`) and asked to bring the same idea to
`topsailai_data`: make note-object usage observable through a **usage count**
and a **last-used time**. We track this under the umbrella term **stat**.

Reference note (via `topsailai_data search myidea` /
`show myidea-memory-observability-hook`):

- Track per-entry access frequency and last-access time.
- Distinguish **cite vs query vs update** with separate counters, not one total.
- Do NOT count eager/enumerating reads (they inflate every counter —
  passive prompt-injection noise).
- Per-item stat files under a DOT-HIDDEN directory so enumeration ignores them.
- Deleting an item MUST also delete its observability data (no leftover garbage),
  done under the same lock, with logging.
- Use HUMAN-READABLE LOCAL TIME (e.g. `2026-08-23 15:45:00 +08:00`), not epoch
  millis.
- Counts are a LOWER BOUND, not exact.

## Current Architecture Facts (verified from source)

- Metadata is persisted per-object in `{object_dir}/metadata.json`
  (`pkg/adapters/local/metadata.go`). Despite `docs/DESIGN.md` mentioning a
  central `{ROOT}/topsailai_data.json` index, the implemented local adapter
  does **not** use one; each object carries its own `metadata.json`.
- `models.Object` = `{ID, Name, Path, Description, Tags, Status,
  SchemaVersion, CreatedAt, UpdatedAt, DeletedAt, CeasedAt, DataRef}`.
- Local adapter `ObjectID == object name`; object folder is the boundary.
- Soft-delete lifecycle: `creating → active → deleted → ceased`.
- Read operations (`Get`, `List`, `Search`, `ReadFile`, `ReadArchive`) do NOT
  acquire the object lock by default (`TOPSAILAI_DATA_READ_LOCK=0`).
- Write operations (`Create`, `Update`, `Delete`, `Move`, `WriteFile`,
  `WriteArchive`) acquire the advisory object lock.
- `show` prints metadata + markdown + folder tree. `list`/`search` print
  YAML/JSON arrays. `printObjectTree` filters metadata markers
  (`metadata.json`, `.tags`, `.lock`, `.deleted`, `.ceased`).
- `gc`/purge removes the whole object folder (`os.RemoveAll`), so any stat
  file inside it disappears automatically.

## Design Decisions

### 1. Where to persist stat metrics

Store stat metrics in a **dedicated per-object hidden file**:

```text
{object_dir}/.stat.json
```

Rationale:

- Keeps stat tracking decoupled from `metadata.json`. `metadata.json` is
  rewritten on every metadata mutation; coupling stats into it would force a
  metadata rewrite on every read, contending with writers and disturbing the
  soft-delete markers.
- Mirrors the myidea note's "hidden per-item stat file" guidance, adapted to
  per-object granularity (the note used `story/.stats/{id}.json`; here a single
  dot-file per object is simplest and equally hidden).
- A dot-prefixed file is naturally ignored by the object scan
  (`scanObjects` only looks for `{name}.md` and `metadata.json`) and by
  `printObjectTree` (we add `.stat.json` to the filtered marker suffixes).

Structure:

```json
{
  "schema_version": 1,
  "read_count": 42,
  "last_read_at": "2026-08-24 10:50:31 +08:00",
  "write_count": 7,
  "last_written_at": "2026-08-24 10:33:12 +08:00"
}
```

Timestamps are human-readable local time (RFC3339-with-offset rendered locally),
per the user's stated preference in the myidea note. The model backing this
file is named `ObjectStat` (fields `ReadCount`, `LastReadAt`, `WriteCount`,
`LastWrittenAt`).

### 2. Which operations count

Primary "usage" metric = **read consumption** of actual content:

| Operation | Effect |
|-----------|--------|
| `show <id>` (active) | `read_count++`, `last_read_at=now` |
| `get <id> <file>` | `read_count++`, `last_read_at=now` |
| `get-archive <id>` | `read_count++`, `last_read_at=now` |
| `list` / `search` | **Decided: no per-object increment** (enumeration would inflate every counter) |
| `create` / `put` / `put-archive` | `write_count++`, `last_written_at=now` |
| `update` / `tag add/remove` / `move` | `write_count++`, `last_written_at=now` |

We deliberately keep **two** counters (read vs write) rather than one total,
following the myidea note's "distinguish semantics with separate counters".
The headline "usage count" surfaced to users is `read_count` (plus
`last_read_at`); `write_count` is supplementary context.

Why `list`/`search` are excluded (**resolved decision**): they enumerate many
objects at once and are often driven by tooling/automation, so counting them
would drown real usage signals — the same "eager read inflation" pitfall the
myidea note warns about.

### 3. Backward compatibility

- Bump `models.Object.SchemaVersion` from `1` to `2` for newly created objects.
- Existing objects keep `SchemaVersion: 1` and simply have **no** `.stat.json`
  yet. Absent metrics are handled gracefully: readers report
  `read_count=0`, `last_read_at=<none>`, `write_count=0`, `last_written_at=<none>`.
- The `.stat.json` file is created lazily on the first counted operation, so
  **no bulk migration of existing objects is required**. A lightweight
  migration/backfill is optional (Phase 3) to stamp `schema_version` and seed
  zero-valued stat files.
- Downgrade protection: per `docs/DESIGN.md` §5.4, an older binary opening a
  newer store must refuse. Because stats live in a separate file, older
  binaries can still read `metadata.json`; to honor the contract we bump the
  schema version and enforce the existing "refuse if store is newer" check.
  This is a deliberate trade-off (documented in Trade-offs).

### 4. CLI surface

- **`show <id>`**: add a `Stat:` section showing `ReadCount`, `LastReadAt`,
  `WriteCount`, `LastWrittenAt`. Shown for all statuses (historical stats
  survive soft-delete); for `deleted`/`ceased` it reflects frozen values.
- **`list` / `search`**: add an opt-in `--with-stat` flag that appends
  `read_count` / `last_read_at` columns to YAML/JSON output. Default stays
  lean to avoid bloating everyday listings.
- **New command `stat <id>`**: concise, dedicated view of one object's stat
  metrics (machine-friendly, YAML/JSON via `--format`).
- **New command `stat top`**: rank active objects by usage, supporting
  retention and eviction decisions. Spec below.

#### `stat top` specification

Rank objects by their stat metrics, defaulting to active objects only.

Syntax:

```text
stat top [--by read|write|last_read] [--order desc|asc] [--limit n]
         [--status active|deleted|ceased|all] [--format yaml|json]
```

Flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--by` | `read` | Sort key: `read` (read_count), `write` (write_count), or `last_read` (last_read_at recency). |
| `--order` | `desc` | `desc` = most-used/newest first; `asc` = least-used/oldest first. |
| `--limit` | `10` | Maximum number of rows returned. |
| `--status` | `active` | Filter by lifecycle status. `all` includes deleted/ceased (their frozen stats). |
| `--format` | `yaml` | Output format: `yaml` or `json`. |

Output (YAML default) — a ranked array, each row:

```yaml
- rank: 1
  id: hello
  path: 2026/0714/2323/hello
  status: active
  read_count: 87
  last_read_at: 2026-08-22 09:40:05 +08:00
  write_count: 5
  last_written_at: 2026-08-06 14:12:44 +08:00
```

Sorting semantics:

- `--by read` sorts by `read_count` (ties broken by `last_read_at` desc).
- `--by write` sorts by `write_count` (ties broken by `last_written_at` desc).
- `--by last_read` sorts by `last_read_at` recency (most recently read first
  when `desc`; least recently read first when `asc` — useful for finding
  cold/unused objects).
- Objects with no `.stat.json` are treated as all-zero / never-read and sort to
  the bottom for `desc`, top for `asc`.

### 5. Environment / config knobs

| Variable | Default | Description |
|----------|---------|-------------|
| `TOPSAILAI_DATA_TRACK_STAT` | `1` | Master switch; `0` disables counting (metrics still readable). **Decided: defaults ON.** |
| `TOPSAILAI_DATA_STAT_FLUSH` | `sync` | `sync` (write-through on each op) or `async` (debounced batch flush). |

Follows the project's `TOPSAILAI_DATA_` prefix convention and the
"parameter/parameter-config over scattering env reads" rule (read once in
`config.Load`, pass down).

### 6. Interaction with soft-delete lifecycle and gc

- Only **`active`** objects accumulate stats (matches the lifecycle matrix:
  reads are the usage signal and are only meaningful for active objects).
- On `deleted` / `ceased`, stats are **frozen** (no further increments);
  historical values remain attached to metadata so `show --include-deleted`
  still reveals past usage.
- On `recover` (`deleted → active`), accumulation resumes; historical counts
  are preserved (not reset).
- On `gc` / purge (ceasing removal), the whole object folder is removed via
  `os.RemoveAll`, which automatically removes `.stat.json` — **no leftover
  garbage**. Log the removal (existing file-deletion logging rule).
- `creating` objects never accrue stats (they are invisible and transient;
  `gc` removes them wholesale).

### 7. Concurrency and read-amplification

- Reads today do not take the object lock. Incrementing stats on a read path
  introduces a tiny write. To keep reads cheap and avoid writer contention:
  - Write `.stat.json` atomically (temp file + `os.Rename`), which is atomic
    on POSIX and tolerates concurrent increments (last-writer-wins on
    `last_read_at`; `read_count` is best-effort monotonic).
  - Debounce `last_read_at` (e.g. update at most once per 60s) to reduce
    churn for rapid successive reads.
  - Treat counts as a **lower bound**, never exact (per myidea note), so rare
    lost increments under extreme concurrency are acceptable.
- Optional `async` flush mode batches increments and flushes periodically,
  trading durability for throughput.

### 8. Trade-offs and edge cases

- **Extra write on read path**: mitigated by atomic rename + debounce +
  optional async flush. Cost is negligible for a local-first CLI.
- **Approximate counts**: concurrent increments may occasionally lose a tick;
  acceptable and documented (counts are a lower bound).
- **Downgrade refusal**: bumping schema to 2 means older binaries refuse newer
  stores. Alternative (keep schema at 1, treat stats as purely additive)
  avoids refusal but weakens the schema contract. Chosen: bump to 2 for
  contract fidelity; revisit if seamless downgrade becomes a requirement.
- **Enumeration noise**: `list`/`search` deliberately excluded to protect
  signal quality (resolved decision).
- **Clock skew / local time**: timestamps are wall-clock local time; fine for
  relative recency comparisons, not for cross-machine ordering.
- **Hidden-file hygiene**: `.stat.json` must be added to the
  `printObjectTree` marker-filter list so it never appears in `show`'s folder
  tree.

### 9. Phased rollout

- **Phase 1 (MVP)**:
  - Add `ObjectStat` model + `.stat.json` read/write helpers in the local
    adapter.
  - Wire increments into manager read/write paths (`show`, `get`,
    `get-archive`, `create`, `put`, `put-archive`, `update`, `tag`, `move`).
  - Bump `SchemaVersion` to 2; graceful absence handling.
  - Extend `show` with a `Stat:` section; add `stat <id>` command.
  - Ensure `gc`/purge removes `.stat.json` (free via `RemoveAll`) with logging.
  - Unit tests (>93% coverage on new paths) + integration tests.
- **Phase 2**:
  - `--with-stat` on `list`/`search`; `stat top` ranking.
  - `TOPSAILAI_DATA_TRACK_STAT` / `TOPSAILAI_DATA_STAT_FLUSH` knobs.
  - Async/debounced flush.
- **Phase 3**:
  - Optional backfill/migration to stamp schema and seed zero stat files.
  - Aggregation/reporting (e.g. unused-object sweep leveraging stat data).
  - Reconciliation: purge orphan `.stat.json`, quarantine corrupt ones.

## Resolved Decisions

The following were previously open questions and are now settled by the human:

1. **Terminology**: the feature is referred to as **stat** (not "usage")
   throughout. Hidden file `.stat.json`, commands `stat <id>` and `stat top`,
   env var `TOPSAILAI_DATA_TRACK_STAT`, and flag `--with-stat`. The two
   counters (read vs write) are kept conceptually under the stat umbrella,
   with field names `read_count`/`last_read_at`/`write_count`/`last_written_at`.
2. **`list`/`search` are NOT counted**: enumeration is excluded from stat
   tracking to protect signal quality.
3. **Independent `top` ranking command**: `stat top` ranks objects by
   `read_count` / recency, with `--by`, `--order`, `--limit`, `--status`
   (default active only), and `--format` options (spec in §4).
4. **`TOPSAILAI_DATA_TRACK_STAT` defaults ON**: enabled by default, with an
   off-switch knob (`0`) to disable counting while keeping metrics readable.
