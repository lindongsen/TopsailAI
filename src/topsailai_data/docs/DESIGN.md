# topsailai_data Design Document

## 1. Overview

`topsailai_data` is a Go-based data management system that unifies access to heterogeneous storage backends through a single CLI. Data is split into two categories:

- **Metadata**: descriptive information about a data object. For this project, metadata consists of **object identity** (the object name and stable ID), **path**, **description**, **time** (creation and update timestamps), **status**, and **tags**.
- **Actual data**: the payload itself, which may be plain text or arbitrary files. The mandatory `object.md` file inside an object folder is the primary actual-data carrier.

The system is built around adapter interfaces. Both metadata and actual data can be backed by independent adapters, allowing combinations such as local-only, database + local files, database + S3, and future backends.

This document describes the architecture, core interfaces, file layout conventions, and the first concrete implementation: the **local adapter**.

## 2. Goals and Non-Goals

### Goals

- Provide a single CLI to create, read, update, delete, and search data objects.
- Separate metadata storage from actual data storage so adapters can be mixed and matched.
- Support highly extensible adapter interfaces.
- Implement the local adapter first, with clear file-system semantics.
- Support independent object tags and time-based payload directory layouts.

### Non-Goals

- This phase does not implement database or S3 adapters.
- This phase does not provide network APIs (REST/gRPC).
- This phase does not implement authentication or multi-user isolation.

## 3. Terminology

| Term | Definition |
|------|------------|
| Object | A logical data unit identified by a stable ID and a name. |
| Object folder | A directory whose name equals the object name and which contains the required `object.md` file. |
| Object file | The `object.md` file inside an object folder. It is **actual data**, not metadata; its existence marks the folder as an object boundary. |
| Classify | A directory level used for organization after the time prefix. A classify path is the sequence of directories between the time prefix and the object folder. |
| Tag | A simple string attached to an object. The local adapter stores tags in the independent `tags` file under the object's Hash metadata directory. |
| Metadata | The set `{object ID, object name, path, description, creation time, update time, status, tags}` that describes an object. |
| Actual data | The payload associated with an object. The `object.md` file is the primary actual-data carrier; additional files and sub-directories inside the object folder are also actual data. |
| Adapter | A pluggable implementation of a storage interface. |
| Schema version | A monotonically increasing integer that identifies the persistent storage format. Starts at `1`. |
| Object lock | An advisory `lock` file in the Hash metadata directory, used to coordinate cooperating operations on that object. |
| Soft delete | A deletion strategy that marks an object as `deleted` while preserving its actual data, then later transitions it to `ceased` and removes the actual data. |
| Status | The lifecycle state of an object: `creating`, `active`, `deleted`, or `ceased`. |

## 4. Architecture

```text
+-----------------+
|      CLI        |
+-----------------+
        |
        v
+-----------------+
|  Data Manager   |
+-----------------+
        |
    +---+---+
    |       |
    v       v
+-------+ +-------+
|Metadata| | Actual |
|Adapter | | Adapter|
+-------+ +-------+
```

### 4.1 CLI Layer

The CLI is the only user-facing entry point. It parses commands, builds a `Manager` with the configured adapters, and invokes manager methods. The CLI supports both inline arguments and interactive prompts.

### 4.2 Data Manager

The `Manager` orchestrates metadata and actual data operations. It does not know storage details; it delegates to adapters. The manager is responsible for:

- Validating object names and paths.
- Coordinating metadata writes with actual data writes.
- Enforcing business rules such as tag validation and depth limits.

### 4.3 Adapter Interfaces

Two interfaces are defined:

- `MetadataAdapter`: stores and retrieves object metadata (ID, name, path, description, time, tags, and the opaque `DataRef`).
- `ActualDataAdapter`: stores and retrieves object payloads.

Both adapters operate on a stable object identifier (`ObjectID`) produced by the manager. Adapters are configured independently, so a deployment may use a local metadata adapter with an S3 actual-data adapter in the future.

## 5. Core Data Models

### 5.1 Object

```go
type ObjectStatus string

const (
    ObjectStatusCreating ObjectStatus = "creating"
    ObjectStatusActive   ObjectStatus = "active"
    ObjectStatusDeleted  ObjectStatus = "deleted"
    ObjectStatusCeased   ObjectStatus = "ceased"
)

type Object struct {
    ID            ObjectID
    Name          string
    Path          string
    Description   string
    Tags          []string
    Status        ObjectStatus
    SchemaVersion int
    CreatedAt     time.Time
    UpdatedAt     time.Time
    DataRef       string // adapter-specific reference to actual data
}
```

- `ID`: stable, opaque identifier. In the local adapter it equals the object name; in database adapters it is typically the same value stored as the primary key.
- `Name`: the object name, equal to the object folder name.
- `Path`: the path relative to the local `object/` payload root, e.g. `2026/0714/2323/xyz` or `2026/0714/2323/projects/demo/xyz`.
- `Description`: a short human-readable summary of the object. A description is required when an object is created; it may be supplied explicitly via `--description` or extracted automatically from the YAML frontmatter in `{name}.md`.
- `Tags`: the complete tag set returned by the adapter, loaded from the independent `tags` file locally. The local `metadata.json` does not contain tags.
- `Status`: lifecycle state. New objects start as `creating`, transition to `active` once actual data is written, and are removed through `deleted` to `ceased`.
- `SchemaVersion`: persistent storage format version of this object record. New local records use the current version; incompatible local records are refused.
- `CreatedAt`: creation timestamp, used to generate the time path.
- `UpdatedAt`: last modification timestamp, persisted in the local metadata record independently of payload file modification times.
- `DataRef`: adapter-specific reference. Locally it equals `Path`, is relative to `object/`, and is validated against object identity; it is never an absolute host path.

