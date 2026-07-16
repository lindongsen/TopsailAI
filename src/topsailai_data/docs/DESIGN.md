# topsailai_data Design Document

## 1. Overview

`topsailai_data` is a Go-based data management system that unifies access to heterogeneous storage backends through a single CLI. Data is split into two categories:

- **Metadata**: descriptive information about a data object. For this project, metadata consists of **object identity** (the object name and stable ID), **path**, **time** (creation and update timestamps), **status**, and **tags**.
- **Actual data**: the payload itself, which may be plain text or arbitrary files. The mandatory `object.md` file inside an object folder is the primary actual-data carrier.

The system is built around adapter interfaces. Both metadata and actual data can be backed by independent adapters, allowing combinations such as local-only, database + local files, database + S3, and future backends.

This document describes the architecture, core interfaces, file layout conventions, and the first concrete implementation: the **local adapter**.

## 2. Goals and Non-Goals

### Goals

- Provide a single CLI to create, read, update, delete, and search data objects.
- Separate metadata storage from actual data storage so adapters can be mixed and matched.
- Support highly extensible adapter interfaces.
- Implement the local adapter first, with clear file-system semantics.
- Support recursive tag inheritance and time-based directory layouts.

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
| Object tag file | An optional `{object}.tags` file containing one tag per line. Tags apply only to that object. |
| Classify | A directory level used for organization after the time prefix. A classify path is the sequence of directories between the time prefix and the object folder. |
| Classify tag file | An optional `{classify}.tags` file inside a classify directory. Tags apply recursively to all objects under that classify directory. |
| Classify tag | A tag stored in the `classify_tag` relation table or a `{classify}.tags` file, inherited by all objects under the associated classify path. |
| Metadata | The set `{object ID, object name, path, creation time, update time, status, tags}` that describes an object. |
| Actual data | The payload associated with an object. The `object.md` file is the primary actual-data carrier; additional files and sub-directories inside the object folder are also actual data. |
| Adapter | A pluggable implementation of a storage interface. |
| Schema version | A monotonically increasing integer that identifies the persistent storage format. Starts at `1`. |
| Object lock | An advisory lock file (`{object}.lock`) inside an object folder, used to serialize write operations on that object. |
| Soft delete | A deletion strategy that first marks an object as `deleted`, removes its actual data, and finally marks it as `ceased`. |
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
- Enforcing business rules such as recursive tag inheritance and depth limits.

### 4.3 Adapter Interfaces

Two interfaces are defined:

- `MetadataAdapter`: stores and retrieves object metadata (ID, name, path, time, tags, and the opaque `DataRef`).
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
- `Path`: the full relative path of the object folder, e.g. `2026/0714/2323/xyz` or `2026/0714/2323/projects/demo/xyz`.
- `Tags`: merged set of inherited tags and object-specific tags.
- `Status`: lifecycle state. New objects start as `creating`, transition to `active` once actual data is written, and are removed through `deleted` to `ceased`.
- `SchemaVersion`: persistent storage format version of this object record. Starts at `1` and is updated on migration.
- `CreatedAt`: creation timestamp, used to generate the time path.
- `UpdatedAt`: last modification timestamp. Required in the model and in database adapters. In the local file-system adapter it is not persisted separately; the adapter returns `CreatedAt` or the file modification time, never a zero value.
- `DataRef`: opaque reference returned by the actual-data adapter. The metadata adapter stores it but does not interpret it.

### 5.2 ObjectID

`ObjectID` is a stable identifier for an object. In the local adapter it is equal to the object name (the folder name). Because an object may be moved to a different classify path, the `ObjectID` must not be derived from the path. Moving an object updates its `Path` but preserves its `ID` and `Name`.

### 5.3 Tag

Tags are simple strings. Duplicates are removed and order is preserved as read from files.

### 5.4 Schema Version and Persistence Format

Every persistent storage backend must record a `schema_version`. The value is a monotonically increasing integer that identifies the on-disk or on-database format. The initial version is `1`.

- The local adapter stores `schema_version` in a root-level index file `{ROOT}/topsailai_data.json` (or equivalent metadata file) and in each object record it returns.
- Database adapters store `schema_version` in the `objects` table and in a dedicated `schema_migrations` table.
- When a newer binary opens an older store, it must run migrations in order until the stored version matches the binary's expected version. Migrations are idempotent and recorded in `schema_migrations`.
- If an older binary opens a newer store, it must refuse to operate and return a clear error.

