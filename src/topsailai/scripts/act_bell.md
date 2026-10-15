---
maintainer: AI
author: DawsonLin
workspace: ..
ProjectFolder: ..
ProjectRootFolder: ../../..
ProjectCode: TOPSAILAI
programming_language: shell
---

# act_bell

Ring a bell once. The script plays a single short tone through `ffplay` when an
audio route is available, otherwise it emits the terminal bell character so the
caller still receives one ring.

## Usage

```text
scripts/act_bell.sh
```

Show help:

```text
scripts/act_bell.sh --help
```

## Environment Variables

Script-owned variables are read from the process environment first, then from
`scripts/act_bell.env`, then built-in defaults. A missing `.env` file is
harmless.

| Variable | Default | Description |
|---|---|---|
| `TOPSAILAI_ACT_BELL_SOUND` | built-in `ffplay` sine tone | Optional shell command that plays the bell sound. When set, it is run unchanged; when unset, a short 880 Hz tone is synthesized with `ffplay`. |

## Behavior

- Plays the configured sound command once when it is available.
- Falls back to the terminal bell character (`\a`) when the sound command is
  missing or fails, so exactly one ring is always attempted.
- Exit code `0` means the bell was rung; exit code `1` means invalid usage.