#### Description and YAML frontmatter fallback

When an object is created, a description is required. The manager first uses an explicit `--description` value if provided. If no explicit description is provided, the manager attempts to populate `Description` from the YAML frontmatter at the beginning of `{name}.md`. The extraction is best-effort:

- Only a leading `--- ... ---` block is considered.
- A bounded prefix of the file (first 8 KiB) is read for efficiency.
- If the frontmatter is missing, malformed, lacks a `description` key, or the value is not a string, the manager returns an error and the object is not created.

When an object with an empty existing description is updated without an explicit description, the manager attempts the same frontmatter extraction. If the frontmatter does not provide a description, the existing description remains empty and the update continues normally.

### 5.2 ObjectID

`ObjectID` is a stable identifier for an object. In the local adapter it is equal to the object name (the folder name). Because an object may be moved to a different classify path, the `ObjectID` must not be derived from the path. Moving an object updates its `Path` but preserves its `ID` and `Name`.

### 5.3 Tag

Tags are simple strings. Duplicates are removed and order is preserved.

The local adapter stores tags only in the independent `tags` file in the object's Hash metadata directory. The public `Object.Tags` field remains available, but `metadata.json` contains no tag field. Tags do not inherit from classify directories, and `meta/classify/` is not created. Tags survive soft deletion and finalization until metadata purge. Tag-file and metadata-record replacement are individually atomic, not a cross-file transaction; a failed later publication may leave an earlier tag replacement visible.

### 5.4 Schema Version and Persistence Format

Every persistent storage backend must record a `schema_version`. The value is a monotonically increasing integer that identifies the on-disk or on-database format. The initial version is `1`.

The local adapter stores `SchemaVersion` in each Hash metadata record and accepts only the current schema version. This layout cutover does not migrate or import an old store. An incompatible record is rejected rather than rewritten. New objects use the current schema version. A future database adapter may maintain its own migration history; that does not imply local migration support.

## 6. Adapter Interfaces

### 6.1 MetadataAdapter

The authoritative signatures are in `pkg/adapters/interfaces.go`. Metadata operations use stable object IDs and object records. The interface includes create/get/update, soft delete, finalization, ceased-only purge, list/search, tag changes, restore, and GC candidate enumeration. Payload removal is coordinated separately by the manager; metadata purge never deletes payload data.

### 6.2 ActualDataAdapter

The actual-data adapter supports two access patterns: **archive** (entire object folder as a tar stream) and **single file** (a named file inside the object).

The authoritative signatures are in `pkg/adapters/interfaces.go`. Location-aware actual-data methods accept a reference string rather than an object ID. Archive/file writes and Move return the resulting reference. Locally references are canonical paths relative to `object/`. Move copies to the destination; the manager publishes the new metadata before deleting the source. Remote references remain adapter-specific.

The local adapter implements both patterns over the object folder. Remote adapters such as S3 may store payloads as single blobs or object-storage keys.

### 6.3 ListOptions

```go
type ListOptions struct {
    Tags   []string
    Offset int
    Limit  int
}
```

## 7. Local Adapter Design

The local adapter stores everything on the local file system. It is split into a `LocalMetadataAdapter` and a `LocalActualDataAdapter`.

### 7.1 Root Directory

The configured store container has sibling `object/` and `meta/` trees. `TOPSAILAI_DATA_ROOT` selects that container; the CLI defaults to `${HOME}/.topsailai/data` when unset. Relative configuration paths are resolved at construction. Existing old-layout stores are not migrated by this cutover.

### 7.2 Object Folder Layout

An object named `xyz` is stored as:

```text
{ROOT}/object/2026/0714/2323/xyz/
    xyz.md          (mandatory actual data)
    <other files>   (optional actual data)
    <sub-directories> (optional actual data)
```

- `xyz.md` is mandatory. It is **actual data** and expresses the real information of the object. Its existence also marks `xyz/` as an object folder.
- Additional files and sub-directories are considered actual data of the object.
- Object metadata lives at `meta/<h[0:2]>/<h[2:4]>/<h[4:6]>/<h>/`, where `h` is the lowercase SHA256 of the exact object ID. The leaf contains `metadata.json`, `tags`, `lock`, `stat.json`, and `stat.lock` as needed.
- The payload folder contains user data only. User files named `metadata.json`, `stat.json`, `.stat.json`, or ending in `.tags`/`.lock` are ordinary actual data, not internal metadata.

### 7.3 ObjectID and Path in the Local Adapter

- `ObjectID` equals the object folder name. For object `xyz`, the ID is `xyz`.
- `Path` and `DataRef` are equal canonical paths relative to `object/`, e.g. `2026/0714/2323/xyz`.
- Because the ID is the folder name, two objects with the same name cannot coexist at different paths in the local adapter. This is a known limitation of the local adapter; database adapters do not have this restriction.
- When an object is moved to a different classify path, its `Path` changes but its `ID` and `Name` remain the same.

