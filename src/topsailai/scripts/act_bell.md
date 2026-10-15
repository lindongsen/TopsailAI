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
- When no sound command is set, synthesizes a short 880 Hz tone with `ffplay`,
  trying the default audio route first and then direct ALSA playback devices
  discovered from `/dev/snd`. A route is accepted only when `ffplay` does not
  report an audio-initialization failure; `ffplay` can exit `0` even when audio
  initialization fails, so the exit code alone is not trusted.
- Falls back to the terminal bell character (`\a`) when no usable audio route is
  found, so exactly one ring is always attempted.
- Exit code `0` means the bell was rung; exit code `1` means invalid usage.
