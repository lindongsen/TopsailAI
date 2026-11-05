# Per-Model Usage Statistics Reference

This document is the self-contained reference for answering "where is the
usage data broken down by model". It describes the three storage locations, the
exact file naming rules, every field, and the caveats that change how the
numbers must be interpreted.

## Which store answers which question

| Question | Store |
|---|---|
| How much work did one model serve in total? | `{TOPSAILAI_HOME}/workspace/stats/*.model.stats.json` |
| What did one specific attempt do, and with which model? | `{TOPSAILAI_HOME}/workspace/task/*.session.stats.jsonl` |
| What are the totals of one conversation? | `{TOPSAILAI_HOME}/memory.db`, table `session` |

Only the first two carry a model dimension. The `session` table has **no
`model_name` column**, so `topsailai_list_sessions` and
`topsailai_session_info` can never answer a per-model question.

## Store 1: per-model cumulative documents

### Location and naming

The directory is `{TOPSAILAI_HOME}/workspace/stats`, where `TOPSAILAI_HOME`
defaults to `$HOME/.topsailai`.

The file name is:

```text
{slug}.{digest}.model.stats.json
```

| Part | Rule |
|---|---|
| `slug` | The model name with every character outside `A-Za-z0-9._-` replaced by `_`, truncated to 48 characters, then stripped of leading and trailing `._-`. An empty or unusable name becomes `unknown`. |
| `digest` | The first 8 hex characters of the SHA-256 of the exact model name. It keeps two names that sanitize identically (`a/b` and `a:b`) in separate documents. |
| suffix | The fixed suffix `.model.stats.json`. |

The name contains no PID segment, because one model owns one document
regardless of which process writes it. A sibling `{document}.lock` file is
created by the advisory lock and is intentionally retained so every contender
always locks the same inode; it is empty and is not a statistics document.

### Field reference

Every accumulated field is a **non-negative integer total**. A value that is
missing, negative, or not exactly an `int` contributes `0` instead of
corrupting the accumulator.

Metadata fields:

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | Document schema version. Currently always `1`. |
| `model_name` | string | The exact model name the totals belong to. |
| `model_slug` | string | The sanitized slug used in the file name, without the suffix. |
| `first_seen` | string | Host-local, timezone-aware ISO-8601 timestamp with microseconds, set on the first successful merge and preserved afterwards. |
| `last_updated` | string | Host-local, timezone-aware ISO-8601 timestamp with microseconds, refreshed on every successful merge. |

Accumulated totals:

| Field | Unit | Meaning |
|---|---|---|
| `turn_count` | count | Settled User2Agent attempts attributed to this model. Each settled attempt contributes exactly `1`. |
| `tool_call_count` | count | Tool calls executed while this model was active. |
| `tool_error_count` | count | Tool calls that reported an error while this model was active. |
| `llm_request_count` | count | Provider request attempts made while this model was active, including retries. |
| `llm_request_failure_count` | count | Provider request attempts that failed to return meaningful response content. |
| `tool_duration_ms_sum` | milliseconds | Summed measured tool execution duration. |
| `llm_request_duration_ms_sum` | milliseconds | Summed measured provider request duration. |
| `prompt_tokens` | tokens | Summed prompt (input) tokens, including cached tokens. |
| `completion_tokens` | tokens | Summed completion (output) tokens. |
| `cached_tokens` | tokens | Summed prompt tokens served from the provider cache. A subset of `prompt_tokens`. |
| `first_byte_sum_ms` | milliseconds | Summed time from request start to the first decoded stream chunk. |
| `first_byte_count` | count | Number of streaming responses that contributed a first-byte measurement. |

### Write path

Each settled User2Agent attempt produces one framed delta. The delta is handed
to a process-owned statistics worker that runs on a daemon thread, so the
execution thread performs no storage I/O.

- **Merge, not append.** The writer reads the current document, adds the delta
  to every total, and republishes the whole document. The file always contains
  one single-line JSON object, never one line per attempt.
- **Atomic publication.** The merged document is written to `{document}.tmp`,
  flushed, `os.fsync()`-ed, then published with `os.replace()`.
- **Cross-process serialization.** The read-merge-write cycle runs under an
  exclusive advisory `flock` on `{document}.lock`.
- **Best effort.** Any storage failure is reported through a bounded diagnostic
  category and never interrupts the Agent flow. A failed write is not requeued.

### Derived values

The document stores sums only; averages are computed by the reader.

| Derived value | Formula |
|---|---|
| Average tool duration | `tool_duration_ms_sum / tool_call_count` |
| Average provider request duration | `llm_request_duration_ms_sum / llm_request_count` |
| Average first-byte latency | `first_byte_sum_ms / first_byte_count` |
| Uncached prompt tokens | `prompt_tokens - cached_tokens` |
| Cache hit ratio | `cached_tokens / prompt_tokens` |
| Tool error ratio | `tool_error_count / tool_call_count` |
| Provider failure ratio | `llm_request_failure_count / llm_request_count` |

Guard every division by a zero denominator. The duration sums only include
operations that produced a valid measurement, while the count fields include
every operation, so these averages are approximations rather than exact means.

### Retention

Expired documents are deleted after a successful write, at most once per
process:

- The default retention is 30 days, measured from the file modification time.
  A retention value of `0` disables age-based deletion.