### 7.4 Time Path

Objects are placed under a time prefix generated from the object's creation time using **local time**:

```text
{year}/{monthday}/{hourminute}/{object-name}
```

Examples:

- `2026/0714/2323/xyz`
- `2026/0714/2323/projects/demo/xyz`

After the time prefix, users may add custom classify directories. The total depth from `object/` to the object folder must not exceed 11 levels, and the object folder itself counts toward that limit.

### 7.5 Depth Limit

The payload root `object/` itself is level 0; the store-container level is not counted. The time prefix contributes 4 levels (`year`, `monthday`, `hourminute`, `object-name`). Therefore up to 7 additional classify levels may be inserted between `hourminute` and the object name.

```text
level 0: {ROOT}/object
level 1: 2026
level 2: 0714
level 3: 2323
level 4-10: optional classify directories
level 11: object-name
```

The 11-level limit **includes** the object folder. If a proposed path exceeds level 11, the manager returns `ErrDepthExceeded`.

Example of an invalid path:

```text
2026/0714/2323/a/b/c/d/e/f/g/h/xyz
```

This path has 12 levels below the root and therefore exceeds the limit.

### 7.6 UpdatedAt in the Local Adapter

The local adapter persists `CreatedAt` and `UpdatedAt` in the Hash metadata record. Payload timestamps are not the authority for object timestamps.

### 7.7 Metadata Enumeration and Payload Boundaries

Normal Get resolves metadata by the ID hash. List and Search enumerate Hash metadata records and load their independent tag files, without discovering objects by scanning payload Markdown. Creating objects remain hidden from normal queries. A nested Markdown file does not create another metadata record.

The payload scanner and namespace checks still recognize a directory containing its same-named Markdown file as a payload boundary and stop descending there. This protects private object subdirectories; it is not the metadata query source. Collection operations remain unindexed: the accepted 100000-object measurements were List 17.023s and Search 22.384s, with about 1.2 GB cumulative allocations per operation, not peak memory. Scale optimization is deferred separately.

### 7.8 Actual Data Storage

For the local adapter, actual data is stored inside the object folder. The adapter treats the entire object folder as the payload container.

- `WriteArchive` receives a tar stream representing the complete object directory. The adapter extracts the stream into the object folder, replacing any existing files with matching entries. If the stream does not contain `object.md`, the adapter preserves the existing `object.md`; if the stream does contain `object.md`, the stream version replaces the existing one. After extraction, the adapter verifies that `object.md` exists.
- `ReadArchive` returns a tar stream of the folder contents, always including `object.md`.
- `WriteFile` and `ReadFile` operate on individual files within the object folder. Writing `object.md` via `WriteFile` is allowed and follows the same rules as any other file.

Future adapters may store payloads as single blobs or object-storage keys.

### 7.9 Object Locking

Each object uses the `lock` file in its Hash metadata leaf. Locks coordinate cooperating processes only. Namespace custody serializes creation, relocation, and metadata-leaf removal; lock order is namespace then object. Mutations re-read the record after acquiring custody.

- Writes, soft deletion, finalization, recovery, and GC acquire object custody.
- Optional read locking retains shared custody until the returned stream is closed.
- Statistics use `stat.lock` for the complete read-modify-write operation and revalidate active status under object custody.
- Finalization removes payload but retains the metadata leaf and its lock files. Only purge removes the leaf.
- These locks do not guarantee safety against hostile concurrent path replacement or power loss.

### 7.10 Soft Delete and Finalization

Lifecycle status is stored in Hash `metadata.json`, not payload `.deleted` or `.ceased` files. Soft delete changes active to deleted and retains payload, tags, and statistics. Finalization removes the entire payload directory before setting ceased. If removal fails, the deleted record remains for retry; if status publication fails after removal, the deleted record also remains retryable. Ceased metadata and tags remain until purge. Statistics are best effort, not a durable event ledger.

Deleted and ceased objects are excluded from normal list/search; `--include-deleted` enables inspection. Show resolves metadata by ID and only renders actual-data sections for active objects.

### 7.11 Lifecycle State-Operation Matrix

The following table maps each object status to the operations that may be performed on it. Operations that are not allowed return an error appropriate for the context (for example, `ErrObjectNotFound` for invisible objects or `ErrObjectLocked` for a locked `active` object).

| Status | Visible in List/Search | Visible in show | Read Actual | Write Actual | Tag | Move | Delete | Allowed Resolution |
|--------|------------------------|-----------------|-------------|--------------|-----|------|--------|-------------------|
| `creating` | No | No | No | Yes (during creation) | No | No | No | `gc` |
| `active` | Yes | Yes | Yes | Yes | Yes | Yes | Yes (soft delete) | — |
| `deleted` | Only with `--include-deleted` | Yes | No | No | No | No | Yes (finalize) | `recover`, `delete`, `gc` |
| `ceased` | Only with `--include-deleted` | Yes | No | No | No | No | No | `gc` (cleanup after retention, or immediate with `--status ceased`) |

