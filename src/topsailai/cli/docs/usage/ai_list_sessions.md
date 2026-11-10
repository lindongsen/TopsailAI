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
| `--category <value>` | Exact category filter. Omit the option to include every category; pass an empty value to select uncategorized sessions. Invalid values are logged and select uncategorized sessions. |
| `--excluded-categories <names>` | Exclude sessions whose category is listed. Accepts comma-separated names and may be repeated. Pass an empty value to exclude uncategorized sessions. An invalid name is rejected with `Error: Invalid excluded category: '<name>'` and exit code `1`. |
| `--json` | Emit the existing JSON array shape with an additive `category` field. |
| `--offset` / `--limit` | Apply pagination after the database category predicates, so a page always contains the requested number of surviving rows. |

Text output keeps `Total` as the displayed page size and adds `Matched Total` for category-filtered queries. `Matched Total` is the pre-pagination count of matching IDs and categories, including the exclusion when `--excluded-categories` is used.

Both category predicates run in the database, so the exclusion never reads rows it discards. The default ordering is by creation time, which is indexed, so a page query does not scan the whole session table.

Category values are validated as lowercase letters, digits, and underscores; no enum allowlist is used. The CLI does not use `TOPSAILAI_SESSION_CATEGORY` as a query default.

## Empty values through the `bin/` wrapper

An empty value reaches the script only when it is invoked directly, for example
`./ai_list_sessions.py --excluded-categories ""`. The `../bin/ai_list_sessions`
wrapper ends with `run_cli ai_list_sessions $*`, and the unquoted `$*` word-splits
its arguments, so an empty string is dropped and the child reports
`error: argument --excluded-categories: expected one argument` with exit code `2`.
This affects `--category ""` identically and predates this option. The wrapper is
outside this workspace, so it is reported rather than edited.

## Examples

```bash
# Exclude one category
topsailai_list_sessions --excluded-categories agent_driver

# Exclude several categories, comma-separated or repeated
topsailai_list_sessions --excluded-categories agent_driver,agent
topsailai_list_sessions --excluded-categories agent_driver --excluded-categories agent

# Exclude uncategorized sessions
topsailai_list_sessions --excluded-categories ""

# Combine an inclusion filter with an exclusion
topsailai_list_sessions --category agent --excluded-categories agent_driver
```
