---
name: topsailai-data
author: DawsonLin
description: |
  Skill for operating the topsailai-data CLI, a local-first object store that
  separates metadata from actual data through pluggable adapters.

  Trigger this skill whenever the user wants to manage structured data objects
  stored by topsailai-data: create, read, update, delete, search, move, tag, or
  garbage-collect objects. Also use it when the user asks to test, inspect, or
  troubleshoot the topsailai-data CLI or its stored data.

  When the user refers to historical records, past notes, or uses phrases like
  "remember that...", "I recall...", or "there was something about X", ALWAYS
  search the topsailai-data store through the CLI first. Do not answer from
  conversation memory alone or fabricate object IDs, paths, or contents.

  Typical intents that should route here:
  - "create a note/document/object in topsailai-data"
  - "list/search/show my objects" or "find objects tagged with X"
  - "add/remove a tag from object X"
  - "move object X to classify path Y"
  - "delete object X" or "clean up topsailai-data"
  - "run gc" or "recover object X"
  - "test topsailai-data" or "smoke test the CLI"
  - "remember that note about X" or "find my previous note on Y"
  - Personal lessons learned

  Common scenarios include local knowledge bases, project document storage,
  tagged data archiving, soft-delete and gc workflows, automated test data
  management, and future db/s3 backend extensions.

  > You Must use the CLI to manage data, DONOT USE shell command!

  When the user expresses praise or positive feedback (for example "不错",
  "很好", "good", or similar), automatically organize the relevant discussion
  or outcome into a topsailai-data note object. Do not wait for an explicit
  request; treat praise as a signal that the content is worth preserving.
---

# topsailai-data

## When to use

Use this skill when the user intends to manage data objects through the
`topsailai-data` CLI. The tool stores **metadata** (name, path, description, tags, status) and
**actual data** (files, archives) through independent adapters. The current
implementation focuses on the **local adapter**, which keeps everything on the
local filesystem under a configurable root directory.

### User intents that trigger this skill

| Intent | Example user phrases |
|--------|----------------------|
| Create objects | "create an object", "add a note", "store a document", "create X under classify Y" |
| Read/query objects | "list my objects", "show object X", "search for X", "find objects tagged Y" |
| Update objects/tags | "update object X", "update object X description", "add tag Y to X", "remove tag Y from X" |
| Move objects | "move object X to path Y", "reclassify object X" |
| Delete objects | "delete object X", "remove object X", "clean up topsailai-data" |
| Recover/gc | "recover object X", "run gc", "clean up creating/ceased objects" |
| Test/inspect | "test topsailai-data", "smoke test the CLI", "check my data" |

### Common usage scenarios

- **Local knowledge base**: create notes under classify paths such as
  `work/2026` or `personal/ideas`, tag them, and search later.
- **Project document storage**: store project artifacts, READMEs, or design
  documents as objects and retrieve them by name or tag.
- **Tagged data archiving**: attach tags to objects and filter lists and
  searches by tag.
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

Name every project object with its workspace and project names so IDs remain
clear and globally unique:

```text
project--{workspace-name}--{project-name}
```

Use exactly two hyphens (`--`) between components. Keep each component stable,
lowercase, and concise. For example, the `skill-hub` project in the `qrew`
workspace uses `project--qrew--skill-hub`; do not use only `skill-hub` as its
object ID.

Place all project objects under the same classify path, and use the mandatory
same-name Markdown file as the project index or home page:

```text
Object ID: project--qrew--skill-hub
Classify: projects

project--qrew--skill-hub/
├── project--qrew--skill-hub.md
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

Create one object for each project. Each project object needs markdown
content and a description:

```
bin/topsailai-data create project--qrew--data-hub --classify projects --description "Data hub project notes" --from ./projects/qrew/data-hub/project.md
bin/topsailai-data create project--qrew--qguard --classify projects --description "QGuard project notes" --from ./projects/qrew/qguard/project.md
bin/topsailai-data create project--qrew--skill-hub --classify projects --description "Skill hub project notes" --from ./projects/qrew/skill-hub/project.md
```

Add or replace an individual project note with `put`. When the source already
exists as a file, always use `--from`:

```
bin/topsailai-data put project--qrew--skill-hub overview.md --from ./notes/overview.md
bin/topsailai-data put project--qrew--skill-hub design/architecture.md --from ./notes/architecture.md
bin/topsailai-data put project--qrew--skill-hub meetings/2026-07-23.md --from ./notes/2026-07-23.md
```

Inspect the project and read a specific note through the CLI:

```
bin/topsailai-data show project--qrew--skill-hub
bin/topsailai-data get project--qrew--skill-hub design/architecture.md
```

In this model:

- One project equals one object ID.
- Every project object ID follows
  `project--{workspace-name}--{project-name}` with exactly two hyphens between
  components.
- The classify path can remain simply `projects`; the workspace-scoped object
  ID distinguishes projects and prevents collisions between workspaces.
- The mandatory `<object>.md` file is the project's index or home page.
- Other Markdown files and subdirectories contain the project's notes.
- Tags describe the project as a whole, such as `active`, `paused`, or
  `archived`; they should not describe individual files.
- `search` locates project objects by object name, classify path, or object
  tags. It does not index each internal Markdown file as a separate object.
- Use `show` to inspect a project's file tree and `get` when the project ID and
  note path are known.

If the request is about general file-system operations outside the
`topsailai-data` root, or about editing the source code of topsailai-data
itself, use the appropriate development tools instead of this skill.

## Object Markdown frontmatter

Every `{name}.md` document inside an object SHOULD include a YAML frontmatter
block. For the mandatory `<object>.md` file, the frontmatter SHOULD include a
`description` field because a description is required when creating an object.
The description may also be supplied with `--description`, but providing it in
frontmatter makes the object self-describing.

The frontmatter block SHOULD contain at least these two fields:

- `name`: the document name, usually matching the file name without the `.md`
  extension. This is the canonical identifier of the document within the object.
- `description`: a concise summary of the document's purpose and contents.

The meaning and style of these fields follow the same convention as the
`SKILL.md` frontmatter of this skill: `name` names the artifact, and
`description` explains what it is for and when to use it.

Example:

```yaml
---
name: architecture
description: |
  High-level architecture decisions for the skill-hub project.
  Use this document to understand service boundaries and data flow.
