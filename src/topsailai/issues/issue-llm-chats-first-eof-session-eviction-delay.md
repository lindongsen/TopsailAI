---
maintainer: AI
author: DawsonLin
status: open
---
# First EOF submission stalls behind synchronous session eviction

## Human report and reproduction

Run `SESSION_ID=test-xx1 llm_chats`, type `HELLO`, then Ctrl-D. Human explicitly requested real tmux observation. Reproduced on 2026-10-23 in dedicated tmux session `eofhang-sol-20261023`, CLI PID 1659133, with the real configured provider. No implementation files changed.

Ctrl-D submits a multiline message; it does not terminate this CLI. The first submit-to-completed-response interval was **21.172 seconds**: Ctrl-D at 15:26:57.512530, response event at 15:27:18.684636 (+08:00). Session persistence and the next input prompt followed at 15:27:18.700–18.701. A second HELLO/Ctrl-D in the same process completed in **2.52 seconds** (15:28:27.955546 to persistence at 15:28:30.490). Natural exit after EOF is not applicable: the CLI deliberately waits for another turn. Explicit interruption exited status 130 at 15:30:19.436977.

## Confirmed dominant cause

The new-session path performs synchronous capacity eviction before model construction or the first greeting request:

- `workspace/llm_shell.py:get_llm_chat:205–208` retrieves history, then creates a missing session.
- `context/ctx_manager.py:create_session:441` calls the session manager.
- `context/session_manager/manager.py:DefaultSessionManager.create_session:35` calls `cleanup.evict_sessions` synchronously.
- `context/session_cleanup.py:SessionCleanupManager.evict_sessions:71–79` lists historical sessions and attempts deletion until the 100-session soft limit is reached. Protected candidates do not decrement excess, so the scan continues.
- `context/session_cleanup.py:_can_clean:56–59` queries session provenance and calls `activity_probe.can_clean` for each candidate.
- `context/session_activity.py:can_clean:95` -> `observe:56` -> `observe_many:82` -> `_observe_root_many:108–119` enumerates and sorts the entire task directory twice for EACH session, indexing every filename at lines 135–149.

PID-scoped logs show **106** `Preserve session` decisions on the main thread, first at **15:26:57.772**, last at **15:27:12.652**, spanning **14.880 seconds** (approximately 140 ms/check). The task directory contained **5,639 entries** when counted after reproduction. Most candidates had incomplete ownership evidence and correctly remained UNKNOWN; running candidates also remained protected. Repeated full directory inventories plus per-candidate provenance queries dominate the pause. The approximate work grows as candidates times inventory size, including repeated sorting.

## Ranked remaining contributors

1. Dominant: synchronous eviction/probing, at least 14.88 seconds of observed main-thread checks before any greeting request.
2. Remaining initialization: model construction starts at 15:27:14.391; main request starts at approximately 15:27:15.224. This adds several seconds; the uninstrumented gaps are not attributed to one function.
3. Actual greeting request: recorded request duration **2.498 seconds**, first byte **0.905 seconds**. No observed retry/exhaustion evidence. This is not the dominant delay.
4. Background title generation runs in a daemon thread (`context/ctx_manager.py:457–463`), with a 1-second TokenStat batch warning at 15:27:17.547. Its request overlaps the greeting; no evidence establishes it as the first-turn blocker.

No shutdown, summary, lock-release, memory-sync, or events-flush hang was established. EOF does not enter shutdown here.

## Live blocking evidence and limitations

Installed py-spy rejected Python 3.13 with `Unsupported version of Python: 3.13.0`. Gdb attached successfully but had no `py-bt` extension. First-turn slow-phase Python stack was therefore NOT captured; attribution uses same-PID main-thread timestamped cleanup logs plus inspected direct callers, not a claimed Python live stack.

After response, gdb showed `__GI___select` -> `select_select_impl`. Strace captured `select(15, [10 14], NULL, NULL, NULL)`; descriptor 10 was the session FIFO and descriptor 14 the terminal-helper channel. The explicit interrupt traceback subsequently confirmed `workspace/input_tool.py:_input:127` -> `input_from_pipe_session:480` -> `utils/input_tool.py:input_from_pipe:1044`. This is normal unlimited next-turn input waiting, not the earlier eviction delay. Second-request strace also captured short timed futex waits, consistent with the request worker; do not interpret those as proof of the first-turn bottleneck.

## Minimal fix direction

Keep UNKNOWN/RUNNING protection and final deletion-time revalidation. Reuse one batch inventory to select eligible candidates (`observe_many` already exists), then freshly revalidate only actual deletion candidates; do not rescan the complete inventory for every protected candidate. Bound or move retention maintenance off the first-message latency path with explicit lifecycle ownership and no unsafe cleanup shortcuts. Add a focused regression asserting bounded inventory counts with many protected sessions and many task artifacts, plus continued protection and final revalidation. EOF wording may clarify submit-versus-exit separately; changing EOF to terminate would be a behavior change, not the latency fix.

## Evidence and cleanup

Artifacts: `.tmp/eofhang-20261023/` contains startup and separate interaction scripts, timestamp timeline, terminal captures, py-spy failures, gdb and strace evidence, filtered PID logs and explicit exit traceback. Raw application runtime events/logging use the CLI's normal configured store; collected inspection artifacts are task-local. Dedicated tmux session and owned CLI/helper were stopped; unrelated pre-existing CLI processes were not touched. Existing test session data was retained rather than destructively deleting history. No source modification, commit, or automated suite execution was performed.

## Implemented correction and verification

Human requested the fix and explicitly questioned why all historical sessions were inspected. The original algorithm targeted successful deletions rather than a fixed oldest-excess candidate set: each protected candidate left excess unchanged and admitted a newer candidate, potentially walking every row.

Automatic eviction now fixes the candidate set to the oldest excess rows, excluding the just-created session. Protected candidates remain without replacement by newer sessions. Selected candidates are screened in batches grouped by recorded home. Only STOPPED candidates enter the unchanged fresh provenance and double-observation deletion path. Ordered database listing still reads the session rows; activity checks do not cover retained newer sessions. Actual deletions retain their fresh directory inspections.

Verification: 182 targeted tests passed; session_cleanup.py statement coverage 65/65 and branch coverage 32/32. A real filesystem case with 110 sessions and 1,000 unrelated artifacts checks only the oldest 10 sessions with two total inventory enumerations for the protected batch. A real SQLite regression confirms only the oldest stopped excess session is removed. Race/refusal, UNKNOWN/RUNNING protection, new-session exclusion, and home grouping are covered. Evidence is under .tmp/session-eviction. Full suite, BDD, and real-provider tmux latency were not rerun; no new end-to-end timing claim is made. Code remains uncommitted pending Human review.