- `creating` objects are invisible to normal `List`, `Get`, and search. They may only be resolved by `gc` (which removes incomplete metadata and any partial actual data).
- `active` objects support all operations. Write operations acquire the advisory object lock; `Delete` performs a soft delete that preserves actual data.
- `deleted` objects retain metadata and actual data, but actual-data reads are refused because reads require `active` status. `recover` restores the object to `active` without requiring `--from`, after which reads work again. `Delete` finalizes the object by removing actual data and transitioning it to `ceased`. `gc --status deleted` finalizes all `deleted` objects.
- `ceased` objects retain only metadata. No actual-data operations are permitted. They are eligible for cleanup by `gc` after `TOPSAILAI_DATA_CEASED_RETENTION_DAYS`. When `gc --status ceased` is explicitly requested, all `ceased` objects are removed immediately, ignoring the retention window.

## 8. CLI Commands

The CLI is named `topsailai-data`. Commands include:

| Command | Purpose |
|---------|---------|
| `create <object> [--classify dir1/dir2/...] [--tag tag1,tag2] [--description <text>] [--from <path|->]` | Create a new object. Markdown content is required and must include the mandatory `{object}.md` file; it can be supplied via `--from` or stdin. A description is required and may be provided with `--description` or extracted from the `description` field in the YAML frontmatter of `{object}.md`. If neither source provides a description, creation fails. Optional classify directories may follow the time prefix. |
| `show <id>` | Display metadata of an object. For `active` objects also display the markdown content and folder structure; for `deleted` or `ceased` objects only metadata is shown. |
| `update <id> [--description <text>]` | Update an object's metadata. Currently supports updating the description; `--description ""` clears it. |
| `move <id> <new-classify...>` | Move an object to a different classify path. The ID and name do not change. |
| `delete <id>` | Soft-delete an active object. Marks the object as `deleted` but preserves actual data so it can be recovered. |
| `list [--include-deleted] [--offset n] [--limit n] [--format yaml|json]` | List active objects, optionally paginated. The default output format is YAML; use `--format json` for machine-readable JSON. |
| `search <query> [--include-deleted] [--offset n] [--limit n] [--format yaml|json]` | Search objects by name, tag, or classify path. Use `|` in `<query>` for OR logic (e.g. `foo|bar`). Spaces, tabs, and backslash escapes are not supported. The default output format is YAML; use `--format json` for machine-readable JSON. |
| `tag add <id> <tag>` | Add a tag to an object. |
| `tag remove <id> <tag>` | Remove a tag from an object. |
| `get <id> <object-file>` | Read a single actual data file from an object. |
| `get-archive <id>` | Output the actual data archive (tar) of an object. |
| `put <id> <dest-file> [--from <src-file|->]` | Write a single actual data file to an object. `<dest-file>` is the filename inside the object; the source is read from `--from` or from redirected stdin. |
| `put-archive <id> <archive>` | Replace object actual data from a tar archive. |
| `recover <id>` | Restore a `deleted` object to `active`. The object's actual data must still exist. Returns an error for `creating`, `active`, or `ceased` objects. |
| `gc [--dry-run] [--status creating|deleted|ceased]` | Scan and clean up objects in the specified status. Default scans `creating` and `ceased`, honoring `TOPSAILAI_DATA_CEASED_RETENTION_DAYS`. When `--status ceased` is explicitly provided, all ceased objects are removed immediately. |

Search queries are case-insensitive substring matches against object names, tags, and classify paths. Multiple terms separated by `|` are combined with OR semantics: an object matches if any term matches its name, tags, or classify path. Queries containing spaces, tabs, or backslash escapes are rejected with a clear error.

All commands support interactive mode when invoked without inline arguments.
Write commands always acquire the object lock by default.

## 9. Error Handling

The manager and adapters define sentinel errors:

```go
var (
    ErrObjectNotFound = errors.New("object not found")
    ErrObjectExists   = errors.New("object already exists")
    ErrDepthExceeded  = errors.New("object path exceeds maximum depth")
    ErrInvalidName    = errors.New("invalid object name")
    ErrObjectLocked   = errors.New("object is locked by another operation")
)
```

Errors are wrapped with context using `fmt.Errorf("...: %w", err)` so callers can inspect causes.

### 9.1 Boundary Cases

- A payload folder missing its same-name Markdown boundary is invalid; a metadata record is not discovered or recreated from arbitrary payload files.
- Duplicate tags on one object are deduplicated; the first occurrence wins.
- Creating an object whose path already exists returns `ErrObjectExists`.
- Deleting an active object marks it as `deleted` and preserves actual data; finalization removes actual data and transitions the object to `ceased`.
- Scanning stops at object boundaries; nested `object.md` files are ignored.
- Moving an object updates its `Path` but preserves its `ID` and `Name`.
- The `show` command resolves an object through its metadata record and therefore works for any status. Actual data content and folder structure are displayed only when the object's status is `active`; for `deleted` and `ceased` objects only metadata is shown.
- In the local adapter, two objects cannot share the same name at different paths.

## 10. Database Metadata Adapter Design

A database-backed metadata adapter implements the same `MetadataAdapter` interface. It stores the same logical `Object` model, but persists metadata in relational tables.

### 10.1 Schema

#### objects table

| Column | Type | Notes |
|--------|------|-------|
| `object_id` | string, primary key | Stable ID. In local adapter terms this equals the object name. |
| `name` | string, not null | Object name, same as `object_id` in the local adapter. |
| `path` | string, not null, unique | Full relative path, e.g. `2026/0714/2323/xyz`. |
| `description` | string | Optional human-readable summary. |
| `created_at` | timestamp, not null | Creation time. |
| `updated_at` | timestamp, not null | Last update time. |
| `status` | enum('creating','active','deleted','ceased'), not null default 'active' | Object lifecycle status. |
| `data_ref` | string | Opaque reference to actual data. |
| `schema_version` | integer, not null default 1 | Persistent storage format version. |

