---
name: topsailai_data
author: DawsonLin
description: Skill for operating the topsailai_data CLI, a local-first object store that separates metadata from actual data through pluggable adapters.
---

# topsailai_data

## When to use

Use this skill when you need to create, organize, search, move, or delete data objects managed by the `topsailai_data` CLI. The tool stores **metadata** (name, path, tags, status) and **actual data** (files, archives) through independent adapters. The current implementation focuses on the **local adapter**, which keeps everything on the local filesystem under a configurable root directory.

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

## Skill layout

```text
skills/topsailai_data/
  bin/topsailai_data      # the CLI binary consumed by this skill
  references/             # cheatsheets and best practices
  config/example.env      # example environment variables
```

The `bin/` directory holds the executable. Helper shell scripts are intentionally not provided; all operations go through `bin/topsailai_data`.

## Commands

| Command | Usage | Description |
|---------|-------|-------------|
| `create` | `create <object> [--classify dir1/dir2/...] [--tag t1,t2] [--from file\|archive]` | Create a new object. Writes a mandatory `<object>.md` marker and optional tags. `--from` accepts a plain file or a tar archive. |
| `show` | `show <id>` | Display metadata of an object. |
| `list` | `list [--tag tag] [--include-deleted]` | List active objects, optionally filtered by tag. |
| `search` | `search <query> [--include-deleted]` | Search objects by name or tag. |
| `tag` | `tag add <id> <tag>` or `tag remove <id> <tag>` | Add or remove an object-specific tag. |
| `move` | `move <id> <new-classify...>` | Move an active object to a different classify path. The ID and name stay the same. |
| `delete` | `delete <id>` | Soft-delete an active object. Actual data is removed and metadata transitions to `ceased`. |
| `recover` | `recover <id> [--resume] [--from archive]` | Resume or clean up a `creating` object. |
| `gc` | `gc [--dry-run] [--status creating\|ceased]` | Clean up `creating` or expired `ceased` objects. `--status deleted` is not supported and returns an error. |
| `get` | `get <id> <file>` | Read a single actual-data file to stdout. |
| `get-archive` | `get-archive <id>` | Output the object's actual data as a tar archive to stdout. |
| `put` | `put <id> <file> [--from file]` | Write a single file into the object's actual data. Defaults to stdin. |
| `put-archive` | `put-archive <id> <archive>` | Replace object actual data from a tar archive. |

## Data layout conventions

### Time-based path

Objects are placed under a time prefix derived from the creation time:

```text
{ROOT}/YYYY/MMDD/HHMM/<object>
```

Example:

```text
./data/2026/0714/2323/hello
```

### Object folder

An object named `hello` is stored as a folder `hello` that must contain a file named `hello.md`. The folder may also contain other files and subdirectories as actual data.

```text
hello/
  hello.md          # mandatory actual-data marker
  hello.tags        # optional object-specific tags
  attachments/      # optional actual data
    screenshot.png
```

### Classify directories

After the time prefix you may add custom classify directories. The total depth from root to the object folder must not exceed 11 levels. The time prefix consumes 3 levels, leaving up to 7 extra classify levels.

Example with classify path `projects/demo`:

```text
./data/2026/0714/2323/projects/demo/hello
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

### Scanning rule

When scanning for objects, the adapter stops at any directory that contains a file named `{directory-name}.md`. Subdirectories inside that folder are not scanned as independent objects.

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

## Notes and common pitfalls

- **Object ID equals object name** in the local adapter. Two objects with the same name cannot exist at different paths.
- **Always create through the CLI** rather than manually creating folders, so metadata and the mandatory `.md` marker are written consistently.
- **Tar archives** are extracted into the object folder. Symbolic links inside tar archives are rejected to prevent directory traversal.
- **`gc --status deleted`** is intentionally unsupported in the current release and returns a clear error.
- **Deleted/ceased objects** are hidden from normal `list`, `show`, and `search` unless `--include-deleted` is used.

## See also

- `bin/topsailai_data` — the CLI binary used by this skill
- `references/cli-cheatsheet.md`
- `references/data-layout.md`
- `config/example.env`
