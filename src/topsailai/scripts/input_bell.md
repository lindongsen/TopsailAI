---
maintainer: AI
author: DawsonLin
workspace: ..
ProjectFolder: ..
ProjectRootFolder: ../../..
ProjectCode: TOPSAILAI
programming_language: python
---

# input_bell

Periodically checks `topsailai workspace` for sessions in the `INPUT` state and
plays a bell sound whenever at least one INPUT session is present.

## Usage

Run the script directly:

```text
python scripts/input_bell.py
```

The script loops forever, checking every `TOPSAILAI_INPUT_BELL_INTERVAL_SEC`
seconds. Stop it with Ctrl+C. To run a single check (useful for testing),
set `TOPSAILAI_INPUT_BELL_ONCE=true`.

## Environment Variables

Script-owned variables are read from the process environment first, then from
`scripts/input_bell.env`, then built-in defaults. A missing `.env` file is
harmless.

| Variable | Default | Description |
|---|---|---|
| `TOPSAILAI_INPUT_BELL_INTERVAL_SEC` | `30` | Polling interval in seconds between checks. Must be a positive integer. |
| `TOPSAILAI_INPUT_BELL_ONCE` | `false` | When `true`, run a single check and exit; exit code `0` when INPUT sessions were found, `1` otherwise. |
| `TOPSAILAI_INPUT_BELL_SOUND` | `ffplay -nodisp -autoexit -loglevel quiet -f lavfi -i sine=frequency=880:duration=0.3` | Shell command that plays the bell sound. Override with any command that produces an audible alert. |
| `TOPSAILAI_INPUT_BELL_TOPSAILAI_CMD` | `topsailai` | Command used to query the workspace task list. |

## Behavior

- Runs `topsailai workspace` and looks for lines containing the `INPUT` status.
- When at least one INPUT session is found, plays the configured bell sound once
  per check cycle.
- Playback and query failures are logged as warnings and do not stop the loop.
- The default sound uses `ffplay` to synthesize a short 880 Hz sine tone, so no
  audio file or display is required.