The `Object.SchemaVersion` field reflects the version of the record at the time it was read. New objects are created with the current schema version.

## 6. Adapter Interfaces

### 6.1 MetadataAdapter

```go
type MetadataAdapter interface {
    Init(ctx context.Context) error
    Create(ctx context.Context, obj Object) (ObjectID, error)
    Get(ctx context.Context, id ObjectID) (Object, error)
    Update(ctx context.Context, id ObjectID, obj Object) error
    Delete(ctx context.Context, id ObjectID) error
    List(ctx context.Context, opts ListOptions) ([]Object, error)
    Close() error
}
```

### 6.2 ActualDataAdapter

The actual-data adapter supports two access patterns: **archive** (entire object folder as a tar stream) and **single file** (a named file inside the object).

```go
type ActualDataAdapter interface {
    Init(ctx context.Context) error

    // Archive access: read or write the whole object folder as a tar archive.
    WriteArchive(ctx context.Context, id ObjectID, reader io.Reader) error
    ReadArchive(ctx context.Context, id ObjectID) (io.ReadCloser, error)

    // Single-file access: read or write one file inside the object.
    WriteFile(ctx context.Context, id ObjectID, filename string, reader io.Reader) error
    ReadFile(ctx context.Context, id ObjectID, filename string) (io.ReadCloser, error)

    // Move relocates the actual data to a new adapter-specific reference.
    // The metadata manager is responsible for updating the Object.Path.
    Move(ctx context.Context, id ObjectID, newRef string) error

    Delete(ctx context.Context, id ObjectID) error
    Exists(ctx context.Context, id ObjectID) (bool, error)
    Close() error
}
```

`Move` only handles the actual-data payload; it does **not** update metadata. For the local adapter, `newRef` is the new full object folder path (e.g. `2026/0714/2323/projects/demo/xyz`). For remote adapters, `newRef` is adapter-specific, such as an S3 object key. The caller (the manager) is responsible for computing `newRef` from the user's classify input and for updating `Object.Path` after the adapter reports success.

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

All data lives under a configurable root directory. The default root is controlled by the environment variable `TOPSAILAI_DATA_ROOT`. If unset, the CLI fails with a clear error.

### 7.2 Object Folder Layout

An object named `xyz` is stored as:

```text
{ROOT}/2026/0714/2323/xyz/
    xyz.md          (mandatory actual data)
    xyz.tags        (optional object-specific tags)
    <other files>   (optional actual data)
    <sub-directories> (optional actual data)
```

- `xyz.md` is mandatory. It is **actual data** and expresses the real information of the object. Its existence also marks `xyz/` as an object folder.
- `xyz.tags` is optional. Tags listed here apply only to this object.
- Additional files and sub-directories are considered actual data of the object.

### 7.3 ObjectID and Path in the Local Adapter

- `ObjectID` equals the object folder name. For object `xyz`, the ID is `xyz`.
- `Path` is the full relative path from the root to the object folder, e.g. `2026/0714/2323/xyz`.
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

After the time prefix, users may add custom classify directories. The total depth from the root to the object folder must not exceed 11 levels, and the object folder itself counts toward that limit.

### 7.5 Depth Limit

The root directory itself is level 0. The time prefix contributes 4 levels (`year`, `monthday`, `hourminute`, `object-name`). Therefore up to 7 additional classify levels may be inserted between `hourminute` and the object name.

```text
level 0: {ROOT}
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

The `UpdatedAt` field is part of the `Object` model and is required by the interface. In the local file-system adapter it is not persisted to a separate file in this phase. The adapter **must not** return a zero value. Instead it returns one of the following, in order of preference:

1. The file modification time of the object folder or `object.md`, if available.
2. `CreatedAt` as a fallback.

Future iterations may add a dedicated metadata file to persist `UpdatedAt` independently.

### 7.7 Tag Files

A tag file contains one tag per line. Lines whose first non-space character is `#` are comments and are ignored. Empty lines are ignored. Leading and trailing whitespace is trimmed from each tag.

Example `xyz.tags`:

```text
# project tags
project-alpha
urgent
```

### 7.8 Classify Tag Inheritance

If a classify directory contains a file named `{classify-name}.tags`, the tags in that file apply **recursively** to every object folder under that directory. Inherited tags are merged with object-specific tags and with tags inherited from intermediate classify directories; duplicates are removed.

Example:

```text
{ROOT}/2026/0714/2323/
    2323.tags
    xyz/
        xyz.md
        xyz.tags
    abc/
        abc.md
```