---
```

The CLI uses `description` as the object description when creating an object
from `--from <file>` if no `--description` flag is provided. A well-formed
frontmatter therefore makes objects self-describing and improves `list`,
`search`, and `show` output.

## Build

From the project root:

```
make build
```

This compiles the CLI to `bin/topsailai-data`.

Other useful targets:

```
make test
make vet
make clean
make install
```

## Run

The CLI is invoked through the `bin/topsailai-data` binary. Place or build the binary at `skills/topsailai-data/bin/topsailai-data` (or `bin/topsailai-data` from the project root) before using the skill.

The CLI requires a root directory. Set it through an environment variable or a `.env` file:

```
export TOPSAILAI_DATA_ROOT=${HOME}/.topsailai/data
bin/topsailai-data <command> [args]
```

If `TOPSAILAI_DATA_ROOT` is not set, the CLI defaults to `${HOME}/.topsailai/data/`.

Invoke without arguments to show usage and available commands:

```
bin/topsailai-data
```

## Mandatory input rule

When the source content already exists as a file on disk, you MUST pass it to the CLI through the `--from <path>` option. Do **not** use shell redirection, pipes, or heredocs to feed file content into `stdin`.

This rule applies to commands that accept `--from`, such as `create` and `put`.

Correct:

```
bin/topsailai-data create note --description "Note description" --from /path/to/note.md
bin/topsailai-data put note attachment.txt --from /path/to/attachment.txt
```

Incorrect:

```
cat /path/to/note.md | bin/topsailai-data create note
bin/topsailai-data create note < /path/to/note.md
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
> echo "---
> description: Inline note
> ---
>
> inline content" | bin/topsailai-data create note --tag quickstart
> echo "attachment data" | bin/topsailai-data put note attachment.txt --from -
> tar -cf - ./files | bin/topsailai-data put-archive note -
> ```
>
> Incorrect (missing parameters cause the CLI to hang):
>
> ```
> echo "inline content" | bin/topsailai-data create
> echo "attachment data" | bin/topsailai-data put note --from -
> tar -cf - ./files | bin/topsailai-data put-archive
> ```

## Skill layout

```text
skills/topsailai-data/
  bin/topsailai-data      # the CLI binary consumed by this skill
  config/example.env      # example environment variables
```

The `bin/` directory holds the executable. Helper shell scripts are intentionally not provided; all operations go through `bin/topsailai-data`.

## Quick start

```
export TOPSAILAI_DATA_ROOT=./data
make build
echo "# Hello" | bin/topsailai-data create hello --description "A hello object" --tag quickstart
bin/topsailai-data list
bin/topsailai-data show hello
```

## Commands

| Command | Usage | Description |
|---------|-------|-------------|
| `create` | `create <object> [--classify dir1/dir2/...] [--description <text>] [--tag t1,t2] [--from <file\|archive\|->]` | Create a new object. **Markdown content is required** and must contain the mandatory `<object>.md` file; it can be supplied via `--from` or stdin. **A description is required** and may be provided with `--description` or extracted from the `description` field in the YAML frontmatter of `<object>.md`. If neither source provides a description, the command fails. `--from` accepts a plain file, a tar archive, or `-` for stdin; when omitted, content is read from stdin. If an object with the same name already exists in `ceased` status, the ceased object is purged and the new object is created; `active`, `creating`, and `deleted` objects cause `ErrObjectExists`. |
| `show` | `show <id>` | Display metadata, the `<object>.md` content, and the folder structure of an object. |
| `update` | `update <id> [--description <text>]` | Update an active object's metadata. Currently supports updating the description. Pass an empty value (`--description ""`) to clear the description. |
| `list` | `list [--tag t1,t2] [--include-deleted] [--offset n] [--limit n] [--format yaml\|json] [--sort time:desc\|time:asc] [--with-stat]` | List active objects, optionally filtered by tag, paginated, and sorted by the time prefix of the object path. Default format is YAML; use `json` for machine-readable output. Default sort is `time:desc` (newest first). `--with-stat` attaches usage counters without incrementing them. |
| `search` | `search <query> [--include-deleted] [--offset n] [--limit n] [--format yaml\|json] [--sort time:desc\|time:asc] [--with-stat]` | Search objects by name, tag, or classify path. Use `\|` in `<query>` for OR logic (e.g. `foo\|bar`). Spaces, tabs, and backslash escapes are not supported. Results are sorted by the time prefix of the object path; default is `time:desc` (newest first). `--with-stat` attaches usage counters without incrementing them. |
| `tag` | `tag add <id> <tag>` or `tag remove <id> <tag>` | Add or remove an object-specific tag. |
| `move` | `move <id> <new-classify...>` | Move an active object to a different classify path. The ID and name stay the same. |
| `delete` | `delete <id>` | Soft-delete an active object. Marks the object as `deleted` but preserves actual data so it can be recovered. Finalization removes actual data and transitions the object to `ceased`. |
| `recover` | `recover <id> [--from <archive\|->]` | Restore a `deleted` object back to `active`. The object's actual data must still exist, or be re-supplied with `--from`. Returns an error for `creating`, `active`, or `ceased` objects. |
| `gc` | `gc [--dry-run] [--status creating\|deleted\|ceased]` | Clean up `creating` objects, finalize `deleted` objects to `ceased`, or remove `ceased` objects. Default `gc` honors `TOPSAILAI_DATA_CEASED_RETENTION_DAYS`. When `--status ceased` is explicitly provided, all ceased objects are removed immediately. |
| `get` | `get <id> <object-file>` | Read a single actual-data file to stdout. The raw byte stream is preserved, so this works for binary files such as images, videos, and compiled executables. |
| `get-archive` | `get-archive <id>` | Output the object's actual data as a tar archive to stdout. |
| `put` | `put <id> <dest-file> [--from <file\|->]` | Write a single file into the object's actual data. `<dest-file>` is the name inside the object; `--from` accepts a local file or `-` for stdin; when omitted, content is read from stdin. |
| `put-archive` | `put-archive <id> <archive\|->` | Replace object actual data from a tar archive. Use `-` to read the archive from stdin. |
| `file` | `file <subcommand> [arguments] --object <id>` | Read, inspect, and edit files inside one data object. Every subcommand requires `--object <id>`. See the file command group section. |

### Command examples

Every example below was executed against a real store. Output is shown as
printed, so you can compare your own run against it.

#### Create an object

When the content already exists as a file, pass it with `--from`:

```
bin/topsailai-data create demo --description "Lifecycle demo object" --tag alpha,beta --from ./demo.md
```

```
created object demo at 2026/1112/1706/demo
```

The printed path is the object's `Path` relative to `object/`. Add classify
directories with `--classify`:

```
bin/topsailai-data create note --classify work/2026 --description "Work notes for 2026" --tag work,important --from ./note.md
```

```
created object note at 2026/1112/1706/work/2026/note
```

Use stdin only when the content is generated in memory and has no file:

```
printf '# Inline\n\ninline content\n' | bin/topsailai-data create inline-note --description "Inline note"
```

A tar archive is also accepted, which lets you create an object with several
files at once:

```
bin/topsailai-data create bundle --description "Bundle archive" --from ./bundle.tar
```

#### Show one object

```
bin/topsailai-data show demo
```

```
ID:            demo
Name:          demo
Path:          2026/1112/1706/demo
Description:   Lifecycle demo object
Status:        active
SchemaVersion: 2
CreatedAt:     2026-11-12T17:06:15+08:00
UpdatedAt:     2026-11-12T17:06:15+08:00
Tags:          alpha, beta
DataRef:       2026/1112/1706/demo

