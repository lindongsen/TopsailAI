---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
---

# Model Stats Document (`*.model.stats.json`)

This document describes the per-model cumulative statistics document stored under
`{TOPSAILAI_HOME}/workspace/stats/`, and explains every field it contains.

## Purpose

The session statistics record conversation totals, while this document records the same
work attributed to the **model that performed it**. It answers questions such as:

- How many turns, tool calls and LLM requests has one model served?
- How many prompt, completion and cached tokens has one model consumed?
- How much wall time did tool execution, provider requests and first-byte waits take?
- How often did provider requests fail?

One model name owns exactly one document, so totals are cumulative across sessions,
processes and restarts instead of being a per-attempt log.

## Location and Naming

The directory is the `FOLDER_WORKSPACE_STATS` constant in
`workspace/folder_constants.py`, which resolves to `{TOPSAILAI_HOME}/workspace/stats`.
`TOPSAILAI_HOME` defaults to `$HOME/.topsailai`.

The file name is built by `model_stats_path()` and `model_slug()` in
`workspace/model_stats_writer.py`:

```text
{slug}.{digest}.model.stats.json
```

| Part | Rule |
|---|---|
| `slug` | The model name with every character outside `A-Za-z0-9._-` replaced by `_`, truncated to 48 characters, then stripped of leading and trailing `._-`. An empty or unusable name becomes `unknown`. |
| `digest` | The first 8 hex characters of the SHA-256 of the exact model name. It keeps two names that sanitize identically (`a/b` and `a:b`) in separate documents. |
| suffix | The fixed `DOCUMENT_SUFFIX` value `.model.stats.json`. |

The name contains no PID segment, because one model owns one document regardless of
which process writes it.

A sibling `{document}.lock` file is created by the advisory lock and is intentionally
retained so every contender always locks the same inode. It is empty and is not a
statistics document.

## Write Path

The document is produced by the Hook Point module
`hooks/points/workspace/after_attempt_settle_user2agent/modules/model_metrics.py`,
invoked through `hook__workspace__after__attempt_settle_user2agent()` from
`workspace/agent/agent_shell_base.py` after each settled User2Agent attempt.

The write path has these properties:

- **No I/O on the execution thread.** The hook only builds a framed delta document and
  hands it to the process-owned statistics worker (`workspace/session_stats_service.py`,
  daemon thread `session-stats`), which performs the storage call.
- **Merge, not append.** `ModelStatsWriter.append()` reads the current document, adds the
  delta to every total, and republishes the whole document. The file therefore always
  contains one single-line JSON object, never one line per attempt.
- **Atomic publication.** The merged document is written to `{document}.tmp`, flushed,
  `os.fsync()`-ed, then published with `os.replace()`. A partial document is never
  visible, and the temporary file is removed on every exit path.
- **Cross-process serialization.** The read-merge-write cycle runs under an exclusive
  advisory `flock` on `{document}.lock`, so concurrent processes accumulate into the same
  totals instead of overwriting each other.
- **Best effort.** Any storage failure is reported through a bounded diagnostic category
  and never interrupts the Agent flow. A rejected or failed write is not requeued.

## Field Reference

Every accumulated field is a **non-negative integer total**. A value that is missing,
negative, or not exactly an `int` contributes `0` instead of corrupting the accumulator.

### Metadata fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | Document schema version. Currently always `1`. |
| `model_name` | string | The exact model name the totals belong to, as reported by `LLMModel.model_name`. |
| `model_slug` | string | The sanitized slug used in the file name, without the `.model.stats.json` suffix. |
| `first_seen` | string | Host-local, timezone-aware ISO-8601 timestamp with microseconds, set on the first successful merge and preserved afterwards. |
| `last_updated` | string | Host-local, timezone-aware ISO-8601 timestamp with microseconds, refreshed on every successful merge. |

### Accumulated totals