If `2323.tags` contains `daily`, `xyz.tags` contains `demo`, and `abc/` has no object-specific tags, then:

- Object `xyz` has tags `[daily, demo]`.
- Object `abc` has tags `[daily]`.

If `2026/0714/0714.tags` contains `archive`, then all object folders under `2026/0714/` (including those under `2026/0714/2323/`) inherit `archive` in addition to any closer inherited tags.

### 7.9 Metadata Scan Rules

When scanning for objects:

1. Walk the root directory recursively.
2. For each directory, check whether it contains a file named `{directory-name}.md`.
3. If such a file exists, the directory is an object folder. Record its metadata (ID = folder name, name, full path, creation time, merged inherited tags) and stop descending into it.
4. If no such file exists, continue scanning sub-directories.
5. A file such as `xyz/abc/xyz.md` does **not** make `abc` an object folder; only `xyz/xyz.md` makes `xyz` an object folder.

This rule ensures that an object's private sub-directories are not treated as independent objects. The `object.md` file is actual data, but its presence is used as the object-boundary signal during scanning.

### 7.10 Actual Data Storage

For the local adapter, actual data is stored inside the object folder. The adapter treats the entire object folder as the payload container.

- `WriteArchive` receives a tar stream representing the complete object directory. The adapter extracts the stream into the object folder, replacing any existing files with matching entries. If the stream does not contain `object.md`, the adapter preserves the existing `object.md`; if the stream does contain `object.md`, the stream version replaces the existing one. After extraction, the adapter verifies that `object.md` exists.
- `ReadArchive` returns a tar stream of the folder contents, always including `object.md`.
- `WriteFile` and `ReadFile` operate on individual files within the object folder. Writing `object.md` via `WriteFile` is allowed and follows the same rules as any other file.

Future adapters may store payloads as single blobs or object-storage keys.

### 7.11 Object Locking

Each object folder may contain an advisory lock file named `{object}.lock` (e.g. `xyz.lock`). The lock is advisory: it only coordinates processes that honor the convention.

- Write operations (`Create`, `Update`, `Delete`, `Move`, `WriteFile`, `WriteArchive`) acquire the object lock by default before modifying the object folder or metadata.
- Read operations (`Get`, `List`, `ReadFile`, `ReadArchive`) do **not** acquire the lock by default, allowing concurrent reads.
- A caller may force read locking via the CLI flag `--lock` or by setting the environment variable `TOPSAILAI_DATA_READ_LOCK=1`.
- If the lock file cannot be acquired because another process holds it, the operation returns `ErrObjectLocked` after a configurable timeout.
- Locks are meaningful only for `active` objects. `gc`, `recover`, and delete-finalization may proceed on `creating` or `deleted` objects without acquiring the lock.
- An `active` object cannot be deleted or moved while another process holds its lock.
- The lock file is created on first write and removed when the object transitions to `ceased`.

### 7.12 Soft Delete Markers

Deletion follows a soft-delete lifecycle with four states: `creating`, `active`, `deleted`, and `ceased`.

In the local adapter:

1. `delete <id>` first creates a marker file `{object}.deleted` (e.g. `xyz.deleted`) inside the object folder. The object's metadata status is updated to `deleted`.
2. The actual data is then removed via the actual-data adapter (`Delete`).
3. After actual data removal succeeds, the marker is renamed or replaced to `{object}.ceased` (e.g. `xyz.ceased`) and the metadata status is updated to `ceased`.

In database adapters:

1. Update the `objects.status` column from `active` to `deleted`.
2. Delete the actual data via the actual-data adapter.
3. Update `objects.status` from `deleted` to `ceased`.

Objects with status `deleted` or `ceased` are excluded from normal `List` and `Get` results. A dedicated `--include-deleted` flag or `TOPSAILAI_DATA_INCLUDE_DELETED=1` environment variable may be used to inspect them.

### 7.13 Lifecycle State-Operation Matrix

The following table maps each object status to the operations that may be performed on it. Operations that are not allowed return an error appropriate for the context (for example, `ErrObjectNotFound` for invisible objects or `ErrObjectLocked` for a locked `active` object).

