---
name: topsailai_data
author: DawsonLin
description: |
  Skill for operating the topsailai_data CLI, a local-first object store that
  separates metadata from actual data through pluggable adapters.

  Trigger this skill whenever the user wants to manage structured data objects
  stored by topsailai_data: create, read, update, delete, search, move, tag, or
  garbage-collect objects. Also use it when the user asks to test, inspect, or
  troubleshoot the topsailai_data CLI or its stored data.

  When the user refers to historical records, past notes, or uses phrases like
  "remember that...", "I recall...", or "there was something about X", ALWAYS
  search the topsailai_data store through the CLI first. Do not answer from
  conversation memory alone or fabricate object IDs, paths, or contents.

  Typical intents that should route here:
  - "create a note/document/object in topsailai_data"
  - "list/search/show my objects" or "find objects tagged with X"
  - "add/remove a tag from object X"
  - "move object X to classify path Y"
  - "delete object X" or "clean up topsailai_data"
  - "run gc" or "recover object X"
  - "test topsailai_data" or "smoke test the CLI"
  - "remember that note about X" or "find my previous note on Y"
  - Personal lessons learned

  Common scenarios include local knowledge bases, project document storage,
  tagged data archiving, soft-delete and gc workflows, automated test data
  management, and future db/s3 backend extensions.

  > You Must use the CLI to manage data, DONOT USE shell command!
---

# topsailai_data

## When to use

Use this skill when the user intends to manage data objects through the
`topsailai_data` CLI. The tool stores **metadata** (name, path, tags, status) and
**actual data** (files, archives) through independent adapters. The current
implementation focuses on the **local adapter**, which keeps everything on the
local filesystem under a configurable root directory.

### User intents that trigger this skill

| Intent | Example user phrases |
|--------|----------------------|
| Create objects | "create an object", "add a note", "store a document", "create X under classify Y" |
| Read/query objects | "list my objects", "show object X", "search for X", "find objects tagged Y" |
| Update objects/tags | "update object X", "add tag Y to X", "remove tag Y from X" |
| Move objects | "move object X to path Y", "reclassify object X" |
| Delete objects | "delete object X", "remove object X", "clean up topsailai_data" |
| Recover/gc | "recover object X", "run gc", "clean up creating/ceased objects" |
| Test/inspect | "test topsailai_data", "smoke test the CLI", "check my data" |

### Common usage scenarios

- **Local knowledge base**: create notes under classify paths such as
  `work/2026` or `personal/ideas`, tag them, and search later.
- **Project document storage**: store project artifacts, READMEs, or design
  documents as objects and retrieve them by name or tag.
- **Tagged data archiving**: organize files with classify tags inherited
  recursively, then filter lists and searches by tag.
- **Soft-delete and gc workflows**: delete objects safely (metadata transitions
  through `deleted` to `ceased`), then run `gc` to finalize cleanup after the
  retention window.
- **Automated test data management**: configure a temporary
  `TOPSAILAI_DATA_ROOT` in scripts or CI to create isolated test objects and
  clean them up with `gc`.
- **Future backend extensions**: the same CLI commands work once additional
  metadata or actual-data adapters (e.g. postgres, s3) are enabled through
  environment variables.

### Example: one object per project with multiple Markdown notes

For simple project-oriented note management, model each project as exactly one
object. Store all notes for that project as Markdown files inside the object's
actual data instead of creating one object per note.

Use a stable project code as the object ID, place all project objects under the
same classify path, and use the mandatory same-name Markdown file as the
project index or home page:

```text
Object ID: project-a
Classify: projects

project-a/
├── project-a.md
├── overview.md
├── decisions.md
├── deployment.md
├── design/
│   ├── architecture.md
│   └── database.md
└── meetings/
    ├── 2026-07-20.md
    └── 2026-07-23.md
```

Create one object for each project:

```
bin/topsailai_data create project-a --classify projects
bin/topsailai_data create project-b --classify projects
bin/topsailai_data create project-c --classify projects
```

Add or replace an individual project note with `put`. When the source already
exists as a file, always use `--from`:

```
bin/topsailai_data put project-a overview.md --from ./notes/overview.md
bin/topsailai_data put project-a design/architecture.md --from ./notes/architecture.md
bin/topsailai_data put project-a meetings/2026-07-23.md --from ./notes/2026-07-23.md
```

Inspect the project and read a specific note through the CLI:

```
bin/topsailai_data show project-a
bin/topsailai_data get project-a design/architecture.md
```

In this model:

- One project equals one object ID.
- The classify path can remain simply `projects`; the object ID distinguishes
  projects.