Stat:
  ReadCount:     0
  LastReadAt:    never
  WriteCount:    1
  LastWrittenAt: 2026-11-12T17:06:15+08:00

--- Markdown ---
# Demo

body line

--- folder structure ---
demo/
└── demo.md
no additional files
```

`show` works for every status. For `deleted` and `ceased` objects the two
actual-data sections are replaced by a single line:

```
--- Actual data unavailable for deleted object ---
```

#### List objects

```
bin/topsailai-data list
```

```
- id: demo
  name: demo
  path: 2026/1112/1706/demo
  description: Lifecycle demo object
  status: active
  tags:
    - alpha
    - beta
  created_at: 2026-11-12T17:06:15.819311178+08:00
  updated_at: 2026-11-12T17:06:15.822979908+08:00
  schema_version: 2
  data_ref: 2026/1112/1706/demo
```

Filter by tag with `--tag`. Repeat the flag, or pass a comma-separated list, to
require several tags at once. Multiple tags are combined with AND, so an object
must carry every named tag:

```
bin/topsailai-data list --tag alpha
bin/topsailai-data list --tag alpha --tag beta
bin/topsailai-data list --tag alpha,beta
```

Requiring a tag the object does not carry yields an empty result:

```
bin/topsailai-data list --tag alpha,nomatch
```

```
[]
```

#### Search objects

```
bin/topsailai-data search demo
```

Search matches object names, tags, and classify paths. Use `|` for OR logic,
and quote the query so the shell does not treat `|` as a pipe:

```
bin/topsailai-data search 'alpha|nomatch'
```

No match prints `[]`. A query containing a space is rejected:

```
bin/topsailai-data search 'a b'
```

```
error: search: search query cannot contain spaces or tabs
```

#### Search query syntax

- `search` performs a case-insensitive substring match against object names, tags, and classify paths.
- Use `|` to separate multiple terms. An object matches if any term matches (OR logic). Example: `search 'foo|bar'` matches objects whose name, tags, or classify path contain `foo` or `bar`.
- Spaces, tabs, and backslash escapes are not supported in search queries. To match multi-word tags, search for one word at a time.

#### Sorting results

Both `list` and `search` accept a `--sort` option that orders results by the time prefix (`YYYY/MMDD/HHMM`) extracted from each object's path.

- `time:desc` — newest first (default when `--sort` is omitted).
- `time:asc` — oldest first.

Examples:

```
bin/topsailai-data list --sort time:desc
bin/topsailai-data search work --sort time:asc
```

#### Update the description

```
bin/topsailai-data update demo --description "Rewritten description"
```

```
updated object demo
```

Pass an empty value to clear the description. The field is then printed with
no value:

```
bin/topsailai-data update demo --description ""
```

```
updated object demo
```

#### Add and remove tags

```
bin/topsailai-data tag add demo gamma
```

```
added tag "gamma" to demo
```

```
bin/topsailai-data tag remove demo gamma
```

```
removed tag "gamma" from demo
```

Removing a tag the object does not carry fails instead of silently succeeding:

```
bin/topsailai-data tag remove demo nosuch
```

```
error: tag remove: tag not found: tag "nosuch" not found
```

#### Move an object

```
bin/topsailai-data move demo archive/2026
```

```
moved object demo
```

The ID, name, and tags are unchanged; only `Path` and `DataRef` gain the new
classify directories:

```
ID:            demo
Path:          2026/1112/1706/archive/2026/demo
Tags:          alpha, beta
DataRef:       2026/1112/1706/archive/2026/demo
```

#### Soft delete and recover

`delete` on an active object marks it `deleted` and keeps the payload, so the
operation is reversible:

```
bin/topsailai-data delete demo
```

```
deleted object demo
```

The object disappears from `list` but `show` still resolves it:

```
bin/topsailai-data list
```

```
[]
```

```
bin/topsailai-data show demo
```

```
Status:        deleted
DeletedAt:     2026-11-12T17:04:18+08:00
```

Use `--include-deleted` to see it in a collection query:

```
bin/topsailai-data list --include-deleted
```

`recover` restores it to `active` without needing `--from`, because the
payload was never removed:

```
bin/topsailai-data recover demo
```

```
recovered object demo
```

Recovering an object that is already active fails:

```
bin/topsailai-data recover demo
```

```
error: recover: object already exists: object demo is already active
```

If the payload is gone but you still have an archive, supply it:

```
bin/topsailai-data recover demo --from ./backup.tar
```

#### Finalize and purge

A second `delete` on a `deleted` object removes the payload and moves the
object to `ceased`:

```
bin/topsailai-data delete demo
```

```
deleted object demo
```

```
bin/topsailai-data show demo
```

```
Status:        ceased
DeletedAt:     2026-11-12T17:04:29+08:00
CeasedAt:      2026-11-12T17:04:29+08:00
```

A `ceased` object keeps its metadata and tags but has no payload, so actual
data commands fail:

```
bin/topsailai-data get demo demo.md
```

```
error: get: object not found: demo
```

`ceased` is terminal. Recovery is refused even when an archive is supplied:

```
bin/topsailai-data recover demo --from ./backup.tar
```

```
error: recover: object has ceased: object demo has ceased and cannot be restored
```

#### Garbage collect

Always preview first. `--dry-run` reports the plan without changing anything:

```
bin/topsailai-data gc --dry-run
```

```
dry-run: would run GC for ceased objects
```

When nothing matches, the message says so:

```
bin/topsailai-data gc --dry-run --status deleted
```

```
no deleted objects to gc
```

Default `gc` honors `TOPSAILAI_DATA_CEASED_RETENTION_DAYS`, so a freshly
ceased object survives:

```
bin/topsailai-data gc
```

```
gc completed for ceased objects
```

`--status ceased` ignores the retention window and purges immediately:

```
bin/topsailai-data gc --status ceased
```

```
gc completed for ceased objects
```

After the purge the object is gone entirely:

```
bin/topsailai-data show demo
```

```
error: show: metadata for "demo": object not found
```

`--status deleted` finalizes every deleted object in one pass, which is the
batch equivalent of deleting twice:

```
bin/topsailai-data gc --status deleted
```

```
finalized deleted object demo
```

`--status creating` cleans up objects whose creation was interrupted:

```
bin/topsailai-data gc --status creating
```

```
no creating objects to gc
```

#### Create over a ceased object

A `ceased` object does not block reuse of its name. Creation purges the old
record and starts clean, so no stale `CeasedAt` survives:

```
bin/topsailai-data create demo --description "Second life" --from ./demo.md
```

```
created object demo at 2026/1112/1706/demo
```

```
Status:        active
Description:   Second life
```

An `active`, `creating`, or `deleted` object still blocks creation:

```
bin/topsailai-data create demo --description "dup" --from ./demo.md
```

```
error: create: object already exists: demo
```

#### Read and write actual data

Read one file to stdout:

```
bin/topsailai-data get demo demo.md
```

Write one file into the object. The destination name is relative to the object
folder, and missing parent folders are created:

```
bin/topsailai-data put demo notes/a.md --from ./demo.md
```

Export the whole payload as a tar archive:

```
bin/topsailai-data get-archive demo > ./backup.tar
```

```
tar -tvf ./backup.tar
```

```
-rw-r--r-- root/root        62 2026-11-12 17:04 demo.md
drwxr-xr-x root/root         0 2026-11-12 17:04 notes
-rw-r--r-- root/root        62 2026-11-12 17:04 notes/a.md
```

Replace the payload from an archive:

```
bin/topsailai-data put-archive demo ./backup.tar
```

```
wrote archive to object demo
```

#### Writes require an active object

Every actual-data write is rejected unless the object is `active`. The error
names the reason, so a script can tell a lifecycle problem from a missing
object:

```
bin/topsailai-data put demo x.md --from ./demo.md
```

```
error: put: object "demo" is not active: object is not active
```

```
bin/topsailai-data tag add demo zeta
```

```
error: tag add: object "demo" is not active: object is not active
```

```
bin/topsailai-data move demo other
```

```
error: move: object is not active: object demo is deleted
```

#### Binary files with `get`

`get` writes the file's raw bytes to stdout without any text conversion, line-ending changes, or truncation. This makes it suitable for binary payloads such as images, videos, compiled executables, compressed archives, or PDFs.

To save the binary data to a file, redirect stdout directly to a file:

```
bin/topsailai-data put myobj photo.png --from ./photo.png
bin/topsailai-data get myobj photo.png > photo-copy.png
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
  description: A hello object
  status: active
  tags:
    - quickstart
  created_at: 2026-07-14T23:23:00Z
  updated_at: 2026-07-14T23:23:00Z
  schema_version: 2
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
    "description": "A hello object",
    "status": "active",
    "tags": ["quickstart"],
    "created_at": "2026-07-14T23:23:00Z",
    "updated_at": "2026-07-14T23:23:00Z",
    "schema_version": 2,
    "data_ref": "2026/0714/2323/hello"
  }
]
```

`show` prints four sections for an object: metadata, usage statistics, the
content of `<object>.md`, and the folder structure.

### show output format

#### Metadata section

The first section lists the object's stored metadata. All timestamps are formatted as RFC3339 strings.

| Field | Description |
|-------|-------------|
| `ID` | Stable object identifier. In the local adapter this equals the object name. |
| `Name` | Object name (the folder name). |
| `Path` | Full relative path from the root to the object folder. |
| `Description` | Optional object description. |
| `Status` | Lifecycle status: `creating`, `active`, `deleted`, or `ceased`. |
| `SchemaVersion` | Persistent storage format version of the object record. |
| `CreatedAt` | Object creation timestamp. |
| `UpdatedAt` | Last modification timestamp. |
| `DeletedAt` | Present only when the object has been soft-deleted. |
| `CeasedAt` | Present only when the object has been finalized after deletion. |
| `Tags` | The object's complete tag set, loaded from the independent Hash metadata `tags` file. Empty when there are no tags. |
| `DataRef` | Opaque reference to the actual data, managed by the actual-data adapter. |

#### Stat section

The second section is labeled `Stat:` and prints the object's usage counters.
`LastReadAt` prints `never` when the object has never been read. Statistics are
frozen while an object is `deleted` or `ceased`.

#### Markdown content section

The third section is labeled `--- Markdown ---` and prints the contents of the object's mandatory `<object>.md` file. If the file is empty, the section prints `(empty)`.

#### Folder structure section

The fourth section is labeled `--- folder structure ---` and prints the payload tree, including `<object>.md` and user files named `metadata.json`, `stat.json`, `.stat.json`, or ending in `.lock`/`.tags`. Internal `.topsailai-data-write-*` temporary files are excluded. Hash metadata lives outside the payload tree.

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
Description:   A hello object
Status:        active
SchemaVersion: 2
CreatedAt:     2026-07-14T23:23:00+08:00
UpdatedAt:     2026-07-14T23:23:00+08:00
Tags:          quickstart
DataRef:       2026/0714/2323/hello

Stat:
  ReadCount:     0
  LastReadAt:    never
  WriteCount:    1
  LastWrittenAt: 2026-07-14T23:23:00+08:00

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
{ROOT}/object/YYYY/MMDD/HHMM/<object>
```

