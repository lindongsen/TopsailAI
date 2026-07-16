# topsailai_data CLI Cheatsheet

Author: DawsonLin

## Quick start

```
export TOPSAILAI_DATA_ROOT=./data
make build
bin/topsailai_data create hello --tag quickstart
bin/topsailai_data list
bin/topsailai_data show hello
```

## Commands

### Create

```
bin/topsailai_data create <object> [--classify dir1/dir2] [--tag t1,t2] [--from file|archive|-]
```

Examples:

```
bin/topsailai_data create note --classify work/2026 --tag work,important
bin/topsailai_data create report --from report.md
bin/topsailai_data create bundle --from bundle.tar
echo "inline content" | bin/topsailai_data create inline-note
```

### Read metadata

```
bin/topsailai_data show <id>
bin/topsailai_data list [--tag tag] [--include-deleted]
bin/topsailai_data search <query> [--include-deleted]
```

### Modify tags

```
bin/topsailai_data tag add <id> <tag>
bin/topsailai_data tag remove <id> <tag>
```

### Move

```
bin/topsailai_data move <id> <new-classify...>
```

Example:

```
bin/topsailai_data move hello archive/2026
```

### Delete and cleanup

```
bin/topsailai_data delete <id>
bin/topsailai_data gc [--dry-run] [--status creating|ceased]
bin/topsailai_data recover <id> [--resume] [--from archive]
```

### Actual data I/O

```
bin/topsailai_data get <id> <file>
bin/topsailai_data get-archive <id> > backup.tar
bin/topsailai_data put <id> <file> [--from file]
bin/topsailai_data put-archive <id> <archive>
```

## Environment variables

```
TOPSAILAI_DATA_ROOT=./data
TOPSAILAI_DATA_METADATA_ADAPTER=local
TOPSAILAI_DATA_ACTUAL_DATA_ADAPTER=local
TOPSAILAI_DATA_INCLUDE_DELETED=false
TOPSAILAI_DATA_CEASED_RETENTION_DAYS=30
```