| Status | Visible in List/Search | Visible in show | Read Actual | Write Actual | Tag | Move | Delete | Allowed Resolution |
|--------|------------------------|-----------------|-------------|--------------|-----|------|--------|-------------------|
| `creating` | No | No | No | Yes (during creation) | No | No | No | `recover`, `gc` |
| `active` | Yes | Yes | Yes | Yes | Yes | Yes | Yes (soft delete) | — |
| `deleted` | Only with `--include-deleted` | Yes | Only if data still exists | No | No | No | Yes (retry/finalize) | `delete`, `gc` |
| `ceased` | Only with `--include-deleted` | Yes | No | No | No | No | No | `gc` (cleanup after retention) |

- `creating` objects are invisible to normal `List`, `Get`, and search. They may only be resolved by `recover` (which promotes them to `active` if actual data exists) or `gc` (which removes incomplete metadata and any partial actual data).
- `active` objects support all operations. Write operations acquire the advisory object lock; `Delete` performs a soft delete.
- `deleted` objects retain metadata but their actual data is removed. `Read` is allowed only if the adapter still holds data; `Delete` re-attempts actual-data removal and finalizes the object to `ceased` on success.
- `ceased` objects retain only metadata. No actual-data operations are permitted. They are eligible for cleanup by `gc` after `TOPSAILAI_DATA_CEASED_RETENTION_DAYS`.

## 8. CLI Commands

The CLI is named `topsaildata`. Commands include:

| Command | Purpose |
|---------|---------|
| `create <object> [--classify dir1/dir2/...] [--tag tag1,tag2] [--from <path|->]` | Create a new object. Optional classify directories may follow the time prefix. |
| `show <id>` | Display metadata of an object. For `active` objects also display the markdown content and folder structure; for `deleted` or `ceased` objects only metadata is shown. |
| `update <id>` | Update an object's metadata or tags. |
| `move <id> <new-classify...>` | Move an object to a different classify path. The ID and name do not change. |
| `delete <id>` | Soft-delete an object and its actual data. |
| `list [--tag tag1,tag2,...] [--include-deleted] [--offset n] [--limit n] [--format table|json]` | List objects, optionally filtered by tag. |
| `search <query> [--include-deleted] [--offset n] [--limit n] [--format table|json]` | Search objects by name or tag. Use `|` in `<query>` for OR logic (e.g. `foo|bar`). Spaces, tabs, and backslash escapes are not supported. |
| `tag add <id> <tag>` | Add a tag to an object. |
| `tag remove <id> <tag>` | Remove a tag from an object. |
| `get <id> <object-file>` | Read a single actual data file from an object. |
| `get-archive <id>` | Output the actual data archive (tar) of an object. |
| `put <id> <dest-file> [--from <src-file|->]` | Write a single actual data file to an object. `<dest-file>` is the filename inside the object; the source is read from `--from` or from redirected stdin. |
| `put-archive <id> <archive>` | Replace object actual data from a tar archive. |
| `recover <id>` | Attempt to finish a `creating` object if actual data exists; otherwise mark it `ceased`. |
| `gc [--dry-run] [--status creating|deleted|ceased]` | Scan and clean up objects in the specified status. Default scans `creating` and `ceased`. |

Search queries are case-insensitive substring matches against object names and tags. Multiple terms separated by `|` are combined with OR semantics: an object matches if any term matches its name or any tag. Queries containing spaces, tabs, or backslash escapes are rejected with a clear error.

All commands support interactive mode when invoked without inline arguments.
Read commands accept an optional `--lock` flag to force advisory locking. Write commands always acquire the object lock by default.

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

- An object folder missing its `object.md` is not recognized as an object.
- A tag file with only comments or empty lines contributes no tags.
- Duplicate tags in the same file or across inherited and object tags are deduplicated.
- Creating an object whose path already exists returns `ErrObjectExists`.
- Deleting an object removes both metadata and actual data.
- Scanning stops at object boundaries; nested `object.md` files are ignored.
- Classify tags are inherited recursively; closer tag files override or augment more distant ones, with deduplication.
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

#### classify_tag table

| Column | Type | Notes |
|--------|------|-------|
| `classify_path` | string, primary key | Full classify path, e.g. `notes/work`. |
| `tag` | string, primary key | Inherited tag. |

#### schema_migrations table

| Column | Type | Notes |
|--------|------|-------|
| `version` | integer, primary key | Applied migration version. |
| `applied_at` | timestamp, not null | When the migration was applied. |

### 10.2 Tag Inheritance

Tags are inherited along the classify hierarchy. When an object is stored at path `2026/0714/2323/notes/work/xyz`, its effective tags are the union of:

1. Tags from `classify_tag` rows whose `classify_path` is a prefix of `notes/work` (e.g. `notes` and `notes/work`).
2. Tags from `object_tags` for `object_id = 'xyz'`.