Example for an object created on 2026-07-14 at 23:23:

```text
./data/object/2026/0714/2323/hello
```

### Object folder contents

An object named `hello` is stored as a folder `hello` that must contain a file named `hello.md`. The folder may also contain other files and subdirectories as actual data.

```text
hello/
  hello.md          # mandatory actual-data marker
  attachments/      # optional actual data
    screenshot.png
```

The store has sibling `object/` and `meta/` trees. For exact object ID `id`, let `h` be its lowercase SHA256. Internal files live at `meta/<h[0:2]>/<h[2:4]>/<h[4:6]>/<h>/`: `metadata.json`, `tags`, `lock`, `stat.json`, and `stat.lock` as needed. `Path` and `DataRef` are equal canonical paths relative to `object/`. Old stores are not migrated by this layout cutover. The payload folder holds user data only.

### Classify directories

After the time prefix you may add custom classify directories. The total depth from `object/` to the object folder must not exceed 11 levels. The time prefix consumes 3 levels and the object folder consumes 1 level, leaving up to 7 extra classify levels.

Example with classify path `projects/demo`:

```text
./data/object/2026/0714/2323/projects/demo/hello
```

Too deep:

```text
2026/0714/2323/a/b/c/d/e/f/g/h/hello  # 12 levels, exceeds limit
```