| Field | Unit | Meaning |
|---|---|---|
| `turn_count` | count | Settled User2Agent attempts attributed to this model. Each settled attempt contributes exactly `1`. |
| `tool_call_count` | count | Tool calls executed while this model was active. |
| `tool_error_count` | count | Tool calls that reported an error while this model was active. |
| `llm_request_count` | count | LLM provider request attempts made while this model was active, including retries. |
| `llm_request_failure_count` | count | Provider request attempts that failed to return meaningful response content. |
| `tool_duration_ms_sum` | milliseconds | Summed measured tool execution duration. |
| `llm_request_duration_ms_sum` | milliseconds | Summed measured provider request duration. |
| `prompt_tokens` | tokens | Summed prompt (input) tokens, including cached tokens. |
| `completion_tokens` | tokens | Summed completion (output) tokens. |
| `cached_tokens` | tokens | Summed prompt tokens served from the provider cache. A subset of `prompt_tokens`. |
| `first_byte_sum_ms` | milliseconds | Summed time from request start to the first decoded stream chunk. |
| `first_byte_count` | count | Number of streaming responses that contributed a first-byte measurement. |

## Where Each Total Comes From

The producer reads two different kinds of cumulative tracker, which is why the deltas are
computed differently.

### Agent-owned counters

`ToolStat` and `LLMRequestStat` are owned by the agent and stay cumulative across a model
switch. Their baseline is therefore advanced on every settled attempt, and the resulting
delta is attributed to the model that was active during that attempt.

| Document field | Source tracker attribute | Conversion |
|---|---|---|
| `tool_call_count` | `ToolStat._call_sequence` | none |
| `tool_error_count` | `ToolStat._error_count` | none |
| `tool_duration_ms_sum` | `ToolStat._execution_duration_sum_sec` | seconds × 1000, rounded to int |
| `llm_request_count` | `LLMRequestStat._total_requests` | none |
| `llm_request_failure_count` | `LLMRequestStat._request_failures` | none |
| `llm_request_duration_ms_sum` | `LLMRequestStat._request_duration_sum_sec` | seconds × 1000, rounded to int |

### Model-owned counters

`TokenStat` belongs to one `LLMModel` instance, so its totals are already scoped to a
single model. The baseline is kept per model instance identity, so switching models and
switching back does not mix their token totals.

| Document field | Source tracker attribute | Conversion |
|---|---|---|
| `prompt_tokens` | `TokenStat.total_count` | none |
| `completion_tokens` | `TokenStat.total_completion_count` | none |
| `cached_tokens` | `TokenStat.total_cached_tokens` | none |
| `first_byte_sum_ms` | `TokenStat.first_byte_sum_ms` | rounded to int |
| `first_byte_count` | `TokenStat.first_byte_count` | none |

### Delta rule

Every contribution is `current - previous`, and a non-positive difference contributes `0`.
Totals are therefore monotonic: a tracker reset (for example `ToolStat.clear()`) can only
stop future growth, it can never decrease a stored total.

## Derived Values

The document stores sums only. Averages are computed by the reader:

| Derived value | Formula |
|---|---|
| Average tool duration | `tool_duration_ms_sum / tool_call_count` |
| Average provider request duration | `llm_request_duration_ms_sum / llm_request_count` |
| Average first-byte latency | `first_byte_sum_ms / first_byte_count` |
| Uncached prompt tokens | `prompt_tokens - cached_tokens` |
| Cache hit ratio | `cached_tokens / prompt_tokens` |
| Tool error ratio | `tool_error_count / tool_call_count` |
| Provider failure ratio | `llm_request_failure_count / llm_request_count` |

Guard every division by a zero denominator. Note that the duration sums only include
operations that produced a valid measurement, while the count fields include every
operation, so the averages above are approximations rather than exact means.

## What the Document Does Not Contain

The following are deliberately absent, because they are per-session or unbounded:

- Per-tool breakdowns, retained call records, success rate and duration percentiles.
- Per-session or per-agent attribution, and the attempt outcome.
- Minimum and maximum durations, and the request-rate window maximum.
- Any per-attempt history: the document is a snapshot of totals, not a log.

Per-session detail lives in `{session_id}.{pid}.session.stats.jsonl` under
`{TOPSAILAI_HOME}/workspace/task`, and settled session totals live in the session
database.

