---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai/cli
---

# Runtime Control Command Optional Arguments Dispatch Failure

## Root Cause

The YAML template `/control {command} {args}` is converted to a regular expression that requires the literal space and `{args}` capture. Therefore `/control hard_interrupt` does not match even though the payload is documented as optional and the target CLI defaults it to an empty JSON object.

The generic `args` shell substitution also inserts the captured JSON directly before `shlex.split`. JSON quote characters are interpreted as shell syntax and removed, so the target command receives invalid JSON such as `{reason:timeout}` instead of `{"reason":"timeout"}`.

## Detection Failure

Existing tests covered the send-control entry point and generic YAML matching independently, but did not verify the real `/control` definition through runtime-scope matching and command construction. The planned manual verification exposed the gap.

## Resolution

Trailing `{args}` is now optional during YAML matching, and `/control` preserves the JSON payload as one argument while generic command argument expansion remains unchanged. Focused unit tests and `tests/manual/verify_runtime_control_dispatch.py` verify both omitted and JSON payload forms.