### Tags

Tags are stored only in the independent `tags` file in the Hash metadata leaf, not in `metadata.json`. There is no classify tag inheritance or `meta/classify/` tree.

- `create --tag t1,t2`, `tag add`, and `tag remove` manage the independent tag file.
- `list`, `search`, and `show` expose these tags through the public object model.
- Tags survive soft deletion and finalization until metadata purge.

Tags must be non-empty and pass CLI validation; path separators, NUL, and leading or trailing spaces are rejected. Duplicates are removed and the first occurrence wins. Tag-file and record updates are not a cross-file transaction. A payload file named `<name>.tags` is ordinary user data.

### Metadata queries and payload boundaries

Get locates the object by its ID hash; list/search enumerate Hash metadata records rather than discovering objects through payload scans. Nested Markdown files do not create objects. Payload scanning and namespace validation still stop at a same-name Markdown boundary, protecting object-private subdirectories. Always create through the CLI. Collection queries remain unindexed; large collections require a full metadata traversal.

## Object Stat Observability (`stat`)

Each object maintains usage statistics in `stat.json` inside its Hash metadata
directory, serialized by `stat.lock`. The record contains `schema_version`, `read_count`, `last_read_at`,
`write_count`, and `last_written_at`. The statistics help identify frequently
used objects and objects that have not been used recently.

### Counting rules

- Read operations (`show`, `get`, and `get-archive`) increment `read_count` and
  update `last_read_at`.
- Write operations (`create`, `put`, `put-archive`, `update`, `tag`, and `move`)
  increment `write_count` and update `last_written_at`.
- `list` and `search` do not change usage statistics.
- Only `active` objects accumulate statistics. Statistics are frozen while an
  object is `deleted` or `ceased`; after `recover`, accumulation resumes.

### Stat commands

Always invoke the topsailai-data binary with its full relative path for stat
commands so it is not confused with the Unix `stat` utility.

Display statistics for one object in YAML (default) or JSON:

```
bin/topsailai-data stat <id>
bin/topsailai-data stat <id> --format yaml
bin/topsailai-data stat <id> --format json
```

Rank objects by read, write, or recency of read usage:

```
bin/topsailai-data stat top --by read --order desc --limit 10
bin/topsailai-data stat top --by write --order asc --limit 10 --status active --format json
bin/topsailai-data stat top --by last_read --order desc --limit 5
```

`stat top` supports `--by read|write|last_read`, `--order desc|asc`, `--limit n`,
`--status active|deleted|ceased|all`, and `--format yaml|json`. `--by last_read`
ranks by the most recent read time, and `--status all` includes every lifecycle
state instead of only `active`.

Attach each object's statistics to normal list or search results without
incrementing its counters:

```
bin/topsailai-data list --with-stat
bin/topsailai-data search <query> --with-stat
```

### Tracking configuration

Stat tracking is enabled by default. Set `TOPSAILAI_DATA_TRACK_STAT` to `0` or
`false` to disable read and write statistic updates; use `1` or `true` to
enable them explicitly.

### Fault tolerance and persistence

- A missing `stat.json` is treated as a zero-value statistic record.
- A corrupt `stat.json` produces a WARN log and is treated as a zero-value
  record instead of crashing the CLI.
- Statistic records are written atomically through a temporary file followed
  by rename.

### Lifecycle integration

- Soft delete freezes the current statistics. After recovery, the preserved
  counters continue accumulating.
- Finalization removes the entire payload directory but retains the Hash metadata leaf, tags, and lock files until purge. Statistics are best effort, not a durable event ledger.
- Purge removes the metadata leaf and its remaining internal files.
- User `.stat.json` or `stat.json` files in the payload are ordinary data and remain visible in `show`.

### Object locking

Writes and lifecycle operations use Hash `lock` custody and re-read status after locking. Creation, move, and metadata-leaf removal also use namespace custody, acquired before the object lock. Optional read locks remain held until the read stream closes. Statistics serialize the full read-modify-write and revalidate active status under object custody. These are cooperating-process guarantees, not protection against hostile concurrent path replacement or power loss.

Every `file` write holds the object's meta lock across the whole
read-modify-write, so `overwrite-lines`, `insert`, `write` with a non-zero
`--seek`, and `append` cannot interleave with another writer. The lock is
non-blocking: a competing writer fails with `object is locked by another
process` and exits non-zero instead of silently discarding an update. Retry
after the other writer finishes.

`file` reads and writes stream instead of buffering the whole object file.
Bounded reads, append, `write --from`, positional writes, and small line edits
therefore use memory independent of the complete file size. `overwrite-lines`
and `insert` retain only the changed window plus three context lines for their
unified diff; a diff containing a very large changed range still naturally
uses memory and output proportional to that changed range. Folder checks,
`list-dirs`, and `mkdirs` use direct adapter metadata discovery and do not read
the object's payload archive.

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
| `TOPSAILAI_DATA_FILE_MAX_BYTES` | no | `30000` | Byte limit for reading a file whose extension is not whitelisted. |
| `TOPSAILAI_DATA_FILE_WHITE_LIST_NO_TRUNCATE_EXT` | no | built-in list | Comma-separated extension override. `*` disables truncation; `!*` forces it. |

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
- **Deleted/ceased objects** are hidden from normal `list` and `search` unless `--include-deleted` is used. The `show` command, however, always resolves an object by ID and displays its metadata regardless of status. For `deleted` and `ceased` objects the actual-data sections (`--- Markdown ---` and `--- folder structure ---`) are omitted and replaced with a note that actual data is unavailable. Actual-data reads require `active` status, so `get` and `get-archive` fail for both statuses even when a `deleted` object's payload is still intact; run `recover` first.
- **`recover`** only restores objects whose status is `deleted` back to `active`. It does not operate on `creating`, `active`, or `ceased` objects.
- **Avoid manual changes**: do not create or rename object folders manually. Use the CLI so that metadata and the `.md` marker stay consistent.

