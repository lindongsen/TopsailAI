---
maintainer: AI
---

# AI-Added Features

## Context Auto-Selection for `topsailai_launch_agent`

`topsailai_launch_agent` now automatically selects a context item from `.topsailai/settings.yaml` when `--item` is not provided. If the `context` section is empty, an interactive setup guides the user to configure context files before launching. When multiple context items exist, the launcher presents each item's full configuration (context files and environment variables) and lets the user choose, defaulting to the `default` item if it exists.