- The mandatory `<object>.md` file is the project's index or home page.
- Other Markdown files and subdirectories contain the project's notes.
- Tags describe the project as a whole, such as `active`, `paused`, or
  `archived`; they should not describe individual files.
- `search` locates project objects by object name, classify path, or object
  tags. It does not index each internal Markdown file as a separate object.
- Use `show` to inspect a project's file tree and `get` when the project ID and
  note path are known.

If the request is about general file-system operations outside the
`topsailai_data` root, or about editing the source code of topsailai_data
itself, use the appropriate development tools instead of this skill.

## Build

From the project root:

```
make build
```

This compiles the CLI to `bin/topsailai_data`.

Other useful targets:

```
make test
make vet
make clean
make install
```

## Run

The CLI is invoked through the `bin/topsailai_data` binary. Place or build the binary at `skills/topsailai_data/bin/topsailai_data` (or `bin/topsailai_data` from the project root) before using the skill.

The CLI requires a root directory. Set it through an environment variable or a `.env` file:

```
export TOPSAILAI_DATA_ROOT=${HOME}/.topsailai/data
bin/topsailai_data <command> [args]
```

If `TOPSAILAI_DATA_ROOT` is not set, the CLI defaults to `${HOME}/.topsailai/data/`.

Invoke without arguments to show usage and available commands:

```
bin/topsailai_data
```

## Mandatory input rule

When the source content already exists as a file on disk, you MUST pass it to the CLI through the `--from <path>` option. Do **not** use shell redirection, pipes, or heredocs to feed file content into `stdin`.

This rule applies to commands that accept `--from`, such as `create` and `put`.

Correct:

```
bin/topsailai_data create note --from /path/to/note.md
bin/topsailai_data put note attachment.txt --from /path/to/attachment.txt
```

Incorrect:

```
cat /path/to/note.md | bin/topsailai_data create note
bin/topsailai_data create note < /path/to/note.md
```

Only use `stdin` when the data is generated in memory and has no corresponding file.

> **Warning: when using `stdin`, provide all parameters on the command line.**
>
> Commands that read content from `stdin` (for example `create <object> -`, `put <id> <file> --from -`, or `put-archive <id> -`) still require every positional argument and flag to be passed explicitly on the command line.
>
> Because `stdin` is occupied by the content stream, the CLI cannot interactively prompt for missing values such as the object name, classify path, or tags. If a required parameter is omitted, the command will block waiting for input and appear to hang.
>
> Correct (all parameters are present):
>
> ```
> echo "inline content" | bin/topsailai_data create note --tag quickstart
> echo "attachment data" | bin/topsailai_data put note attachment.txt --from -
> tar -cf - ./files | bin/topsailai_data put-archive note -
> ```
>
> Incorrect (missing parameters cause the CLI to hang):
>
> ```
> echo "inline content" | bin/topsailai_data create
> echo "attachment data" | bin/topsailai_data put note --from -
> tar -cf - ./files | bin/topsailai_data put-archive
> ```

## Skill layout

```text
skills/topsailai_data/
  bin/topsailai_data      # the CLI binary consumed by this skill
  config/example.env      # example environment variables
```

The `bin/` directory holds the executable. Helper shell scripts are intentionally not provided; all operations go through `bin/topsailai_data`.

## Quick start

```
export TOPSAILAI_DATA_ROOT=./data
make build
bin/topsailai_data create hello --tag quickstart
bin/topsailai_data list
bin/topsailai_data show hello
```

## Commands