## See also

- `bin/topsailai-data` — the CLI binary used by this skill
- `config/example.env`

## Lesson learned: use the CLI as the only abstraction layer

When managing topsailai-data objects (notes or any other type), ALWAYS use
the topsailai-data CLI as the primary abstraction layer. Use commands such as
`list`, `show`, `get`, `put`, `tag`, `move`, `delete`, `recover`, and `gc` to
locate, read, and modify objects. Do NOT use shell commands such as `find`,
`ls`, or direct filesystem access to probe the storage backend, adapter
directories, or object paths. If the CLI location or data root is unclear,
read this skill documentation first rather than exploring the filesystem.


## Write-source safety

- `put` rejects a source that is the same file as the destination, including symlink and hard-link aliases. Single-file writes use a same-directory temporary file followed by an atomic rename, so failed writes preserve the previous destination.
- `put-archive` and `recover --from` reject file-backed archive sources located inside or aliased into the target object directory before cleanup or extraction. The object data and lifecycle status remain unchanged after rejection.
- `.topsailai-data-write-*` is reserved for internal temporary files. These files are excluded from archive output, `show` folder trees, `exists` checks, and move copies.
- Expired reserved temporary files are cleaned recursively at object cleanup/GC boundaries after 24 hours. Fresh temporary files, unrelated files, and directory symlinks are preserved.

## File and folder command group

The `file` command group exposes the file and folder capabilities of the
TopsailAI file tool, scoped to the actual data of one data object. Every
subcommand requires `--object <id>`, and every path is relative to that
object's folder.

This is the right tool when a task needs to read or edit a file inside an
object without a `get`-edit-`put` round trip. There is no operating-system
mode: a file command without `--object` is rejected.

| Subcommand | Usage | Description |
|------------|-------|-------------|
| `read` | `file read <file_path> --object <id> [--seek n] [--size n]` | Read a file, optionally a byte window. A negative `--seek` counts from the end; `--size -1` reads to the end. |
| `read-lines` | `file read-lines <file_path> --object <id> [--start n] [--end n]` | Read a line range as `{n}-{content}`. `--end 0` reads only `--start`; `--end -1` reads to the end. |
| `read-around` | `file read-around <file_path> <line_number> --object <id> [--context n]` | Read a line with surrounding context. The target is marked `:` and context lines `-`. |
| `read-context` | `file read-context <file_path> <pattern> --object <id> [--context n] [--case-sensitive]` | Read lines matching a regular expression with context. Matching is case-insensitive by default. |
| `read-files` | `file read-files <file_path...> --object <id> [--format yaml\|json]` | Read several files into one path-to-content map. |
| `write` | `file write <file_path> --object <id> [--content <text>\|--from <path\|->] [--seek n] [--insert]` | Write content. `--insert` inserts at the offset instead of overwriting. Redirected standard input is read when neither `--content` nor `--from` is given. |
| `append` | `file append <file_path> --object <id> [--content <text>\|--from <path\|->]` | Append content to a file. Redirected standard input is read when neither `--content` nor `--from` is given. |
| `exists` | `file exists <name=path...> --object <id> [--format yaml\|json]` | Check several paths for existence. |
| `mkdirs` | `file mkdirs <dir...> --object <id>` | Create folders, each seeded with an `AGENTS.md` marker so the folder is discoverable. An existing folder is left untouched. |
| `list-dirs` | `file list-dirs <dir...> --object <id> [--format yaml\|json]` | List several folders with sorted entries. |
| `size` | `file size <file_path> --object <id>` | Report a file size in bytes. |
| `overwrite-lines` | `file overwrite-lines <file_path> <start_num> --object <id> [--end n] [--content <text>\|--from <path\|->]` | Replace a line range and print a unified diff. Redirected standard input is read when neither `--content` nor `--from` is given. |
| `insert` | `file insert <file_path> <line_num> --object <id> [--content <text>\|--from <path\|->] [--before]` | Insert content before or after a line and print a unified diff. Redirected standard input is read when neither `--content` nor `--from` is given. |

### Examples

Most examples below use one object id, `project--qrew--skill-hub`; the folder
examples use a second object, `demo`, so their output stays short. Every example
was run against a real store, and the output is copied from the actual command
output.

#### Read a whole file

```
bin/topsailai-data file read notes/design.md --object project--qrew--skill-hub
```

```text
# Design

line three
line four
line five
line six
line seven
line eight
```

#### Read a byte window

`--seek` and `--size` are byte offsets. A negative `--seek` counts from the end
of the file, and `--size -1` reads to the end.

```
bin/topsailai-data file read logs/big.log --object project--qrew--skill-hub --seek 0 --size 10
bin/topsailai-data file read logs/big.log --object project--qrew--skill-hub --seek -5
```

```text
xxxxxxxxxx
xxxxx
```

#### Read a line range

Rows are printed as `{line_number}-{content}`. `--end 0` reads only `--start`,
and `--end -1` reads through the end of the file.

```
bin/topsailai-data file read-lines notes/design.md --object project--qrew--skill-hub --start 3 --end 5
```

```text
3-line three
4-line four
5-line five
```

#### Read around one line

The target line is marked `:` and context lines `-`.

```
bin/topsailai-data file read-around notes/design.md 5 --object project--qrew--skill-hub --context 1
```

```text
4-line four
5:line five
6-line six
```

#### Search a file with a pattern

`read-context` takes a regular expression and is case-insensitive unless
`--case-sensitive` is passed.

```
bin/topsailai-data file read-context notes/design.md "line (four|six)" --object project--qrew--skill-hub --context 1
```

```text
3-line three
4:line four
5-line five
6:line six
7-line seven
```

#### Read several files at once

`read-files` returns one path-to-content map. A file that cannot be read is
recorded as an `Error: ...` value instead of failing the whole command.

```
bin/topsailai-data file read-files notes/design.md notes/2026/AGENTS.md --object project--qrew--skill-hub --format json
```

