---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
---

# Summary recovery never applies because the persisted copy carries `create_time`

## Symptom

Session `wa-a3d826b4ec58` (pid `3802727`) stopped reducing its Agent2LLM message
count after a summarize. The recovery branch kept triggering, nothing was ever
applied, and the same warning repeated on every turn from `15:35` to `15:44`
(11 occurrences):

```
Summary recovery triggered: layer=agent2llm budget=89600 normal_tokens=116974
candidate_tokens=73329 reserve=4096 removed_messages=1 session_id=wa-a3d826b4ec58
```

The message count therefore never decreased, so the next turn re-triggered the
same branch. The user reported this as unacceptable.

## Evidence

- Session artifacts: `/root/.topsailai/workspace/task/wa-a3d826b4ec58.3802727.session.{meta,stdout,events,stats.jsonl}`.
- Session identity: workspace `/TopsailAI/src/topsailai`, model
  `DeepSeek-V4-Flash-Preview`, role `manager`,
  `TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS=true`.
- The ordinary path worked earlier in the same session: at `14:31:33` the
  context went `137 -> 13` messages and logged
  `New context messages for processing: msg_len=[13]`. The failure starts only
  once the observation-recovery branch is entered.
- The real database is `/opt/git/ai/lindongsen/work/hosts/.topsailai/memory.db`
  (the process working directory), not `/TopsailAI/src/memory.db`. The session
  has 5 persisted rows.
- Blast radius, counted in `topsailai.log`: `850` occurrences of
  `Summary recovery persisted context changed` across `wa-709ebd842e8b` (87),
  `wa-4843661110c1` (56), `wa-c60749413d94` (16), `wa-a3d826b4ec58` (11).
- Probe 1: all 5 persisted rows carry `create_time`, and
  `message_key(persisted) != message_key(in_memory)` for every row.
- Probe 2, modelling the real turn lifecycle: rows `[0..3]` compare equal
  because `reset_messages()` reloaded them from the database at turn start, and
  only the newest row `d083d6e8afb816a4f5a9ea9eb5ead8cf` differs. That is
  exactly the message appended during the current turn.
- Probe 3: reproduced the exact
  `RuntimeError: Summary recovery persisted context changed; originals retained`.
- Probe 4: applying the existing `history_replay_semantic_projection`
  (`utils/history_replay_message.py`, fields `role, content, name, tool_calls,
  tool_call_id, function_call`) makes all 5 keys equal.

## Root cause

`workspace/context/summary_recovery_runtime.py:102` compares the in-memory
session list against the persisted rows with `message_key()`:

```python
if [message_key(item.message) for item in raw] != [message_key(message) for message in session_before]:
    raise RuntimeError("Summary recovery persisted context changed; originals retained")
```

`message_key()` (`workspace/context/summary_recovery.py:40-42`) canonicalizes the
whole message dict with `json.dumps(..., sort_keys=True)`, so every field
participates in equality.

`context/chat_history_manager/__base.py:453-456` prepends storage metadata to the
persisted copy for every non-system message:

```python
if last_message["role"] != ROLE_SYSTEM:
    new_last_message = {"create_time": get_current_date(include_ms=True)}
    new_last_message.update(last_message)
    last_message = new_last_message
```

The in-memory copy appended during the turn has no `create_time`, so the two
sides can never agree for the message written in the current turn. The guard
raises, and nothing is applied.

## Why the failure is silent and self-perpetuating

`apply_recovery()` raises `RuntimeError`, which is not a domain control-flow
error, so `ai_base/prompt_base.py:299-300` swallows it:

```python
except Exception as e:
    logger.exception("failed to call hook [%s]: %s", hook, e)
```

The agent then continues with an unchanged, oversized context. The recovery
branch also returns `None` instead of falling through to the ordinary
summarization path, so the path that worked at `14:31:33` is never reached
again. This is the same defect class already recorded in `LEARN.md` under
"Do not use assert for recoverable control flow that must cross a swallowing
exception boundary".

## Why the tests cannot see it

- `tests/unit/workspace/context/test_summary_recovery.py::test_storage_reload`
  and `test_storage_failures_keep_memory` build
  `SimpleNamespace(msg_id=..., message=msg)` from the in-memory dict, so the
  persisted shape is modelled as byte-identical to memory.
- `tests/bdd/test_summary_observation_recovery.py` contains no `create_time`
  either.

Both suites are green while the production shape can never match.

## Fix direction

1. Compare persisted and in-memory messages by semantic projection instead of
   raw `message_key`, so storage metadata such as `create_time` is excluded from
   the equality decision. Reuse the existing
   `history_replay_semantic_projection` helper rather than adding a second
   spelling of "semantic message".
2. Add a regression test whose fixture writes `create_time` into the persisted
   record while the in-memory copy lacks it, and assert `apply_recovery()`
   succeeds. Confirm the new test fails on a pristine worktree first.