| Command | Usage | Description |
|---------|-------|-------------|
| `create` | `create <object> [--classify dir1/dir2/...] [--tag t1,t2] [--from <file\|archive\|->]` | Create a new object. Writes a mandatory `<object>.md` marker and optional tags. `--from` accepts a plain file, a tar archive, or `-` for stdin; when omitted, content is read from stdin. If an object with the same name already exists in `ceased` status, the ceased object is purged and the new object is created; `active`, `creating`, and `deleted` objects cause `ErrObjectExists`. |
| `show` | `show <id>` | Display metadata, the `<object>.md` content, and the folder structure of an object. |
| `list` | `list [--include-deleted] [--offset n] [--limit n] [--format yaml\|json] [--sort time:desc\|time:asc]` | List active objects, optionally paginated and sorted by the time prefix of the object path. Default format is YAML; use `json` for machine-readable output. Default sort is `time:desc` (newest first). |
| `search` | `search <query> [--include-deleted] [--offset n] [--limit n] [--format yaml\|json] [--sort time:desc\|time:asc]` | Search objects by name, tag, or classify path. Use `|` in `<query>` for OR logic (e.g. `foo\|bar`). Spaces, tabs, and backslash escapes are not supported. Results are sorted by the time prefix of the object path; default is `time:desc` (newest first). |
| `tag` | `tag add <id> <tag>` or `tag remove <id> <tag>` | Add or remove an object-specific tag. |
| `move` | `move <id> <new-classify...>` | Move an active object to a different classify path. The ID and name stay the same. |
| `delete` | `delete <id>` | Soft-delete an active object. Marks the object as `deleted` but preserves actual data so it can be recovered. Finalization removes actual data and transitions the object to `ceased`. |
| `recover` | `recover <id> [--from <archive\|->]` | Restore a `deleted` object back to `active`. The object's actual data must still exist, or be re-supplied with `--from`. Returns an error for `creating`, `active`, or `ceased` objects. |
| `gc` | `gc [--dry-run] [--status creating\|deleted\|ceased]` | Clean up `creating` objects, finalize `deleted` objects to `ceased`, or remove `ceased` objects. Default `gc` honors `TOPSAILAI_DATA_CEASED_RETENTION_DAYS`. When `--status ceased` is explicitly provided, all ceased objects are removed immediately. |
| `get` | `get <id> <object-file>` | Read a single actual-data file to stdout. The raw byte stream is preserved, so this works for binary files such as images, videos, and compiled executables. |
| `get-archive` | `get-archive <id>` | Output the object's actual data as a tar archive to stdout. |
| `put` | `put <id> <dest-file> [--from <file\|->]` | Write a single file into the object's actual data. `<dest-file>` is the name inside the object; `--from` accepts a local file or `-` for stdin; when omitted, content is read from stdin. |
| `put-archive` | `put-archive <id> <archive\|->` | Replace object actual data from a tar archive. Use `-` to read the archive from stdin. |

### Command examples

Create:

```
bin/topsailai_data create note --classify work/2026 --tag work,important
bin/topsailai_data create report --from report.md
bin/topsailai_data create bundle --from bundle.tar
echo "inline content" | bin/topsailai_data create inline-note
```

Read metadata:

```
bin/topsailai_data show <id>
bin/topsailai_data list [--include-deleted] [--offset 0] [--limit 10] [--format yaml|json]
bin/topsailai_data search <query> [--include-deleted] [--offset 0] [--limit 10] [--format yaml|json]
```

#### Search query syntax

- `search` performs a case-insensitive substring match against object names, tags, and classify paths.
- Use `|` to separate multiple terms. An object matches if any term matches (OR logic). Example: `search foo|bar` matches objects whose name, tags, or classify path contain `foo` or `bar`.
- Spaces, tabs, and backslash escapes are not supported in search queries. To match multi-word tags, search for one word at a time.

#### Sorting results

Both `list` and `search` accept a `--sort` option that orders results by the time prefix (`YYYY/MMDD/HHMM`) extracted from each object's path.

- `time:desc` — newest first (default when `--sort` is omitted).
- `time:asc` — oldest first.

Examples:

```
bin/topsailai_data list --sort time:desc
bin/topsailai_data search work --sort time:asc
```

Modify tags:

```
bin/topsailai_data tag add <id> <tag>
bin/topsailai_data tag remove <id> <tag>
```

Move:

```
bin/topsailai_data move <id> <new-classify...>
bin/topsailai_data move hello archive/2026
```

Delete and cleanup:

```
bin/topsailai_data delete <id>
bin/topsailai_data gc [--dry-run] [--status creating|deleted|ceased]
bin/topsailai_data recover <id> [--from <archive|->]
```

Actual data I/O:

```
bin/topsailai_data get <id> <object-file>
bin/topsailai_data get-archive <id> > backup.tar
bin/topsailai_data put <id> <dest-file> [--from <file|->]
bin/topsailai_data put-archive <id> <archive|->
```

#### Binary files with `get`

`get` writes the file's raw bytes to stdout without any text conversion, line-ending changes, or truncation. This makes it suitable for binary payloads such as images, videos, compiled executables, compressed archives, or PDFs.

To save the binary data to a file, redirect stdout directly to a file:

```
bin/topsailai_data put myobj photo.png --from ./photo.png
bin/topsailai_data get myobj photo.png > photo-copy.png
```

The redirected file is an exact byte-for-byte copy of the stored file. You can then open or process it with normal tools:

```
open photo-copy.png
xxd photo-copy.png | head
```

Avoid piping `get` output through tools that interpret or re-encode the stream (for example `cat` in some terminals, or text-processing utilities). Redirect stdout straight to the destination file to keep the data intact.

### Output format

`list` and `search` support two output formats selected with `--format yaml|json`. The default format is YAML.