```json
{
  "notes/2026/AGENTS.md": "# AGENTS\n\nThis folder was created by the topsailai-data file mkdirs command.\n\nRecord instructions for agents working in this folder here.\n",
  "notes/design.md": "# Design\n\nline three\nline four\nline five\nline six\nline seven\nline eight\n"
}
```

#### Write a whole file

`--from` reads a local file, `--content` takes inline text, and redirected
standard input is used when neither is given. A whole-file write prints `OK`.

```
bin/topsailai-data file write notes/new.md --object project--qrew--skill-hub --content "# Title"
bin/topsailai-data file write notes/design.md --object project--qrew--skill-hub --from ./draft.md
```

```text
OK
OK
```

#### Write at a byte offset

`--seek` overwrites from that offset. Adding `--insert` inserts instead of
overwriting. A seek past the end of the file appends.

```
bin/topsailai-data file write notes/pos.txt --object project--qrew--skill-hub --seek 3 --content "ABC"
bin/topsailai-data file write notes/pos.txt --object project--qrew--skill-hub --seek 3 --insert --content "XY"
```

Starting from `0123456789`, the first command produces `012ABC6789` and the
second produces `012XYABC6789`.

#### Append

`append` creates the file when it does not exist yet.

```
bin/topsailai-data file append notes/log.md --object project--qrew--skill-hub --content "one more line"
bin/topsailai-data file append notes/new-log.md --object project--qrew--skill-hub --content "first line"
```

```text
OK
OK
```

#### Replace a line range

`overwrite-lines` prints the line-number warning and a unified diff. The file is
already changed when the diff is printed.

```
bin/topsailai-data file overwrite-lines notes/design.md 4 --object project--qrew--skill-hub --end 5 --content "line four replaced"
```

```text
> You CANNOT call continuously due to the line number will change after each call.
> Invoke the tool that provides line numbers to check content Now!
--- before
+++ notes/design.md
@@ -1,8 +1,7 @@
 # Design
 
 line three
-line four
-line five
+line four replaced
 line six
 line seven
 line eight
```

Passing an empty `--content ""` deletes the addressed range:

```
bin/topsailai-data file overwrite-lines notes/small.md 2 --object project--qrew--skill-hub --content ""
```

Starting from `alpha`, `beta`, `gamma`, the result is `alpha`, `gamma`.

#### Insert a line

`insert` adds content after the reference line by default, and `--before`
inserts before it.

```
bin/topsailai-data file insert notes/design.md 2 --object project--qrew--skill-hub --content "inserted after two"
bin/topsailai-data file insert notes/small.md 1 --object project--qrew--skill-hub --before --content "header"
```

```text
--- before
+++ notes/design.md
@@ -1,5 +1,6 @@
 # Design
 
+inserted after two
 line three
 line four replaced
 line six
```

#### Check existence

`exists` requires `name=path` pairs and accepts files and folders alike.

```
bin/topsailai-data file exists design=notes/design.md missing=notes/nope.md dir=notes/2026 --object project--qrew--skill-hub
```

```text
design: true
dir: true
missing: false
```

#### Create folders

```
bin/topsailai-data file mkdirs notes/2026 --object project--qrew--skill-hub
```

```text
OK
```

#### List folders

```
bin/topsailai-data file list-dirs . notes notes/2026 --object project--qrew--skill-hub
```

```text
.:
    - notes
    - project--qrew--skill-hub.md
notes:
    - "2026"
    - AGENTS.md
    - design.md
notes/2026:
    - AGENTS.md
```

#### Report a file size

```
bin/topsailai-data file size notes/design.md --object project--qrew--skill-hub
```

```text
72
```

#### Edit a file in place instead of get-edit-put

The `file` group exists so a small edit does not need a full round trip. Read
the region, edit it, and confirm the result:

```
bin/topsailai-data file read-lines notes/design.md --object project--qrew--skill-hub --start 1 --end 5
bin/topsailai-data file overwrite-lines notes/design.md 4 --object project--qrew--skill-hub --content "line four replaced"
bin/topsailai-data file read-lines notes/design.md --object project--qrew--skill-hub --start 1 --end 5
```

Re-read after every `overwrite-lines` or `insert` call, because the line numbers
of the following lines change.

#### Compare with get and put

Use `file` for reading and editing inside an object, and `get`/`put` when the
whole file must leave or enter the store as a stream:

```
bin/topsailai-data get project--qrew--skill-hub notes/design.md > ./design.md
bin/topsailai-data put project--qrew--skill-hub notes/design.md --from ./design.md
```

`get` preserves raw bytes, so it is the right choice for binary files. `file
read` decodes text and truncates non-whitelisted extensions, so it is the wrong
choice for images or archives.

### Object scoping

`--object <id>` names the data object whose actual data the command operates
on. The object folder is the root of every path:

- A path is relative to the object folder. `notes/a.md` addresses the file
  `notes/a.md` inside that object, never a file on the host.
- A leading slash is ignored, so `/notes/a.md` and `notes/a.md` are the same
  file.
- An empty path addresses the object root. `list-dirs ""` and `list-dirs .`
  both list the top level of the object folder. The output key echoes the
  argument as given, so `list-dirs .` prints `.:` while `list-dirs ""` prints
  `"":`; the listed entries are identical.
- A path that climbs above the object root is clamped to the root, not
  rejected. `../outside.md` and `../../outside.md` both address
  `outside.md` inside the object, so a file command can never reach a file
  outside the object. The clamp is silent: the command succeeds and writes
  inside the object.
- An unknown object id fails with `object not found` before any file is
  touched.

Because every operation is routed through the manager, the object store
guarantees apply unchanged:

- Write operations acquire the advisory object lock.
- Single-file writes replace the destination atomically, so a failed write
  leaves the previous content intact.
- Read and write operations update the object's usage statistics.
- Internal Hash metadata is outside the payload root and cannot be reached through file commands. Payload files named `<object>.lock`, `<object>.deleted`, `<object>.ceased`, `.stat.json`, or `metadata.json` are ordinary user data. The mandatory `<object>.md` remains readable and writable; `.topsailai-data-write-*` remains reserved.

### Common errors

Every failure exits non-zero and prints one `error: ...` line to stderr, so a
script can rely on the exit code.

