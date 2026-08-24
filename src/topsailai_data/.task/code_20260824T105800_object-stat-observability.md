---
maintainer: AI
workspace: /TopsailAI/src/topsailai_data
ProjectFolder: /TopsailAI/src/topsailai_data
ProjectRootFolder: /TopsailAI/src/topsailai_data
ProjectCode: topsailai_data
programming_language: go
---
# Code Proposal: Object Stat Observability

Reference design: `.task/plan_20260824T104900_object-usage-observability.md`
(recently renamed terminology to **stat**).

Goal: track per-object usage via a hidden `{object_dir}/.stat.json` carrying
`read_count`, `last_read_at`, `write_count`, `last_written_at`; expose it
through `show`, `stat <id>`, `stat top`, and opt-in `--with-stat` on
`list`/`search`; gate counting behind `TOPSAILAI_DATA_TRACK_STAT` (default ON).

## Verified architecture facts driving the design

- Metadata is per-object `{object_dir}/metadata.json`
  (`pkg/adapters/local/metadata.go`). No central index in the implemented
  local adapter.
- `models.Object` = `{ID, Name, Path, Description, Tags, Status,
  SchemaVersion, CreatedAt, UpdatedAt, DeletedAt, CeasedAt, DataRef}`.
- Local adapter `ObjectID == object name`; object folder is the boundary.
- Reads (`Get`, `List`, `Search`, `ReadFile`, `ReadArchive`) do NOT take the
  advisory lock by default (`TOPSAILAI_DATA_READ_LOCK=0`); writes do.
- Marker filtering lives in TWO places that must both learn about `.stat.json`:
  - `pkg/adapters/local/actual.go`: `metadataMarkerNames` /
    `metadataMarkerSuffixes` (protect stat file from actual-data ops).
  - `pkg/cli/commands.go`: `isMetadataMarkerName` (hide from `show` tree).
- `gc`/purge removes the whole object folder via `os.RemoveAll`, so
  `.stat.json` is removed automatically (needs a log line per deletion rule).
- `move` copies the whole folder (`copyDir`), so `.stat.json` travels with the
  object automatically.
- Config is loaded once in `pkg/config/config.go` and passed down; new knobs
  belong there (respect "params over scattered env reads").
- Errors are centralized in `pkg/errors/errors.go`.

## Logical change units (ONE per implementation turn)

### UNIT 1 — Model + schema version
Files:
- `pkg/models/models.go`

Points:
- Add `ObjectStat` struct:
  ```go
  type ObjectStat struct {
      SchemaVersion int        `json:"schema_version"`
      ReadCount     int64      `json:"read_count"`
      LastReadAt    *time.Time `json:"last_read_at,omitempty"`
      WriteCount    int64      `json:"write_count"`
      LastWrittenAt *time.Time `json:"last_written_at,omitempty"`
  }
  ```
  Timestamps nullable pointers so "never read/written" renders as absent.
- Add a constant for the stat file schema version (e.g.
  `ObjectStatSchemaVersion = 1`).
- Introduce a `SchemaVersion` bump constant for objects: currently
  `CreateObject` hardcodes `SchemaVersion: 1` in the manager. Centralize a
  `CurrentSchemaVersion = 2` in models and use it at creation. Existing
  objects keep whatever version they were created with (no forced rewrite).
- Add a clone/helper if needed for stat aggregation.

### UNIT 2 — Per-object `.stat.json` persistence in the local adapter
Files:
- `pkg/adapters/local/stat.go` (NEW)
- `pkg/adapters/local/actual.go` (edit marker lists)

Points:
- New file `stat.go` with:
  - `statFileName = ".stat.json"`.
  - `StatFilePath(objectDir string) string`.
  - `ReadStat(objectDir string) (*models.ObjectStat, error)` — returns a
    zero-valued `ObjectStat` when the file is absent (graceful, no error).
  - `WriteStat(objectDir string, st *models.ObjectStat) error` — atomic
    temp-file + `os.Rename`; marshal with `json.MarshalIndent`.
  - `IncrementRead(objectDir string, now time.Time, debounce time.Duration)
    error` — read-modify-write, bumps `ReadCount`, updates `LastReadAt`
    respecting debounce (skip if last read within debounce window).
  - `IncrementWrite(objectDir string, now time.Time) error` — bumps
    `WriteCount`, updates `LastWrittenAt`.
  - A `TrackEnabled` guard is NOT baked here; the manager decides whether to
    call these (keeps adapter pure and testable).
- Edit `actual.go`:
  - Add `".stat.json"` to `metadataMarkerNames` so actual-data
    read/write/delete/archive operations treat it as reserved metadata and
    never ship it in archives or wipe it during `clearActualData`.
  - `validateActualFilename` already rejects reserved markers via
    `isMetadataMarker`, so `.stat.json` cannot be written as a user file.

### UNIT 3 — Manager orchestration of stat increments
Files:
- `pkg/manager/manager.go`
- `pkg/config/config.go` (knob plumbing, see UNIT 5; referenced here)

Points:
- Add fields to `Manager`: `trackStat bool`, `statFlushSync bool`,
  `statDebounce time.Duration` populated from `cfg` in `New`.
- Add private helpers:
  - `recordRead(ctx, id) error` — resolve active object dir, call
    `local.IncrementRead` when `trackStat` is on; swallow/log errors (best
    effort, counts are a lower bound).
  - `recordWrite(ctx, id) error` — analogous with `IncrementWrite`.