3. Decide the failure contract: a failed recovery should fall through to the
   ordinary summarization path, or at minimum surface a visible error, instead
   of silently returning `None` while the context grows.

## Secondary observation

Even when applied, the plan removes only the single opening observation
(`removed_messages=1`), so the reduction is marginal. The apply failure is the
primary defect, but the recovery policy's effectiveness deserves a separate
review.

## Impact

Any session that enters the observation-recovery branch can never apply it, so
its Agent2LLM context keeps growing while the trigger log line keeps appearing.
The session looks like it is summarizing while it is not.

## Resolution (2026-11-17): obsolete, the mechanism was removed

This issue is closed as **obsolete**, not as repaired. The defect it describes is
real and was real in production, but the code that carried it no longer exists.

### The mechanism was deleted two hours after this issue was written

This issue was authored at `2026-11-16 16:11`. Commit
`71bc21d4 refactor: remove summary observation recovery mechanism`
(`2026-11-16 18:07:19`) deleted the whole feature: 16 files, 66 insertions,
938 deletions. `git merge-base --is-ancestor 71bc21d4 HEAD` confirms it is an
ancestor of the current tree.

Deleted outright:

- `workspace/context/summary_recovery.py` (185 lines)
- `workspace/context/summary_recovery_runtime.py` (141 lines)
- `tests/unit/workspace/context/test_summary_recovery.py` (373 lines)
- `tests/bdd/test_summary_observation_recovery.py` (117 lines)
- `tests/bdd/features/summary_observation_recovery.feature` (20 lines)

`git ls-files | grep -i summary_recovery` returns nothing. Only stale
`__pycache__` bytecode remains on disk, which is a build artifact, not source.

`message_key()`, the function whose whole-dict canonicalization caused the
mismatch, no longer exists anywhere in the repository.

### All three fix directions are satisfied by the replacement

The replacement is `release_opening_observation_after_summary`, built after the
removal in `ea6b0cba`, `ef64d04d`, `b7ac8652`, `b6b5ff9a` and `4fc339e8`.

1. **Semantic projection instead of raw equality.** `workspace/context/base.py`
   `_match_persisted_rows()` compares
   `history_replay_semantic_projection(raw_dict)` against the removed message's
   projection. `workspace/context/agent.py` `_semantic_message()` wraps the same
   helper for cross-turn deduplication. The helper is the existing
   `utils/history_replay_message.history_replay_semantic_projection`, exactly as
   this issue requested, not a second spelling of "semantic message".
2. **Regression test with `create_time` on the persisted side.**
   `tests/unit/workspace/context/test_observation_release_after_summary.py::test_matches_by_semantic_projection_ignoring_create_time`
   sets `stored["create_time"] = 1794675567` and asserts the match succeeds.
   `tests/unit/test_topsailai_workspace_context_agent.py` adds
   `test_add_runtime_messages_keep_enabled_ignores_storage_metadata` plus the
   negative control `test_add_runtime_messages_keep_enabled_keeps_business_difference`.
3. **Failure contract.** The branch that swallowed `RuntimeError` and returned
   `None` is gone. The release now runs as a post-step inside the normal summary
   path, so a failure cannot strand the context on a branch that never falls
   through.

The trap itself is now documented at the two places that could reintroduce it:
`workspace/context/agent2llm.py` and `workspace/context/ctx_runtime.py` each
carry a warning block naming this exact incident and stating that raw-dict
comparison is forbidden.

### The underlying cause is still live, which is why the rule is mandatory

`context/chat_history_manager/__base.py` still prepends `create_time` to the
persisted copy for every non-system message. That is correct behaviour for
storage, so the fix belongs on the comparison side, and the semantic-projection
rule stays mandatory for any future code that compares memory against storage.

### Verification

Real-storage probe (`.tmp/probe_persisted_shape.py`), writing one message through
`SessionSQLAlchemy` and reading it back:

```
persisted row count: 1
stored keys : ['content', 'create_time', 'role']
runtime keys: ['content', 'role']
has create_time: True
raw equality: False
projection equality: True
```

This reproduces the exact mismatch the issue reported and proves the projection
resolves it.

Test suites:

- `tests/unit/workspace/context/test_observation_release_after_summary.py` — 47 passed
- `tests/unit/test_topsailai_utils_history_replay_message.py` — 5 passed
- `tests/bdd/test_opening_observation_release.py` — 8 passed

The deleted BDD feature was replaced, not dropped:
`tests/bdd/features/opening_observation_release.feature` covers the successor
behaviour with 8 scenarios.

### Secondary observation

The note that the recovery plan removed only the single opening observation is
moot for the same reason: the plan type no longer exists. The successor release
has its own scope, covered by the suites above.

### Residual limitation

No pristine-worktree reproduction was performed for this issue, because there is
no code to reproduce against: the files the issue names are absent from the
current tree and from every commit after `71bc21d4`. The evidence here is
absence plus the replacement's own tests, not a red-green cycle.