| Situation | Message |
|-----------|---------|
| `--object` omitted | `error: file read: --object <id> is required` |
| Unknown object id | `error: file read: metadata for "nope": object not found` |
| Missing file | `error: file read: object not found: file "notes/nope.md"` |
| `exists` without `name=path` | `error: file exists: expected name=path, got "notes/tail.md"` |
| Invalid `--format` | `error: invalid --format "xml": must be yaml or json` |
| Invalid regex in `read-context` | `error: file read-context: invalid parameter: invalid pattern=[: invalid regular expression: ...` |
| `read` on a folder | `error: file read: read <absolute-path>: is a directory` |
| Competing writer holds the lock | `error: ... object is locked by another process` |

A missing folder is not an error for `list-dirs`: the folder is reported with a
single `Error: ...` entry and the command still exits `0`.

```
bin/topsailai-data file list-dirs nope --object demo
```

```text
nope:
    - 'Error: objectfs: folder "nope" does not exist in object "demo"'
```

### Writing content from standard input

The four content-writing subcommands (`write`, `append`, `overwrite-lines`,
`insert`) read redirected standard input when neither `--content` nor `--from`
is given. Piping content is therefore enough; no extra flag is required.

```
printf 'piped content\n' | bin/topsailai-data file write notes/from-stdin.md --object project--qrew--skill-hub
printf 'one more line\n' | bin/topsailai-data file append notes/log.md --object project--qrew--skill-hub
printf 'TWO\n' | bin/topsailai-data file overwrite-lines notes/design.md 2 --object project--qrew--skill-hub
printf 'inserted\n' | bin/topsailai-data file insert notes/design.md 5 --object project--qrew--skill-hub
```

The explicit `--from -` form keeps working and is equivalent:

```
printf 'dash content\n' | bin/topsailai-data file write notes/from-dash.md --object project--qrew--skill-hub --from -
```

Content sources are resolved in this order:

1. `--from <path>`, which reads a file.
2. `--from -`, which reads standard input.
3. An explicit `--content` value, including an explicitly empty value.
4. Redirected standard input when neither flag is given.
5. Empty content when standard input is an interactive terminal.

`--from` wins over `--content`, so a caller can pass a file without quoting its
text.

When `--from` is absent, an explicitly empty `--content ""` wins over piped
input, because an empty value is a real request: `overwrite-lines` with empty
content deletes the addressed line range. When standard input is an interactive
terminal and no content source is given, the content stays empty instead of
waiting, so an interactive invocation never hangs.

### Behaviour notes

- Content whose extension is not whitelisted is truncated at
  `TOPSAILAI_DATA_FILE_MAX_BYTES` (default `30000`) and the suffix
  ` ... (force to truncate)` is appended. Whitelisted extensions are returned
  in full.
- `TOPSAILAI_DATA_FILE_WHITE_LIST_NO_TRUNCATE_EXT` overrides the whitelist.
  Use `*` to disable truncation for every extension and `!*` to force it.
- `--seek` and `--size` count bytes, not characters. This differs from the
  Python file tool, which counts characters.
- `overwrite-lines` and `insert` print a unified diff. `overwrite-lines` also
  prints the warning that line numbers change after each call, so re-read the
  file before the next edit.
- `read-files`, `list-dirs`, and `exists` record a per-item failure instead of
  hiding the other items. A failed item appears as an `Error: ...` value and the
  command still exits `0`, so inspect the values rather than the exit code.
- `read-lines`, `read-around`, and `read-context` print their rows joined by a
  newline with no trailing newline, so chained output runs into the next line.
  Add `echo` when chaining commands in a terminal.
- `read` on a folder fails with `is a directory`, while `size` on a folder
  reports `0`. Use `list-dirs` to inspect a folder.
- `write --seek` past the end of a file appends instead of failing, and
  `read --seek` past the end returns empty output with exit `0`.
- `exists` requires `name=path` pairs. A bare path is rejected with
  `expected name=path`.
- `file` with no subcommand prints the subcommand list and exits `0`. `-h` or
  `--help` after a subcommand prints the generic `file` usage line, not that
  subcommand's own flags, so read the table above for exact arguments.

### Discovery inside an object

`list-dirs` lists the immediate entries of each named folder inside the object
and does not recurse, so each deeper level must be named explicitly:

```
bin/topsailai-data file list-dirs . --object project--qrew--skill-hub
bin/topsailai-data file list-dirs notes --object project--qrew--skill-hub
bin/topsailai-data file list-dirs notes/archive --object project--qrew--skill-hub
```

Real output for the first two commands:

```text
.:
    - notes
    - project--qrew--skill-hub.md
notes:
    - "2026"
    - AGENTS.md
    - design.md
```

`exists` reports a boolean per named path and accepts files and folders alike.
`size` reports a byte count, and `read` returns content.

There is no recursive walk and no search-by-name command in the `file` group.
Recursive discovery with object-boundary detection belongs to `list` and
`search` in the object store, which scan the whole store rather than one
object.

### Folders and the AGENTS.md marker

Object storage has no meaningful empty folder: a folder becomes discoverable
only once it holds a file. Both `mkdirs` and the ordinary write commands
therefore seed a marker file.

`mkdirs` creates every missing level of the requested path and writes an
`AGENTS.md` marker into each level it creates:

```
bin/topsailai-data file mkdirs notes/2026 --object demo
bin/topsailai-data file list-dirs "" --object demo
bin/topsailai-data file read notes/2026/AGENTS.md --object demo
```

- A level that already exists is skipped, so an existing `AGENTS.md` is never
  overwritten and a populated folder receives no marker.
- The object root is never modified: `mkdirs .` and `mkdirs ""` succeed without
  writing a marker.
- The marker is written through the manager, so the object lock, the atomic
  replacement, and the write statistics apply exactly as for any other write.
- The absolute-path requirement of the original tool does not apply in object
  mode, because every path is already relative to the object folder.

`write`, `append`, `overwrite-lines`, and `insert` also create missing parent
folders, and those parents receive the same `AGENTS.md` marker. A write into a
new folder therefore succeeds without a separate `mkdirs` call, but the marker
appears as an extra file:

```
bin/topsailai-data file write deep/x/y.md --object demo --content "hi"
bin/topsailai-data file list-dirs deep --object demo
bin/topsailai-data file list-dirs deep/x --object demo
```

```text
deep:
    - AGENTS.md
    - x
deep/x:
    - AGENTS.md
    - y.md
```

Use `mkdirs` when the folder itself is the deliverable, and a plain write when
only the file matters. Do not be surprised by the marker: it is created by the
tool, not by the caller, and it is ordinary actual data afterwards.
