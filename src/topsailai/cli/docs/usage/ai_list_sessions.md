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
| `--json` | Emit the existing JSON array shape with an additive `category` field. |
| `--offset` / `--limit` | Apply pagination after the database category predicate. |

Text output keeps `Total` as the displayed page size and adds `Matched Total` for category-filtered queries. `Matched Total` is the pre-pagination count of matching IDs and categories.

Category values are validated as lowercase letters, digits, and underscores; no enum allowlist is used. The CLI does not use `TOPSAILAI_SESSION_CATEGORY` as a query default.