`--format yaml` (default) prints the result as a YAML array. Each object is represented with snake_case keys:

```yaml
- id: hello
  name: hello
  path: 2026/0714/2323/hello
  status: active
  tags:
    - quickstart
  created_at: 2026-07-14T23:23:00Z
  updated_at: 2026-07-14T23:23:00Z
  schema_version: 1
  data_ref: 2026/0714/2323/hello
```

Use `--offset` and `--limit` to paginate. When no objects match, `list` and `search` print an empty YAML array (`[]`).

`--format json` prints the full result as a pretty-printed JSON array:

```json
[
  {
    "id": "hello",
    "name": "hello",
    "path": "2026/0714/2323/hello",
    "status": "active",
    "tags": ["quickstart"],
    "created_at": "2026-07-14T23:23:00Z",
    "updated_at": "2026-07-14T23:23:00Z",
    "schema_version": 1,
    "data_ref": "2026/0714/2323/hello"
  }
]
```

`show` prints three sections for an object: metadata, the content of `<object>.md`, and the folder structure.

### show output format

#### Metadata section

The first section lists the object's stored metadata. All timestamps are formatted as RFC3339 strings.

| Field | Description |
|-------|-------------|
| `ID` | Stable object identifier. In the local adapter this equals the object name. |
| `Name` | Object name (the folder name). |
| `Path` | Full relative path from the root to the object folder. |
| `Status` | Lifecycle status: `creating`, `active`, `deleted`, or `ceased`. |
| `SchemaVersion` | Persistent storage format version of the object record. |
| `CreatedAt` | Object creation timestamp. |
| `UpdatedAt` | Last modification timestamp. |
| `DeletedAt` | Present only when the object has been soft-deleted. |
| `CeasedAt` | Present only when the object has been finalized after deletion. |
| `Tags` | Merged list of inherited classify tags and object-specific tags. Empty when there are no tags. |
| `DataRef` | Opaque reference to the actual data, managed by the actual-data adapter. |

#### Markdown content section

The second section is labeled `--- Markdown ---` and prints the contents of the object's mandatory `<object>.md` file. If the file is empty, the section prints `(empty)`.

#### Folder structure section

The third section is labeled `--- folder structure ---` and prints a tree-style listing of the object folder. The mandatory `<object>.md` marker file and metadata marker files (`.tags`, `.lock`, `.deleted`, `.ceased`, `metadata.json`) are excluded from the tree so only user actual data is shown.

If the object folder contains no files besides the mandatory `<object>.md`, the section prints:

```text
hello/
└── hello.md
no additional files
```

#### Example

```text
ID:            hello
Name:          hello
Path:          2026/0714/2323/hello
Status:        active
SchemaVersion: 1
CreatedAt:     2026-07-14T23:23:00+08:00
UpdatedAt:     2026-07-14T23:23:00+08:00
Tags:          quickstart
DataRef:       2026/0714/2323/hello

--- Markdown ---
Hello, world!

--- folder structure ---
hello/
└── hello.md
no additional files
```

An object with extra actual data files might look like:

```text
--- folder structure ---
hello/
├── hello.md
├── attachment.txt
└── assets/
    └── screenshot.png
```

## Data layout conventions

### Object folder rule

Every object is a folder whose name matches the object name. The folder must contain a file with the same name and a `.md` extension. This file is actual data, but its presence marks the folder boundary.

```text
hello/
  hello.md
```

### Time-based path

Objects are placed under a time prefix derived from the creation time using local time:

```text
{ROOT}/YYYY/MMDD/HHMM/<object>
```

Example for an object created on 2026-07-14 at 23:23:

```text
./data/2026/0714/2323/hello
```

### Object folder contents

An object named `hello` is stored as a folder `hello` that must contain a file named `hello.md`. The folder may also contain other files and subdirectories as actual data.

```text
hello/
  hello.md          # mandatory actual-data marker
  hello.tags        # optional object-specific tags
  attachments/      # optional actual data
    screenshot.png
```

### Classify directories

After the time prefix you may add custom classify directories. The total depth from root to the object folder must not exceed 11 levels. The time prefix consumes 3 levels and the object folder consumes 1 level, leaving up to 7 extra classify levels.

Example with classify path `projects/demo`:

```text
./data/2026/0714/2323/projects/demo/hello
```

Too deep:

```text
2026/0714/2323/a/b/c/d/e/f/g/h/hello  # 12 levels, exceeds limit
```

### Tag files

- Object tag file: `<object>.tags` inside the object folder.
- Classify tag file: `<classify-name>.tags` inside a classify directory; applies recursively to all objects under that directory.