#### object_tags table

| Column | Type | Notes |
|--------|------|-------|
| `object_id` | string, FK → objects | Part of composite primary key. |
| `tag` | string | Part of composite primary key. |

#### schema_migrations table

| Column | Type | Notes |
|--------|------|-------|
| `version` | integer, primary key | Applied migration version. |
| `applied_at` | timestamp, not null | When the migration was applied. |

### 10.2 Tag Storage

Tags are stored per object in the `object_tags` table and nowhere else. There is no
classify-level tag table and no inheritance: the rows for one `object_id` are the
complete tag set of that object.

The contract is that `Object.Tags` returned by the adapter equals the `object_tags`
rows for that object, deduplicated. No adapter may synthesize tags from the object's
path or from any ancestor directory.

### 10.3 Object Boundary in the Database Adapter

A future database adapter represents objects by rows rather than payload scans. As with local metadata enumeration, nested payload files do not create metadata records. Payload namespace validation must prevent one object from owning a descendant of another object's payload path.

## 11. Extensibility

New adapters are added by implementing `MetadataAdapter` or `ActualDataAdapter`. The manager does not change when a new adapter is introduced. Configuration selects adapters via environment variables:

- `TOPSAILAI_DATA_METADATA_ADAPTER`: e.g. `local`, `postgres`.
- `TOPSAILAI_DATA_ACTUAL_DATA_ADAPTER`: e.g. `local`, `s3`.

Adapter-specific settings use the `TOPSAILAI_DATA_{ADAPTER}_{KEY}` pattern. For example:

- `TOPSAILAI_DATA_LOCAL_ROOT`
- `TOPSAILAI_DATA_POSTGRES_DSN`
- `TOPSAILAI_DATA_S3_BUCKET`

A factory function maps adapter names to constructors:

```go
type MetadataAdapterFactory func(ctx context.Context, cfg map[string]string) (MetadataAdapter, error)
```

### 11.1 Cross-Adapter DataRef

The manager coordinates a stable ID, an adapter-specific payload reference, and lifecycle metadata. The current local implementation determines its relative reference before publishing creating metadata, writes payload, then publishes active metadata. Local records validate `Path` and `DataRef` against the same object identity. Other adapters must define their reference resolution and failure semantics explicitly; this document does not promise unsupported remote combinations.

## 12. Manager Operation Flows

The `Manager` is responsible for orchestrating metadata and actual data adapters so that cross-adapter operations remain consistent and recoverable.

### 12.1 Create Object

1. Validate the name, tags, classify path, mandatory Markdown, and description before publication.
2. Acquire namespace custody and check the destination boundary and existing ID. Active, creating, and deleted IDs cannot be replaced; a ceased ID is purged under custody before replacement.
3. Acquire the Hash object lock and reserve the payload directory with its same-name Markdown boundary.
4. Publish creating metadata with relative `Path`/`DataRef`, then write the archive.
5. Publish active metadata and record the write statistic. Failures after creating publication retain the creating record and partial payload for GC; errors are returned, not converted to success. Failure before record publication can leave a boundary or Hash leaf without a record; it is not automatically a normal GC candidate.
6. Release custody.

Creation inspects the archive in memory before persistence, so memory use is proportional to archive size.

### 12.2 Update Actual Data

Acquire Hash object custody, re-read active metadata, write using the relative reference, then publish the updated timestamp. Single-file replacement is atomic; archive replacement is not a whole-object transaction. If later metadata publication fails, report the error without deleting the existing payload. A failed publication does not promise rollback of already written content.

### 12.3 Delete Object

Under namespace and object custody, re-read the record. Active becomes deleted without removing payload. A second delete on a deleted object removes the payload directory, then publishes ceased. A cleanup error preserves the retry record and is returned. Finalization retains metadata, tags, and lock files; it is not purge.

### 12.4 Move Object

Under namespace and object custody, re-read active metadata and validate the destination. Copy payload with its boundary established first, publish the new relative `Path`/`DataRef`, then delete the source. ID, name, and tags remain unchanged. Publication failure retains the original reference and source; source-cleanup failure after publication is returned while the new reference remains authoritative.

### 12.5 Failure Strategy

Each file publication may be atomic, but tags plus metadata, archive replacement, and cross-directory move are not multi-file transactions. Retain recovery records when cleanup fails, return the original failure with context, and do not claim all-or-nothing rollback or power-loss durability.

### 12.6 Recover Object

Acquire namespace and object custody, re-read deleted status, verify actual data or apply an explicitly supplied archive, then restore active metadata. Recovery preserves tags and resumes statistics. Active, creating, and ceased objects cannot be recovered.

### 12.7 Garbage Collect Objects

`gc` cleans up objects based on their lifecycle status.

- Default behavior (no `--status` flag): scan `creating` objects and `ceased` objects. Remove `creating` objects and their partial actual data immediately. Remove `ceased` objects only after `TOPSAILAI_DATA_CEASED_RETENTION_DAYS`.
- `--status creating`: remove all `creating` objects immediately.
- `--status deleted`: finalize all `deleted` objects to `ceased` after actual data removal succeeds.
- `--status ceased`: remove all `ceased` objects immediately, ignoring the retention window. Use this when you want to force cleanup before the retention period expires.

