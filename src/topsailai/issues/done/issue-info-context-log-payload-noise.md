---
maintainer: AI
author: DawsonLin
status: resolved
---

# INFO context logging emits unbounded conversation payloads

## Observation

Recent log inspection on 2026-10-24 found a single `new context messages:` INFO line at 00:38:59.170 measuring 243427 characters in the main log and 243412 characters in the chat log. Its prefix includes the system prompt and its body contains conversation history. Another recent tail sample of the rotated main log includes a 761484-character line with the same prefix. These are character counts, not byte counts.

Agent-home log filenames inspected: `topsailai.log`, `chat.log`, and `topsailai.log.1` under the log directory resolved by `workspace/folder_constants.py`. Samples were limited to the last 3000 lines within the final 4 MB of each file. The files were actively growing; measurements are snapshots, not immutable inventories.

## Source and impact

`workspace/context/agent2llm.py:475` interpolates the complete rebuilt message list into an INFO log. This makes routine summarization write potentially hundreds of kilobytes of prompt/history data, obscures useful diagnostics, accelerates rotation, and unnecessarily copies potentially sensitive conversation content into operational logs. No concrete secret values were inspected or reproduced in this issue.

`logger/base_logger.py::setup_logger` installs a dedicated chat file handler without disabling propagation, while `configure_root_logger` installs the main file handler. Matching timestamp/thread/message prefixes occur in both files; a recent-window comparison found 976 shared unique header prefixes among 1265 main-log prefixes and 1135 chat-log prefixes. The samples have different time spans, so this is overlap evidence, not a global duplication rate.

## Suggested bounded repair

Replace the complete INFO message-list dump with a summary containing message count, estimated size, and session correlation only. Any detailed diagnostic mode should be explicitly enabled, size-bounded, and redacted; simply moving an unlimited payload to DEBUG is insufficient. Separately decide whether chat records should propagate to the main file; preserve required error visibility if routing is changed.

## Acceptance for a future implementation

A large synthetic conversation must not appear verbatim in INFO logs; output size must remain bounded independently of conversation size. Verify chat/root routing with real handlers and retain error diagnostics. This analysis task makes no source changes and runs no tests.

## Resolution

Replaced the full INFO conversation dump with bounded message/token/layer/session metadata, reused the existing token estimate, and removed the redundant payload record. Routine chat records now stay in chat.log; ERROR/CRITICAL remain in the main and error logs. Expected tool disables, interactive hints, normal system merges, and successful marker removals retain DEBUG diagnostics. Request-stat display remains per request; cumulative file persistence is activity-triggered at most once per 60 seconds per instance.

Focused checks passed (91 summary, 52 logger, 72 tool, 126 status checks plus 75 strengthened checks). Final project runner: 409/410 files passed, 12530 passed cases, 2 failed, no skips/errors/incomplete files. The remaining two environment-command masking assertions fail identically at pristine HEAD; tracked separately in issue-log-noise-verification-baseline.md. Full-run Hook timing transients recovered on retry. No source/business behavior or environment defaults changed, no commits made. Detailed commands and evidence summary: `.task/check_20261024T012130_log-noise-fix.md`.