## Retention

`sweep()` deletes expired documents after a successful write, at most once per process:

- The default retention is `RETENTION_DAYS = 30` days, measured from the file modification
  time. A retention value of `0` disables age-based deletion.
- Only regular files whose name ends with `.model.stats.json` are considered. Neighbouring
  files, the `.lock` files and symlinks are never touched.
- The document currently being written is always protected, even when it looks expired.
- A sweep failure is reported and never fails the write that triggered it.

## Reading Caveats

- **`turn_count` counts settled attempts, not successes.** The producer runs after the
  attempt result is settled, so failed, interrupted and abandoned attempts also contribute
  `1`. Use `llm_request_failure_count` and `tool_error_count` to judge health.
- **Only sessions with a session id are recorded.** An attempt without a resolvable
  session id is skipped.
- **Only User2Agent attempts are recorded.** Direct `llm_shell` chats do not produce a
  model document.
- **The first settled attempt of a binding starts from a zero baseline.** The binding is
  created before the run loop, so its first delta equals the full cumulative tracker value
  at that moment; for a freshly created agent that is exactly the first attempt's work.
- **A damaged document is replaced, not repaired.** An unreadable document is reported as
  `invalid_document` and the merge restarts from empty totals.
- **Reads are capped at 65536 bytes** (`READ_CAP = LINE_CAP * 16`). A document larger than
  that cap is truncated on read, treated as damaged, and replaced. With twelve integer
  totals the document stays around 550 bytes, so the cap is a safety bound rather than a
  practical limit.
- **Unknown fields are preserved.** A merge keeps fields written by a newer version, so a
  forward-compatible reader can rely on them surviving a downgrade.

## Example

A real document from `{TOPSAILAI_HOME}/workspace/stats/`, reformatted for readability:

```json
{
  "schema_version": 1,
  "model_name": "DeepSeek-V4-Flash-Preview",
  "model_slug": "DeepSeek-V4-Flash-Preview.88193a98",
  "first_seen": "2026-11-03T10:47:23.584839+08:00",
  "last_updated": "2026-11-03T11:35:03.724850+08:00",
  "turn_count": 4,
  "tool_call_count": 163,
  "tool_error_count": 0,
  "llm_request_count": 186,
  "llm_request_failure_count": 1,
  "tool_duration_ms_sum": 115227,
  "llm_request_duration_ms_sum": 2044392,
  "prompt_tokens": 16098831,
  "completion_tokens": 87312,
  "cached_tokens": 15517568,
  "first_byte_sum_ms": 678208,
  "first_byte_count": 185
}
```

Reading that example:

- 4 settled attempts produced 163 tool calls and 186 provider request attempts, one of
  which failed.
- Average tool duration is about 707 ms, average provider request duration about 11.0 s.
- Average first-byte latency is about 3.7 s over 185 measured streams.
- About 96.4% of prompt tokens were served from cache.

The values above are a snapshot taken at `last_updated`; the live document keeps growing
as further attempts settle.

## Related Files

| File | Role |
|---|---|
| `workspace/model_stats_writer.py` | Document naming, merge, atomic publication, advisory lock, retention. |
| `hooks/points/workspace/after_attempt_settle_user2agent/modules/model_metrics.py` | Builds the per-attempt delta and hands it to the storage worker. |
| `workspace/session_stats_service.py` | Process-owned serialized storage worker and binding lifecycle. |
| `workspace/session_stats_writer.py` | Shared framing, diagnostics and storage primitives. |
| `workspace/folder_constants.py` | `FOLDER_WORKSPACE_STATS` and `TOPSAILAI_HOME` resolution. |
| `context/tool_stat.py` | Agent-owned tool counters and duration accumulator. |
| `context/llm_request_stat.py` | Agent-owned provider request counters and duration accumulator. |
| `context/token.py` | Model-owned token counters and first-byte accumulator. |
| `tests/unit/workspace/test_model_stats_writer.py` | Storage behavior and retention tests. |
| `tests/unit/workspace/test_model_metrics_hook.py` | Delta attribution and one-shot latch tests. |
