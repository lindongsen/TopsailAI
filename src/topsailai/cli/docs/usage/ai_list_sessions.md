---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# ai_list_sessions

List stored sessions with optional exact category filtering.

## Options

| Option | Description |
|---|---|
| `--category <value>` | Exact category filter. Omit the option to include every category; pass an empty value to select uncategorized sessions. Accepts exactly one value made of lowercase letters, digits, and underscores. A repeated option or any other character is rejected with exit code `2`. |
| `--included-categories <names>` | Include only sessions whose category is listed. Accepts comma-separated names and may be repeated. Pass an empty value to include uncategorized sessions. An invalid name is rejected with `Error: Invalid included category: '<name>'` and exit code `1`. |
| `--excluded-categories <names>` | Exclude sessions whose category is listed. Accepts comma-separated names and may be repeated. Pass an empty value to exclude uncategorized sessions. An invalid name is rejected with `Error: Invalid excluded category: '<name>'` and exit code `1`. |
| `--has-project` | Keep only sessions whose `project_workspace` is non-empty. |
| `--since <iso>` | Inclusive lower bound on `create_time`, for example `2026-07-28T00:00:00`. |
| `--until <iso>` | Inclusive upper bound on `create_time`, for example `2026-07-28T23:59:59`. |
| `--json` | Emit the existing JSON array shape with an additive `category` field. |
| `--offset` / `--limit` | Apply pagination after every database predicate, so a page always contains the requested number of surviving rows. |

Text output keeps `Total` as the displayed page size and adds `Matched Total` for filtered queries. `Matched Total` is the pre-pagination count of matching rows, including the category, project, and creation-time filters when those options are used.

Every selection predicate runs in the database, so a filter never reads rows it discards. The default ordering is by creation time, which is indexed, so a page query does not scan the whole session table.

`--category` and `--included-categories` intersect, and `--excluded-categories` is subtracted from the result, so the three options compose instead of overriding each other. `--has-project`, `--since`, and `--until` narrow the result further and combine with every category option.

`--category` accepts exactly one value. It must be empty, which selects uncategorized sessions, or match lowercase letters, digits, and underscores. A repeated option and any other character are rejected before the query runs, so an invalid value can never silently select uncategorized rows. `--included-categories` and `--excluded-categories` accept several names and also reject an invalid name, but they exit with code `1` while `--category` exits with code `2`, because `--category` is validated by the argument parser. No enum allowlist is used. The CLI does not use `TOPSAILAI_SESSION_CATEGORY` as a query default.

## Empty values through the `bin/` wrapper

An empty value works both directly and through the wrapper. The `../bin/`
wrappers quote every argument the same way `../bin/topsailai.cli` does, so an
empty string survives the hand-off:

```bash
./ai_list_sessions.py --category ""
topsailai_list_sessions --category ""
```

Both list uncategorized sessions and exit `0`. Before the wrappers quoted their
arguments, the unquoted `$*` word-split the argument list, dropped the empty
string, and the child reported `error: argument --category: expected one
argument` with exit code `2`. The same defect also glob-expanded values
containing `*` and split values containing spaces, which turned a rejected value
into an empty result. See `../../issues/done/issue-bin-wrapper-drops-empty-arguments.md`.

## Examples

```bash
# Include only one category
topsailai_list_sessions --included-categories agent

# Include several categories, comma-separated or repeated
topsailai_list_sessions --included-categories agent,chat
topsailai_list_sessions --included-categories agent --included-categories chat

# Include uncategorized sessions
topsailai_list_sessions --included-categories ""

# Exclude one category
topsailai_list_sessions --excluded-categories agent_driver

# Exclude several categories, comma-separated or repeated
topsailai_list_sessions --excluded-categories agent_driver,agent
topsailai_list_sessions --excluded-categories agent_driver --excluded-categories agent

# Exclude uncategorized sessions
topsailai_list_sessions --excluded-categories ""

# Combine an inclusion filter with an exclusion
topsailai_list_sessions --category agent --excluded-categories agent_driver
topsailai_list_sessions --included-categories agent,agent_driver --excluded-categories agent_driver

# Keep only sessions bound to a project workspace
topsailai_list_sessions --has-project

# Keep a creation-time window, inclusive on both ends
topsailai_list_sessions --since 2026-07-28T00:00:00 --until 2026-07-28T23:59:59

# A page stays full because the filters run before pagination
topsailai_list_sessions --has-project --limit 10 --offset 20
```