- Wire increments (only when object is `active`):
  - READS → `recordRead`:
    - `GetObject` — BUT careful: `GetObject` is called internally by many
      write paths and by `show`. To avoid double counting and counting
      internal probes, do NOT hook `GetObject` generically. Instead hook the
      user-facing read entry points:
      - `ReadActualFile` (serves `get`)
      - `ReadActualArchive` (serves `get-archive`)
      - `show` path: `runShow` calls `GetObject` then `ReadActualFile` for the
        markdown. Counting `ReadActualFile` already covers `show`'s content
        read. Decision: count `show` via the `ReadActualFile` call it makes;
        do not additionally count the bare `GetObject` metadata fetch (that
        would double-count and also fire on internal calls).
  - WRITES → `recordWrite`:
    - `CreateObject` (after activation)
    - `UpdateObject`
    - `UpdateActualData` (put-archive)
    - `WriteActualFile` (put)
    - `AddTag` / `RemoveTag`
    - `MoveObject`
- IMPORTANT: `list`/`search` (`ListObjects`, `SearchObjects`) are NOT hooked
  (resolved decision).
- `RestoreObject` (recover) does NOT increment; it only resumes future
  accumulation (historical counts preserved because `.stat.json` survives
  soft-delete).
- `DeleteObject`/`GC` do NOT increment; they freeze stats (see UNIT 6).

### UNIT 4 — CLI commands: `stat`, `stat top`, `show` Stat section, `--with-stat`
Files:
- `pkg/cli/cli.go`
- `pkg/cli/commands.go`

Points:
- `cli.go`:
  - Register `{Name: "stat", Usage: "stat <id> | stat top [...]", Run: runStat}`.
  - Add `TOPSAILAI_DATA_TRACK_STAT` and `TOPSAILAI_DATA_STAT_FLUSH` to the
    printed environment-variable help.
- `commands.go`:
  - `runStat(ctx, mgr, args)`:
    - Route to `runStatTop` when `args[0]=="top"`, else `runStatOne`.
  - `runStatOne`: `stat <id> [--format yaml|json]` — fetch the object's stat
    via a new manager accessor `GetStat(ctx, id)` (returns `*models.ObjectStat`
    even for deleted/ceased, reflecting frozen values; absent → zeros). Print
    a `Stat:` block (human) or YAML/JSON.
  - `runStatTop`: `stat top [--by read|write|last_read] [--order desc|asc]
    [--limit n] [--status active|deleted|ceased|all] [--format yaml|json]`.
    - Fetch candidate objects via `mgr.ListObjects` with `IncludeDeleted` =
      status==all||deleted||ceased, then filter by requested status.
    - For each, load stat via `GetStat`.
    - Rank per design §4 (ties broken by recency; missing `.stat.json` →
      zeros, sort bottom on desc / top on asc).
    - Emit ranked rows `{rank,id,path,status,read_count,last_read_at,
      write_count,last_written_at}` in YAML/JSON.
  - `runShow`: after `printObject(obj)`, print a `Stat:` section fetched via
    `GetStat` (shown for all statuses; frozen for deleted/ceased).
  - `runList`/`runSearch`: add `--with-stat` bool flag; when set, append
    `read_count`/`last_read_at`/`write_count`/`last_written_at` to the
    YAML/JSON row structs (`listObjectYAML`/`listObjectJSON`). Requires
    fetching stats per object (opt-in only).
  - Extend `isMetadataMarkerName` to also treat `.stat.json` as a marker so it
    never appears in `show`'s folder tree.

### UNIT 5 — Config / env wiring
Files:
- `pkg/config/config.go`
- `pkg/manager/manager.go` (populate fields)

Points:
- Add to `Config`:
  - `TrackStat bool` — default `true` (ON). Parsed from
    `TOPSAILAI_DATA_TRACK_STAT`; empty → true; `0/false/no/off` → false.
  - `StatFlush string` — `sync` (default) or `async` from
    `TOPSAILAI_DATA_STAT_FLUSH`.
  - `StatDebounce time.Duration` — internal constant (e.g. 60s) or optional
    knob; keep as a const in manager for MVP simplicity.
- `Load()`: read the two env vars; default `TrackStat=true`.
- Manager `New`: copy `cfg.TrackStat` / `cfg.StatFlush` into `Manager`.
  For MVP, `async` may map to the same synchronous write (accept the value,
  document that async is a Phase-2 refinement) OR implement a simple
  debounced flush; recommend accepting `sync`/`async` and treating `async` as
  sync-with-debounce for now to keep the change minimal.

### UNIT 6 — gc / lifecycle integration
Files:
- `pkg/manager/manager.go` (logging on purge/cleanup)
- possibly `pkg/adapters/local/metadata.go` (Purge logging)

Points:
- Stats are frozen for `deleted`/`ceased` automatically because no increment
  hooks fire on those paths.
- `recover` (`RestoreObject`) leaves `.stat.json` intact → historical counts
  resume accumulating once active.
- `gc`/purge removes the object folder via `os.RemoveAll`, which removes
  `.stat.json`. Per the file-deletion logging rule, emit a log line when the
  stat file is removed (e.g. in `gcCeasedObject` / `cleanupCreatingObject` /
  `Purge`): `logger.Info("removing object stat file", "path", statPath)`.
- `move` copies the folder incl. `.stat.json` automatically; no change needed
  beyond a sanity assertion in tests.

## Cross-cutting concerns

- Comments in English; minimal edits; no hardcoded absolute paths (paths derive
  from `cfg.Root` / object dirs).
- Counts are a lower bound; increment errors are swallowed/logged, never fail
  the user operation.
- `.stat.json` must be excluded from archive read/write and from the `show`
  folder tree (two marker sites).
- Unit tests must hit >93% coverage on new paths; integration tests cover CLI
  surfaces.

## Suggested implementation order
1. UNIT 1 (model) → 2. UNIT 2 (persistence) → 3. UNIT 3 (manager) →
4. UNIT 5 (config) → 5. UNIT 4 (CLI) → 6. UNIT 6 (lifecycle/logging) →
then tests.
