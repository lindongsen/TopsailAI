---
references:
  - topsailai.py
  - cli_topsailai/
  - topsailai.yaml
---

# CLI: topsailai

## Scope: workspace

- task list

## Scope: runtime

- steam log of one session

## Scope: project

- project workspace
- shows recent records, default limit 30, use `r [limit]` to adjust

## Scope: session

- enter one session

## Scope: doc

- usage documentation list
- read usage documentation

## Command Design Convention

- Interactive parameters use option flags, for example `--agent-mode`.
- Non-interactive parameters use subcommands, for example `project list`.