`--dry-run` reports what would be removed without making changes.

## 13. Configuration and Environment Variables
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TOPSAILAI_DATA_ROOT` | no | `${HOME}/.topsailai/data` | Root directory for the local adapter. |
| `TOPSAILAI_DATA_METADATA_ADAPTER` | no | `local` | Metadata adapter name. |
| `TOPSAILAI_DATA_ACTUAL_DATA_ADAPTER` | no | `local` | Actual data adapter name. |
| `TOPSAILAI_DATA_LOG_LEVEL` | no | `INFO` | Log level for the CLI. |
| `TOPSAILAI_DATA_READ_LOCK` | no | `0` | If `1`, read operations acquire the object lock. |
| `TOPSAILAI_DATA_INCLUDE_DELETED` | no | `false` | If `true`, list/search operations include objects with status `deleted` or `ceased`. |
| `TOPSAILAI_DATA_CEASED_RETENTION_DAYS` | no | `30` | Number of days to retain `ceased` metadata before cleanup. |
| `TOPSAILAI_DATA_FILE_MAX_BYTES` | no | `30000` | Byte limit applied when reading a file whose extension is not whitelisted. |
| `TOPSAILAI_DATA_FILE_WHITE_LIST_NO_TRUNCATE_EXT` | no | built-in list | Comma-separated extension override for the no-truncate whitelist. `*` disables truncation; `!*` forces it. |
All paths in configuration are resolved relative to the process working directory or as absolute paths. No hardcoded paths are used.

## 14. Logging

Logging uses the standard library `log/slog` with JSON output. When logging to a file, rotation is configured via `lumberjack` with the following environment variables:

- `TOPSAILAI_DATA_LOG_MAX_SIZE_MB`
- `TOPSAILAI_DATA_LOG_MAX_BACKUPS`
- `TOPSAILAI_DATA_LOG_MAX_AGE_DAYS`

Default rotation limits are provided so the CLI starts safely.

## 15. Testing Strategy

Unit tests target the manager and local adapter with high coverage, focusing on critical paths. Each unit test uses `t.TempDir()` as the local adapter root so tests are isolated and do not depend on external state.

Key test areas:

- Object creation with valid and invalid names.
- Time-path generation and depth enforcement.
- Tag validation, deduplication, and independent tag-file persistence.
- Metadata scanning and object-boundary detection.
- Actual data archive read/write, single-file read/write, and deletion.
- Adapter factory selection.
- Object locking and soft-delete state transitions.
- Schema compatibility refusal without old-store migration.

Integration tests verify CLI commands against a temporary root directory configured via the `TOPSAILAI_DATA_ROOT` environment variable.

## 16. Project Structure

```text
project/
├── cmd/topsailai-data/
├── docs/DESIGN.md
├── pkg/
│   ├── adapters/local/
│   ├── cli/
│   ├── config/
│   ├── errors/
│   ├── filetool/
│   ├── manager/
│   ├── models/
│   └── objectfs/
├── skills/topsailai-data/
└── tests/bdd/
```

## 17. Future Work

- Implement `postgres` metadata adapter.
- Implement `s3` actual data adapter.
- Add search indexing for fast tag-based queries.
- Add import/export commands for backup and migration.

## 18. Summary

`topsailai_data` separates metadata from actual data through adapter interfaces, enabling flexible backend combinations. The local adapter uses a time-based directory layout and mandatory `object.md` files as actual-data carriers. Tags are stored in each object's independent Hash metadata `tags` file, excluded from `metadata.json`, with no classify tag inheritance. Object creation requires non-empty markdown content and a description, which may be supplied explicitly or extracted from YAML frontmatter. Payload namespace boundaries use same-named `.md` files; normal object queries enumerate Hash metadata rather than payload files. The metadata model includes `ID`, `Name`, `Path`, `Description`, `CreatedAt`, `UpdatedAt`, `Status`, `SchemaVersion`, and `Tags`, with `ObjectID` stable across moves. A database metadata adapter can implement the same interface using an `objects` table and an `object_tags` table. The design prioritizes extensibility, clear conventions, and testability.


## 19. Write-source safety

Single-file `put` rejects a source that is the same file as the destination, including filesystem aliases such as symlinks and hard links. The existing destination is replaced atomically through a temporary file in the destination directory followed by rename; failed writes leave the previous destination unchanged.

`put-archive` and `recover --from` reject file-backed archive sources that overlap the target object directory or any file that the archive write may clear or replace. The rejection occurs before cleanup, extraction, or lifecycle metadata updates, preserving the original object data and status.

The local adapter reserves the `.topsailai-data-write-*` namespace for temporary replacements. Reserved temporary files are excluded from archive reads, folder-tree output, existence checks, and move copies. Expired reserved temporary files are removed recursively at object cleanup/GC boundaries after 24 hours; fresh and unrelated files are preserved, and directory symlinks are not traversed.

Every `file` write holds the object's meta lock across the whole
read-modify-write, so a competing writer fails with `ErrObjectLocked` rather
than silently discarding an update. See §20.9 for the streaming and
lock-scoped write contract.

## 20. File and Folder Command Group

The `file` command group exposes the file and folder capabilities of the
TopsailAI file tool through the same CLI, scoped to the actual data of one data
object. It is implemented in `pkg/filetool` as a reusable library,
`pkg/objectfs` as the adapter that presents an object's actual data as a file
system, and `pkg/cli/file_commands.go` as the argument-parsing layer.

Every subcommand requires `--object <id>`. There is no operating-system mode:
a file command without `--object` is rejected, so the group can never silently
read or write a path outside a data object.

### 20.1 Capability Inventory

| Subcommand | Capability | Arguments |
|------------|------------|-----------|
| `read` | Read a file, optionally a byte window | `<file_path> --object <id> [--seek n] [--size n]` |
| `read-lines` | Read a line range | `<file_path> --object <id> [--start n] [--end n]` |
| `read-around` | Read context around one line | `<file_path> <line_number> --object <id> [--context n]` |
| `read-context` | Read lines matching a pattern with context | `<file_path> <pattern> --object <id> [--context n] [--case-sensitive]` |
| `read-files` | Read several files into one map | `<file_path...> --object <id> [--format yaml\|json]` |
| `write` | Write content, optionally at a byte offset | `<file_path> --object <id> [--content <text>\|--from <path\|->] [--seek n] [--insert]` |
| `append` | Append content | `<file_path> --object <id> [--content <text>\|--from <path\|->]` |
| `exists` | Check several paths for existence | `<name=path...> --object <id> [--format yaml\|json]` |
| `mkdirs` | Create folders, each seeded with an `AGENTS.md` marker | `<dir...> --object <id>` |
| `list-dirs` | List several folders | `<dir...> --object <id> [--format yaml\|json]` |
| `size` | Report a file size in bytes | `<file_path> --object <id>` |
| `overwrite-lines` | Replace a line range and return a diff | `<file_path> <start_num> --object <id> [--end n] [--content <text>\|--from <path\|->]` |
| `insert` | Insert content before or after a line and return a diff | `<file_path> <line_num> --object <id> [--content <text>\|--from <path\|->] [--before]` |

### 20.2 Object Scoping

`--object <id>` names the data object whose actual data the command operates
on. The object folder is the root of every path:

- A path is interpreted relative to the object folder. `notes/a.md` addresses
  the file `notes/a.md` inside that object, never a file on the host.
- A leading slash is ignored, so `/notes/a.md` and `notes/a.md` are the same
  file.
- An empty path addresses the object root. `list-dirs ""` and `list-dirs .`
  both list the top level of the object folder.
- A path that escapes the object folder, such as `../outside.md`, is clamped
  rather than rejected. The path is normalized against the object root, so
  `../outside.md` addresses `outside.md` inside the object and the command
  succeeds. A caller cannot reach a file outside the object, but it also
  receives no error, so a path that was meant to fail silently addresses a
  different file at the object root.
- An unknown object id returns `ErrObjectNotFound` before any file is touched.

Because every operation is routed through the manager, the guarantees of the
object store apply unchanged:

- Write operations acquire the advisory object lock.
- Single-file writes replace the destination atomically through a temporary
  file followed by a rename, so a failed write leaves the previous content
  intact.
- Read and write operations update the object's usage statistics.
- Hash metadata is outside the payload root and cannot be addressed through file commands. User files named `metadata.json`, `stat.json`, `.stat.json`, or `<object>.lock` are ordinary actual data. The mandatory `<object>.md` remains actual data; `.topsailai-data-write-*` remains reserved for internal replacements.

`mkdirs` creates every missing level of the requested path and writes an
`AGENTS.md` marker into each level it creates. Object storage has no meaningful
empty folder, so a folder becomes discoverable only once it holds a file; the
marker is what makes the new folder visible to `list-dirs` and `exists`.

- A level that already exists is skipped, so an existing `AGENTS.md` is never
  overwritten and a populated folder receives no marker.
- The object root is never modified: `mkdirs .` and `mkdirs ""` succeed without
  writing a marker.
- The marker is written through the manager, so the object lock, the atomic
  replacement, and the write statistics apply exactly as for any other write.
- The absolute-path requirement of the original tool does not apply in object
  mode, because every path is already relative to the object folder.

### 20.3 Preserved Behaviour Contracts

- `--seek` and `--size` are byte offsets. A negative `--seek` counts from the
  end of the file; `--size -1` reads to the end.
- Content whose extension is not whitelisted is truncated at
  `TOPSAILAI_DATA_FILE_MAX_BYTES` and the suffix ` ... (force to truncate)` is
  appended. Whitelisted extensions are returned in full.
- The whitelist override accepts `*` to disable truncation for every extension
  and `!*` to force truncation for every extension.
- Encoding is detected from a bounded leading sample and decoded incrementally;
  undecodable bytes are replaced so a partially corrupted file still yields
  readable text.
- `--end 0` addresses only `--start`; `--end -1` reads through the end of the
  file; any other negative value is rejected.
- `overwrite-lines` and `insert` preserve the surrounding line endings and
  return a unified diff. `overwrite-lines` also returns the warning that line
  numbers change after each call.
- `read-files`, `list-dirs`, and `exists` record a per-item failure instead of
  hiding the other items.

### 20.4 Content Source Precedence

The four content-writing subcommands (`write`, `append`, `overwrite-lines`,
`insert`) resolve their content from the same ordered sources:

1. `--from <path>`, which reads a file.
2. `--from -`, which reads standard input.
3. An explicit `--content` value, including an explicit empty value.
4. Redirected standard input when neither `--content` nor `--from` is given.
5. Empty content when standard input is an interactive terminal.

`--from` wins over `--content` so a caller can pass a file without quoting its
text. This ordering predates the standard-input fallback and is preserved.

The distinction between an absent `--content` and an explicitly empty
`--content ""` is preserved, because an empty value is a meaningful request:
`overwrite-lines` with empty content deletes the addressed line range. When
`--from` is absent, a caller that passes `--content ""` therefore never blocks
on standard input.

When standard input is an interactive terminal and no content source is given,
the content stays empty instead of waiting for input, so an interactive
invocation never hangs. This matches the convention already used by `create`
and `put`.

### 20.5 Documented Deviation

The TopsailAI file tool counts `seek` and `size` in characters because Python
strings are character indexed. This implementation counts bytes because Go
strings are byte indexed. For ASCII and UTF-8 text the two agree; for
multi-byte characters a byte offset may land inside a character. Callers that
need character-accurate windows on multi-byte text must account for this.

### 20.6 Configuration Boundary

`TOPSAILAI_DATA_FILE_MAX_BYTES` and
`TOPSAILAI_DATA_FILE_WHITE_LIST_NO_TRUNCATE_EXT` are read once by
`config.Load` at the CLI boundary and passed to the library as an explicit
`filetool.Options` value. The library never reads process-wide environment
variables, so tests override behaviour through parameters rather than by
mutating global state.

### 20.7 Discovery Inside an Object

`list-dirs` lists the immediate entries of each named folder inside the object
and does not recurse, so a deeper level must be named explicitly. `exists`
reports a boolean per named path and accepts files and folders alike. `size`
reports a byte count, and `read` returns content.

There is no recursive walk and no search-by-name command in the `file` group.
Recursive discovery with object-boundary detection belongs to `list` and
`search` in the object store, which scan the whole store rather than one
object.

### 20.8 Testing

- `pkg/filetool` unit tests cover all thirteen capabilities, including
  truncation, whitelist overrides, encoding fallback, line-ending preservation,
  and the `end_num` sentinel rules.
- `pkg/objectfs` unit tests cover path normalization, root listing, metadata
  marker rejection, and statistics integration.
- `pkg/cli` tests exercise every subcommand through the command layer with an
  explicit configuration, including a table-driven test proving that all
  thirteen subcommands reject a missing `--object`.
- `tests/bdd/features/file-tool.feature` runs the real binary against an
  isolated store. Objects are created through `create` and their content is
  verified through `get`, so the scenarios exercise the public surface end to
  end rather than the library alone.

### 20.9 Streaming and Lock-Scoped Writes

The `file` group must not buffer a whole object file to serve a bounded
request, and every write must hold the object's meta lock across the complete
read-modify-write. Both properties are part of the contract, not an
optimization detail.

**Streaming reads.** `ObjectFS.Open` forwards the adapter's stream when it is
seekable, so `filetool` reads only the bytes it needs. The local adapter
returns an `*os.File`, which is seekable, so `read`, `read-lines`,
`read-around`, `read-context`, and `size` stay bounded regardless of file
size. Only a non-seekable remote adapter falls back to buffering, and that
fallback is the adapter's responsibility to bound.

**Streaming writes.** `FS` exposes `WriteFileFrom`, `AppendFrom`,
`WriteAt`, and `EditFile` so content can flow from an `io.Reader` and bounded
edits can publish byte ranges. Whole-file writes, append, non-zero `--seek`,
and `--insert` assemble replacements in same-directory temporary files and
publish them by rename without loading the existing file. `put` already
streamed sources; the `file` group now preserves that property for every write
shape.

**Lock-scoped edits.** `Manager.AppendActualFile`, `WriteActualFileAt`, and
`EditActualFile` acquire exclusive object custody once and retain it while the
current file is inspected, the edit range is resolved, the replacement is
published, and the timestamp is updated. `overwrite-lines` and `insert` scan
line boundaries incrementally, retain only the changed window and three
context lines for the unified diff, and stream the untouched prefix and suffix.
For a small edit, memory is therefore independent of the complete file size.
A diff that itself contains a very large changed range still necessarily uses
memory and output proportional to that changed range, not to unrelated file
content.

The lock is the object's meta lock file at
`meta/<h[0:2]>/<h[2:4]>/<h[4:6]>/<h>/lock`, where `h` is the lowercase SHA256
of the object ID. It is acquired with `LOCK_NB`, and flock is per open file
description, so the lock is **not re-entrant**: a write path must acquire
custody once and must not call another custody-acquiring method while holding
it. A competing writer therefore fails with `ErrObjectLocked` instead of
silently discarding an update. This is the same advisory lock used by `put`,
`tag`, `move`, and the lifecycle commands.

**Direct folder discovery.** `ObjectFS.Stat`, `ReadDir`, and `MkdirAll`
use adapter `StatFile` and `ListFiles` operations. The local adapter answers
these from filesystem metadata and directory entries, so checking or creating
a folder does not stream the object's payload archive. Reserved temporary
replacement paths remain hidden from discovery.
