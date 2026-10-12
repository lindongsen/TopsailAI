---
maintainer: AI
author: DawsonLin
---

# Empty plugin environment prevents driver tool discovery

Status: resolved in working tree.

An inherited empty TOPSAILAI_PLUGIN_TOOLS survived setdefault and prevented local plugin discovery. The driver now defaults missing or whitespace-only values to plugins.tools before framework imports while preserving nonblank values. Fresh-process regressions verify plugin tool callables and generated chat schemas; all 53 driver tests passed. Existing tmux processes require restart to load the repair.

## Final incremental repair

The final implementation supersedes the default-only approach above: driver plugins are mandatory. Merge TOPSAILAI_PLUGIN_TOOLS and legacy PLUGIN_TOOLS packages, preserve configured packages, append plugins.tools and deduplicate before framework imports. All 57 driver unit and BDD tests passed in 4.66 seconds, including generated chat schemas and incremental configuration cases.