- Only regular files whose name ends with `.model.stats.json` are considered.
  Neighbouring files, `.lock` files and symlinks are never touched.
- The document currently being written is always protected, even when it looks
  expired.
- A sweep failure is reported and never fails the write that triggered it.

### Reading caveats

- **`turn_count` counts settled attempts, not successes.** Failed, interrupted
  and abandoned attempts also contribute `1`. Use `llm_request_failure_count`
  and `tool_error_count` to judge health.
- **Only sessions with a session id are recorded.** An attempt without a
  resolvable session id is skipped.
- **Only User2Agent attempts are recorded.** Direct `llm_shell` chats do not
  produce a model document.
- **The first settled attempt of a binding starts from a zero baseline.** For a
  freshly created agent that equals exactly the first attempt's work.
- **A damaged document is replaced, not repaired.** An unreadable document is
  reported as `invalid_document` and the merge restarts from empty totals.
- **Reads are capped at 65536 bytes.** A larger document is truncated on read,
  treated as damaged, and replaced. With twelve integer totals the document
  stays around 550 bytes, so the cap is a safety bound rather than a practical
  limit.
- **Unknown fields are preserved.** A merge keeps fields written by a newer
  version, so a forward-compatible reader can rely on them surviving a
  downgrade.

### Example document

A real document from `{TOPSAILAI_HOME}/workspace/stats/`, reformatted for
readability:

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

Reading that example: 4 settled attempts produced 163 tool calls and 186
provider request attempts, one of which failed; average tool duration is about
707 ms, average provider request duration about 11.0 s, average first-byte
latency about 3.7 s over 185 measured streams, and about 96.4% of prompt tokens
were served from cache.

## Store 2: per-attempt session records

### Location and naming

```text
{TOPSAILAI_HOME}/workspace/task/{session_id}.{pid}.session.stats.jsonl
```

`session_id` must match `[A-Za-z0-9_-]{1,64}` and an empty id becomes
`topsailai`. Unlike the model documents, this store is **per process** and is
an append-only JSON Lines log with one record per settled attempt.

### Record shape

Each line is one JSON object. The fields that matter for a per-model query are:

| Field | Meaning |
|---|---|
| `session_id`, `pid`, `thread_id` | Owning session and process. |
| `record_id` | `{writer_instance_id}:{agent_instance_id}:{attempt_seq}`. |
| `attempt_seq` | Monotonic attempt number inside the agent instance. |
| `outcome` | Settled attempt outcome, for example `success`. |
| `model_name` | The model active during that attempt. This is the field to group by. |
| `agent_name`, `agent_type`, `agent_role` | Agent identity for the attempt. |
| `sources` | Tracker instance ids: `model_instance_id`, `tool_stat`, `token_stat`, `llm_request_stat`. |
| `availability` | Per-section availability state and the metrics deliberately not computed. |
| `tool_stat`, `token_stat`, `llm_request_stat` | Snapshot of the trackers at settle time. |

The `token_stat` snapshot carries `total_prompt_tokens`,
`total_completion_tokens`, `total_usage_tokens`, `total_cached_tokens` and the
first-byte min/average/max values. The `llm_request_stat` snapshot carries
`total_requests`, `request_successes`, `request_failures` and the request
duration min/average/max values.

### Rotation

Rotation bounds this store: 1048576 bytes per file, 3 backups, 7 days
retention, at most 100 groups, and 4096 bytes per record. Backups are named
`{stem}.{index}.jsonl`. Because of rotation and retention, the JSONL store is a
bounded recent history, not a complete archive.

### Aggregating by model

Group records by `model_name` and sum the snapshot totals. Two cautions:

- Records whose `model_name` is absent or `unknown` cannot be attributed.
- The snapshots are cumulative tracker values at settle time, so summing
  `total_prompt_tokens` across records of one session double-counts earlier
  attempts. Prefer the per-model documents for totals, and use this store for
  per-attempt attribution and history.

## Store 3: session totals in the database

`{TOPSAILAI_HOME}/memory.db`, table `session`, holds conversation totals:
`total_tokens`, `total_cached_tokens`, `total_completion_tokens`,
`turn_count`, `tool_call_count`, `tool_error_count`, `llm_request_count`,
`llm_request_failure_count`, `tool_duration_ms_sum`,
`llm_request_duration_ms_sum`, `summary_count`.

There is no `model_name` column. `topsailai_session_info` maps the legacy
prompt-only `total_tokens` column to `total_prompt_tokens` and derives
`total_usage_tokens` from prompt plus completion totals.

## No CLI reader exists

No `topsailai` subcommand lists or aggregates the per-model documents, and
`topsailai models` manages only the model registry at
`{TOPSAILAI_HOME}/.models.jsonl`.

To produce a per-model report, read the documents directly and aggregate them
yourself, for example:

```bash
python3 - <<'PY'
import glob, json, os
root = os.path.join(os.environ.get("TOPSAILAI_HOME", os.path.expanduser("~/.topsailai")),
                    "workspace", "stats")
for path in sorted(glob.glob(os.path.join(root, "*.model.stats.json"))):
    with open(path, encoding="utf-8") as stream:
        doc = json.load(stream)
    print(doc["model_name"], doc["turn_count"], doc["llm_request_count"],
          doc["prompt_tokens"], doc["cached_tokens"], doc["completion_tokens"])
PY
```