Prefix matching is performed by comparing path segments, not raw strings, to avoid false matches such as `notes` matching `notes2`. The final tag list is deduplicated.

The exact query strategy (join, sub-query, or materialized cache) is an implementation detail. The important contract is that `Object.Tags` returned by the adapter is the fully merged set of inherited classify tags and object-specific tags.

### 10.3 Object Boundary in the Database Adapter

The database adapter does not scan directories. Object boundaries are implicit: every row in `objects` is one object. The rule that "scanning stops at `object/object.md`" is replaced by the rule that "each row represents one object, and no row may have a `path` that is a descendant of another object's `path`".

## 11. Extensibility

New adapters are added by implementing `MetadataAdapter` or `ActualDataAdapter`. The manager does not change when a new adapter is introduced. Configuration selects adapters via environment variables:

- `TOPSAILAI_DATA_METADATA_ADAPTER`: e.g. `local`, `postgres`.
- `TOPSAILAI_DATA_ACTUAL_ADAPTER`: e.g. `local`, `s3`.

Adapter-specific settings use the `TOPSAILAI_DATA_{ADAPTER}_{KEY}` pattern. For example:

- `TOPSAILAI_DATA_LOCAL_ROOT`
- `TOPSAILAI_DATA_POSTGRES_DSN`
- `TOPSAILAI_DATA_S3_BUCKET`

A factory function maps adapter names to constructors:

```go
type MetadataAdapterFactory func(cfg map[string]string) (MetadataAdapter, error)
```

### 11.1 Cross-Adapter DataRef

When metadata and actual data use different adapters, the manager coordinates the write:

1. The manager generates a stable `ObjectID`.
2. The actual-data adapter writes the payload and returns an opaque `DataRef`.
3. The metadata adapter stores the metadata along with the `DataRef`.

The metadata adapter treats `DataRef` as an opaque string and never interprets it. The actual-data adapter is the only component that resolves `DataRef` back to a payload.

## 12. Manager Operation Flows

The `Manager` is responsible for orchestrating metadata and actual data adapters so that cross-adapter operations remain consistent and recoverable.

### 12.1 Create Object

1. Validate object name and classify path (depth, characters).
2. Ask the metadata adapter whether the object already exists. If yes, return `ErrObjectExists`.
3. Acquire the object lock (write mode) by default.
4. Create metadata with status `creating` and a placeholder `DataRef` (empty or adapter-specific). This makes the incomplete object visible to recovery without exposing it as a normal result.
5. Write the actual data via the actual-data adapter. During creation, `WriteArchive`, `WriteFile`, `put`, and `put-archive` are allowed while status is `creating`. If this step fails:
   - The metadata remains in `creating` status.
   - Release the object lock.
   - Return the error; a later `gc` command can remove the orphaned metadata.
6. Update the metadata with the returned `DataRef` and set status to `active` and `UpdatedAt` to now. If this fails:
   - Attempt to delete the actual data written in step 5.
   - The metadata remains in `creating` status.
   - Release the object lock.
   - Return the metadata error wrapped with a cleanup note.
7. Release the object lock.

Objects in `creating` status are excluded from normal `List`, `Get`, and search results. To resolve a `creating` object, run `recover <id>` to finish creation if actual data exists, or `gc` to remove incomplete metadata and actual data. Re-running `create` with the same name while a `creating` object exists returns `ErrObjectExists` unless `--force` is used.

### 12.2 Update Actual Data

1. Read the existing metadata to obtain the current `DataRef`.
2. Acquire the object lock (write mode).
3. Write the new actual data via the actual-data adapter. The adapter returns a new `DataRef`.
4. Update the metadata with the new `DataRef` and set `UpdatedAt` to now.
5. If the metadata update fails, attempt to delete the new actual data and return the error.
6. After metadata update succeeds, the old actual data may be garbage-collected by the adapter or left for a background cleanup task.
7. Release the object lock.

A background cleanup process or the `gc` command may later remove old `ceased` metadata entries and any leftover empty directories, subject to the configurable retention window `TOPSAILAI_DATA_CEASED_RETENTION_DAYS`.

### 12.3 Delete Object (Soft Delete)

1. Read the existing metadata to obtain the `DataRef`.
2. Acquire the object lock (write mode).
3. Mark the object as `deleted`:
   - Local adapter: create `xyz.deleted` and update the local index/status.
   - Database adapter: update `objects.status` to `'deleted'`.
