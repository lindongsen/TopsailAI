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