Tag file format:

```text
# this is a comment
project-alpha
urgent
```

Lines starting with `#`, `;`, `//`, or `--` (after optional whitespace) are comments. Empty lines are ignored. Tags are trimmed and deduplicated.

### Tag inheritance

Classify tag files apply recursively. Object tag files apply only to that object. Inherited and object tags are merged and deduplicated.

```text
2026/0714/2323/
  2323.tags            # applies to all objects under 2323/
  projects/
    projects.tags      # applies to all objects under projects/
    demo/
      demo.tags        # applies to all objects under demo/
      hello/
        hello.md
        hello.tags     # applies only to hello
```

Object `hello` receives the merged tags from `2323.tags`, `projects.tags`, `demo.tags`, and `hello.tags`.

### Scanning rule

When scanning for objects, the adapter stops at any directory that contains a file named `{directory-name}.md`. Subdirectories inside that folder are not scanned as independent objects.

A file such as `hello/sub/hello.md` does **not** make `sub` an object folder; only `hello/hello.md` makes `hello` an object folder.

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TOPSAILAI_DATA_ROOT` | no | `${HOME}/.topsailai/data` | Root directory for local storage. |
| `TOPSAILAI_DATA_METADATA_ADAPTER` | no | `local` | Metadata adapter name. |
| `TOPSAILAI_DATA_ACTUAL_DATA_ADAPTER` | no | `local` | Actual-data adapter name. |
| `TOPSAILAI_DATA_READ_LOCK` | no | `0` | Acquire advisory locks on read operations. |
| `TOPSAILAI_DATA_INCLUDE_DELETED` | no | `false` | Include `deleted`/`ceased` objects in list/search. |
| `TOPSAILAI_DATA_CEASED_RETENTION_DAYS` | no | `30` | Retention window for ceased metadata. |
| `TOPSAILAI_DATA_LOG_LEVEL` | no | `INFO` | Log level. |

Variables prefixed with `TOPSAILAI_DATA_ADAPTER_` are passed to adapter factories as adapter-specific settings.

Example `.env`:

```
TOPSAILAI_DATA_ROOT=./data
TOPSAILAI_DATA_METADATA_ADAPTER=local
TOPSAILAI_DATA_ACTUAL_DATA_ADAPTER=local
TOPSAILAI_DATA_INCLUDE_DELETED=false
TOPSAILAI_DATA_CEASED_RETENTION_DAYS=30
```

## Notes and common pitfalls

- **Object ID equals object name** in the local adapter. Two objects with the same name cannot exist at different paths.
- **Always create through the CLI** rather than manually creating folders, so metadata and the mandatory `.md` marker are written consistently.
- **Creating over a ceased object** purges the ceased object (metadata and actual data) and creates the new object with the same name. Creating over `active`, `creating`, or `deleted` objects still returns `ErrObjectExists`.
- **Tar archives** are extracted into the object folder. Symbolic links inside tar archives are rejected to prevent directory traversal.
- **`gc --status deleted`** finalizes `deleted` objects to `ceased`. After finalization, the object is subject to `TOPSAILAI_DATA_CEASED_RETENTION_DAYS` unless `gc --status ceased` is used to remove it immediately.
- **`gc --status ceased`** removes all `ceased` objects immediately, ignoring the retention window. Default `gc` only removes ceased objects after the retention window expires.
- **Deleted/ceased objects** are hidden from normal `list` and `search` unless `--include-deleted` is used. The `show` command, however, always resolves an object by ID and displays its metadata regardless of status. For `deleted` and `ceased` objects the actual-data sections (`--- Markdown ---` and `--- folder structure ---`) are omitted and replaced with a note that actual data is unavailable, because the payload may have been partially or fully removed.
- **`recover`** only restores objects whose status is `deleted` back to `active`. It does not operate on `creating`, `active`, or `ceased` objects.
- **Avoid manual changes**: do not create or rename object folders manually. Use the CLI so that metadata, the `.md` marker, and tag files stay consistent.

## See also

- `bin/topsailai_data` — the CLI binary used by this skill
- `config/example.env`

## Lesson learned: use the CLI as the only abstraction layer

When managing topsailai_data objects (notes or any other type), ALWAYS use
the topsailai_data CLI as the primary abstraction layer. Use commands such as
`list`, `show`, `get`, `put`, `tag`, `move`, `delete`, `recover`, and `gc` to
locate, read, and modify objects. Do NOT use shell commands such as `find`,
`ls`, or direct filesystem access to probe the storage backend, adapter
directories, or object paths. If the CLI location or data root is unclear,
read this skill documentation first rather than exploring the filesystem.