4. Delete the actual data via the actual-data adapter using the `DataRef`.
5. If actual-data deletion fails, the object remains in `deleted` status and can be retried later. Log the error. Running `delete <id>` on an already `deleted` object re-attempts actual-data deletion and proceeds to `ceased` if successful. The `gc` command may also finalize stale `deleted` objects whose actual data is already gone.
6. After actual data is removed, mark the object as `ceased`:
   - Local adapter: rename `xyz.deleted` to `xyz.ceased` and remove the object from the active index.
   - Database adapter: update `objects.status` to `'ceased'`.
7. Release the object lock.

### 12.4 Move Object

1. Read the existing metadata.
2. Verify the object status is `active`; only `active` objects may be moved.
3. Acquire the object lock (write mode).
4. Compute the new full path from the object's creation time, the supplied classify directories, and the object name. If the adapter supports it, call `ActualDataAdapter.Move(ctx, id, newRef)` with that computed reference. If the adapter does not support move, rewrite the payload and obtain a new `DataRef`.
5. Update the metadata `Path`, `DataRef` (if adapter-specific), and `UpdatedAt`.
6. Release the object lock.

### 12.5 Failure Strategy Summary

- Actual data is written before metadata so that a dangling `DataRef` never points to missing data.
- Metadata is deleted before actual data so that the object becomes invisible to users even if payload cleanup fails.
- Soft delete provides a recoverable intermediate state (`deleted`) between `active` and `ceased`.
- Lock acquisition failures return `ErrObjectLocked` immediately without side effects.
- All cleanup attempts are logged; failures during cleanup do not hide the original error.

## 13. Configuration and Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TOPSAILAI_DATA_ROOT` | yes (local) | none | Root directory for the local adapter. |
| `TOPSAILAI_DATA_METADATA_ADAPTER` | no | `local` | Metadata adapter name. |
| `TOPSAILAI_DATA_ACTUAL_ADAPTER` | no | `local` | Actual data adapter name. |
| `TOPSAILAI_DATA_LOG_LEVEL` | no | `INFO` | Log level for the CLI. |
| `TOPSAILAI_DATA_READ_LOCK` | no | `0` | If `1`, read operations acquire the object lock. |
| `TOPSAILAI_DATA_INCLUDE_DELETED` | no | `false` | If `true`, list/search operations include objects with status `deleted` or `ceased`. |
| `TOPSAILAI_DATA_CEASED_RETENTION_DAYS` | no | `30` | Number of days to retain `ceased` metadata before cleanup. |
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
- Tag parsing, recursive inheritance, and deduplication.
- Metadata scanning and object-boundary detection.
- Actual data archive read/write, single-file read/write, and deletion.
- Adapter factory selection.
- Object locking and soft-delete state transitions.
- Schema version migration and downgrade refusal.

Integration tests verify CLI commands against a temporary root directory configured via the `TOPSAILAI_DATA_ROOT` environment variable.

## 16. Project Structure

```text
/TopsailAI/src/topsailai_data/
├── README.md
├── Makefile
├── docs/
│   └── DESIGN.md
├── cli/
│   └── topsaildata/
│       └── main.go
├── src/
│   ├── manager.go
│   ├── models.go
│   ├── errors.go
│   ├── adapters/
│   │   ├── interfaces.go
│   │   └── local/
│   │       ├── metadata.go
│   │       ├── actual.go
│   │       ├── tags.go
│   │       ├── scan.go
│   │       ├── lock.go
│   │       └── local_test.go
│   └── cmd/
│       └── commands.go
└── tests/
    └── integration/
        └── cli_test.go
```

## 17. Future Work

- Implement `postgres` metadata adapter.
- Implement `s3` actual data adapter.
- Add search indexing for fast tag-based queries.
- Add import/export commands for backup and migration.

## 18. Summary

`topsailai_data` separates metadata from actual data through adapter interfaces, enabling flexible backend combinations. The local adapter uses a time-based directory layout, mandatory `object.md` files as actual-data carriers, optional tag files, and recursive classify tag inheritance. Object boundaries are detected by the presence of a same-named `.md` file, and scanning stops at those boundaries. The metadata model includes `ID`, `Name`, `Path`, `CreatedAt`, `UpdatedAt`, `Status`, `SchemaVersion`, and `Tags`, with `ObjectID` stable across moves. A database metadata adapter can implement the same interface using an `objects` table, an `object_tags` table, and a `classify_tag` relationship table. The design prioritizes extensibility, clear conventions, and testability.
