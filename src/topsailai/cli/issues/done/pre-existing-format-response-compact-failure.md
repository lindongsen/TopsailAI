---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai/cli
---

# Pre-existing Compact Format Response Test Failure

## Observation

The complete CLI unit suite reports one failure in `tests/unit/topsailai_format_response/test_topsailai_format_response.py::TestFormatResponseCli::test_main_compact` at line 65. The assertion expects compact output to remain on one line, but the current formatter output does not satisfy that expectation.

## Reproduction

Run the complete unit suite with color disabled. The result observed on 2026-08-04 was `1 failed, 1053 passed`.

## Scope

The failure exists outside the send-control refactor and does not exercise any changed send-control, shared log parsing, YAML command registration, or runtime help code. It is recorded for separate triage and is not fixed as part of the current task.

## Resolution

Resolved by commit `8b77d22c` ("fix: redirect format_response debug output to stderr"), which is an ancestor of the current HEAD. The compact-format assertion at line 65 now passes because debug output no longer shares stdout with the formatted result.

Verified on 2026-11-03:

```text
$ uv run python -m pytest tests/unit/topsailai_format_response/test_topsailai_format_response.py -q --color=no
15 passed in 1.70s

$ uv run python -m pytest "tests/unit/topsailai_format_response/test_topsailai_format_response.py::TestFormatResponseCli::test_main_compact" -q --color=no
1 passed in 0.25s
```

The complete unit suite also passes (`3296 passed`), so the failure recorded on 2026-08-04 no longer reproduces.
