---
maintainer: AI
author: DawsonLin
---

# Runtime ctx btw all test execution checklist

## Status and ownership

Plan prepared against the approved design and implementation snapshot inspected on 2026-10-16. Tests NOT executed in this reviewer turn. This checklist is an acceptance contract, not a statement that current code passes.

- gpt-sol: independent test planning and review only; no implementation fixes.
- ds-dev: implementation and test authoring per the approved design; local repairs remain with the assigned Developer.
- Assigned Tester: execute the checks in order and record evidence; independent Reviewer accepts the logical unit after reviewing the complete diff and evidence.
- Design index: `.task/plan_20261016T175200_ctx-btw-all.md` — named-session, runtime-only, discoverable live-PID broadcast; implementation/verification pending.

## Human requirement

> runtime scope 有一个 ctx.btw 指令，它只传递当前session+pid的信息。我希望加入 ctx.btw-all 指令，它会传递session对应的所有pids的信息。可以做到吗？适合做吗？如果可以，请实现。

Test interpretation: deliver the same message to all eligible discoverable PIDs sharing the watched named session, not deliver a PID list. Preserve existing single-PID `/ctx.btw` behavior.

## Inspected context

Workspace README.md, LEARN.md, topsailai.md and docs/README.md were supplied in full. The design was read in full. Inspected current runtime_broadcast.py, streaming dispatch and message handlers, completion/help entries, runtime_operations writer and message limit, and existing test bootstrap/control patterns. The workspace directory layout and test locations were verified before inspecting implementation.

## Fixture and safety requirements

- Use isolated task directories below workspace `.tmp/ctx-btw-all/`; never use real session files or real agent task storage.
- Use positive synthetic PIDs with explicitly injected probes and writers. For permission failures use narrow doubles rather than chmod assumptions under root.
- Use module-local substitutes or dependency injection; never mutate shared os singleton attributes. Restore CLI scope/YAML state after each case.
- Fixture stdout examples: `named.101.session.stdout`, `named.101.a.task.stdout`, `named.101.b.task.stdout`, `named.102.worker.task.stdout`, `other.103.session.stdout`.
- Default expected targets: 101 and 102, exactly once each, never 103. Expected queue names: `named.101.session.agent2llm_inject_messages.jsonl` and corresponding 102 path.
- Capture stdout/stderr and assert diagnostics omit message bodies. Never execute shell-like message text.
- Put pytest basetemp/cache, bytecode, coverage, HOME, TMPDIR and reports under `.tmp/ctx-btw-all/`. Existing tests using explicit TemporaryDirectory(dir=...) must be audited for outside-workspace writes before full-suite execution; environment overrides alone cannot redirect explicit destinations.
- Do not run red-green TDD: source implementation already exists; add its verification cases now. Stop dependent progression on a failure, record it, let Developer repair, then rerun that item and affected regressions.

## Broadcast unit matrix

Add `tests/unit/topsailai/test_runtime_broadcast.py`.

- [ ] B01 Nominal session + task-only PID: ALIVE probes and successful writers produce exactly two queued outcomes; same message bytes/content for both; no other-session write; supplied task_dir wins over global home/state.
- [ ] B02 Multiple session/task evidence for one PID deduplicate by integer PID. Session evidence preferred; otherwise lexical task filename selected deterministically. Assert selected evidence, sorted stable target order and one writer call per PID.
- [ ] B03 Exact session equality excludes prefix/suffix lookalikes. Include parser-supported dotted session IDs; malformed/unsupported task names are ignored, never guessed. Ignore stderr, generic legacy stdout, directories and nonpositive/malformed PIDs.
- [ ] B04 Reject None/empty, temporary `topsailai`, display sentinel `(temp)` and invalid/path-like session identities before discovery/probe/write. No accidental grouping or successful empty result.
- [ ] B05 No matches: zero writes, zero queued, visible no-target result. Missing directory, symlink directory, non-directory and denied enumeration produce visible failures without writes.
- [ ] B06 Symlink/nonregular stdout is excluded. Existing symlink/directory/nonregular injection endpoint fails prewrite; absent valid endpoint may be created. Denied endpoint access produces a distinct prewrite diagnostic. Unrelated files stay byte-for-byte unchanged.
- [ ] B07 ALIVE, DEAD, UNKNOWN and PermissionError probe cases: only ALIVE writes; DEAD is skipped_exited; unknown is unverifiable; permission denial separately visible. No stale queue creation for skipped PIDs.
- [ ] B08 Evidence removed/renamed/replaced with a symlink before its append blocks that write, without substituting another evidence path. Process exit immediately before append blocks delivery. Do not claim inode authentication/PID-reuse protection beyond the approved contract.
- [ ] B09 Snapshot once after message acquisition: create another matching log during the first append; new PID gets no write. Change the second target evidence during the first append; second is revalidated before use.
- [ ] B10 Writer true -> queued; false -> delivery_unknown; ordinary writer exception -> delivery_unknown with safe cause type. First target failure does not suppress later eligible targets. Each writer attempted at most once; no rediscovery, retry, rollback or deletion of already queued messages.
- [ ] B11 Ordinary per-target evidence/probe/endpoint errors are bounded and reported; later eligible targets continue. Global directory errors are visible. Distinguish known prewrite failure from uncertain append rather than labeling every error as delivered or exited.
- [ ] B12 KeyboardInterrupt and SystemExit propagate from probe and writer; already completed outcomes must not become an overall success. Never catch host termination as an ordinary target failure.
- [ ] B13 Aggregate counts separate queued/skipped/failed/uncertain. Zero queued is not success. Failed, unknown or unverifiable targets mean incomplete broadcast. Known exited skips remain visible and do not falsely claim queueing to those PIDs; live-target completion semantics follow the design.

## Dispatch and UI matrix

Add `tests/unit/topsailai/test_streaming_broadcast.py`; use existing streaming suites for transport-specific routing.

- [ ] D01 `/ctx.btw-all hello` routes once to the dedicated handler, before YAML matching, with explicit watched session and supplied task_dir. Stale mutable session state and watched PID do not restrict broadcast targets.
- [ ] D02 Exact-token rejection: `/ctx.btw-all-extra` and `/ctx.btw-allx` never broadcast or run the single-target injection command. Runtime-only feature cannot execute from workspace/project/session/doc scope; exercise actual ordinary-scope boundaries, not only the runtime internal function.
- [ ] D03 Inline Unicode, quotes, shell metacharacters and flag-like text remain message data; do not invoke shell/YAML. Mixed-case/whitespace normalization follows existing dispatcher convention without truncating the message.
- [ ] D04 No inline body: curses input_provider called once with the broadcast-specific prompt; same multiline payload shared across all PIDs. Legacy collector reads until EOF/Ctrl+D. Test finite input sequences so an unexpected loop fails rather than hangs.
- [ ] D05 Provider None (Esc cancellation), legacy Ctrl+C, empty/whitespace-only input cause zero discovery/writes. Blank command itself remains harmless. Inline whitespace enters collection once, then empty collected body rejects.
- [ ] D06 Reject invalid Unicode and UTF-8 payload > 1 MiB before enumeration/write; accept exact limit, include multibyte boundary case. Verify limits in bytes, not character count.
- [ ] D07 Reject missing/temp session identity before writing, without fallback to another session. No candidate, all-dead, mixed success/error, all failed and uncertain outcomes display accurate session/PID details and summary. Announce session/candidate count before appends; avoid echoing message text.
- [ ] D08 Every successful result explicitly means queued, not consumed. Do not label partial/zero success as full success. Interrupted execution must not print final completion. Preserve prior printed target outcomes when a later append is interrupted.
- [ ] D09 Curses, raw and legacy/continuation entry paths reach the same dedicated dispatcher. Add focused routing assertions in test_streaming_curses.py, test_streaming_raw.py and test_streaming_continuation.py; do not duplicate the complete delivery matrix.
- [ ] D10 Existing `/ctx.btw` continues delegating only the watched PID. `/send`, `/control`, `/agent.*`, `/meta` and non-interactive runtime tests remain unchanged in targeting semantics. Non-interactive broadcast syntax remains rejected with no writes.

## Help, completion and documentation matrix

- [ ] H01 test_completer.py: `/ctx.btw-all` appears exactly once in runtime, even with no YAML definitions; absent in every other scope. Existing completions remain intact.
- [ ] H02 test_help_text.py: runtime help and keyword-filtered help discover broadcast and its queue-only semantics; other scopes do not list it as available. Scope introduction names both single-PID and broadcast commands accurately.
- [ ] H03 Capture every runtime startup/raw/fallback/unrecognized-input hint including the shell-fallback error paths in streaming.py. All command lists include `/ctx.btw-all`; no stale error guidance claims only `/ctx.btw` exists. Search is supplementary to behavioral output assertions.
- [ ] H04 Review README.md, topsailai.md and canonical docs/usage/topsailai.md for runtime-only syntax, named-session discovery, dedup, multiline/cancellation, snapshot timing, partial/uncertain results, no retry and queue-vs-consumption distinction. No unintended non-interactive broadcast or receiver guarantees.

## Automated queue integration

- [ ] I01 Invoke the interactive shared dispatcher using isolated stdout evidence, an injected ALIVE probe and the real runtime_operations.write_injection public writer. Inspect each generated JSONL record using the public reader or actual receiver schema. Exactly one newly appended record with identical message in each eligible queue; unrelated session queue unchanged. Existing queue prefix records remain intact.
- [ ] I02 Repeat user invocation intentionally to prove separate invocations append again; document no exactly-once guarantee across commands. This must not be mistaken for an automatic retry.
- [ ] I03 If the public core writer cannot import or fixtures cannot exercise its schema, record a blocker. A fake writer pass is only unit evidence, not integration evidence.

## Commands and execution order

Run from the workspace using the following preparation in the same shell. These are planned commands, not executed evidence. The new test files must exist before stage A.

```sh
mkdir -p /TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/home /TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/tmp /TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/cache
export HOME=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/home
export TMPDIR=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/tmp
export TOPSAILAI_HOME=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/home
export PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/bytecode
export COVERAGE_FILE=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/.coverage
export PYTHONPATH=/TopsailAI/src:/TopsailAI/src/topsailai/cli
cd /TopsailAI/src/topsailai/cli
```

Stage A — focused new cases including the automated queue integration:

```sh
time pytest --color=no -q --tb=short -o cache_dir=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/cache --basetemp=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/base-focused /TopsailAI/src/topsailai/cli/tests/unit/topsailai/test_runtime_broadcast.py /TopsailAI/src/topsailai/cli/tests/unit/topsailai/test_streaming_broadcast.py
```

Stage B — related UI/help/completion, controls and compatibility regression:

```sh
time pytest --color=no -q --tb=short -o cache_dir=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/cache --basetemp=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/base-related /TopsailAI/src/topsailai/cli/tests/unit/topsailai/test_completer.py /TopsailAI/src/topsailai/cli/tests/unit/topsailai/test_help_text.py /TopsailAI/src/topsailai/cli/tests/unit/topsailai/test_streaming_curses.py /TopsailAI/src/topsailai/cli/tests/unit/topsailai/test_streaming_raw.py /TopsailAI/src/topsailai/cli/tests/unit/topsailai/test_streaming_continuation.py /TopsailAI/src/topsailai/cli/tests/unit/topsailai/test_streaming_control.py /TopsailAI/src/topsailai/cli/tests/unit/topsailai/test_send_retrieve_stream_prompt.py /TopsailAI/src/topsailai/cli/tests/unit/topsailai/test_runtime_cli.py /TopsailAI/src/topsailai/cli/tests/unit/topsailai_session_add_agent2llm_message/test_topsailai_session_add_agent2llm_message.py
```

Stage C — entire CLI topsailai unit suite after fixture safety audit:

```sh
time pytest --color=no -q --tb=short -o cache_dir=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/cache --basetemp=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/base-full /TopsailAI/src/topsailai/cli/tests/unit/topsailai
```

Stage D — final scoped branch coverage; requires pytest-cov, do not silently drop coverage if unavailable:

```sh
time pytest --color=no -q --tb=short -o cache_dir=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/cache --basetemp=/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/base-coverage --cov=cli_topsailai.runtime_broadcast --cov-branch --cov-report=term-missing --cov-report=json:/TopsailAI/src/topsailai/cli/.tmp/ctx-btw-all/coverage.json --cov-fail-under=94 /TopsailAI/src/topsailai/cli/tests/unit/topsailai/test_runtime_broadcast.py /TopsailAI/src/topsailai/cli/tests/unit/topsailai/test_streaming_broadcast.py
```

Record exact commands, exit codes, passed/failed/skipped counts, elapsed times and coverage after final source changes. Capture any large logs only under the designated temporary directory. No normal verification timeout; diagnose a hang separately and clean up only owned exact processes. Pytest basetemp cleanup must target only its designated test-owned directory.

## Current implementation checkpoints needing verification

Observed during planning, not repaired and not claimed as executed failures:

- `_valid_session` currently does not explicitly reject `(temp)`.
- Broadcast handler currently lacks the approved UTF-8 size/encoding check and reuses a single-target legacy prompt.
- Writer exception handling currently catches BaseException except KeyboardInterrupt, which can swallow SystemExit; evidence/probe ordinary error isolation also needs verification.
- Summary currently prints queued/total rather than all required category counts; candidate announcement and interrupted per-target progress need verification. BroadcastResult.incomplete currently treats every exited skip as incomplete; reconcile with eligible-live-target semantics in the approved design.
- Several startup/fallback hints still list only `/ctx.btw`. Some overview updates were reported incomplete by Developer.

Keep these gates open until focused tests and independent diff review demonstrate conformance; do not redefine acceptance to match current behavior.

## Limitations and acceptance gate

- No tests, coverage or real agent consumption were run in this planning turn.
- Task-log discovery cannot cover PIDs without matching stdout evidence. Queue-only integration cannot establish receiver polling, consumption, cross-agent coordinated action, or exactly-once behavior.
- PID reuse and check/open races remain within trusted per-user task storage assumptions; no authentication or atomic broadcast guarantee.
- Platform liveness and permission-denial behavior are primarily verified via injected observations; live cross-platform behavior requires suitable environments. Public append has no hard write deadline.
- A real multi-agent consumption test is optional only with an isolated available receiver environment and a maintained reproducible script; do not touch production sessions to obtain it.
- Existing dependency availability, full-suite fixture safety and pytest-cov availability remain unverified. Any missing dependency, skip or unsafe fixture is an explicit limitation requiring Reviewer disposition, not a passing test.
- Acceptance requires all applicable checklist items passing, no unresolved blockers, >93% scoped broadcaster coverage, complete per-file diff self-review and independent Reviewer approval. Developer must not commit without authorization.

## Execution evidence ledger

| Stage | Command reference | Result | Elapsed | Counts/coverage | Limitations |
|---|---|---|---|---|---|
| A focused | Repair4 focused command | PASS | 0.19s | 26 passed, 0 failed, 0 skipped | Focused broadcast and dispatcher tests |
| B related | Stage B affected-suite command | PASS | 1.20s | 363 passed, 0 failed, 0 skipped | Used python -m pytest because pytest launcher is broken |
| C full | Final Stage C command | PARTIAL | 12.64s | 2024 passed, 1 failed, 0 skipped | Unchanged child import-path failure in test_live_owner_survives_cli_process_exit; /TopsailAI/src missing from child PYTHONPATH |
| D coverage | Repair4 Coverage.py branch command | PASS | 0.80s | 26 passed; pure branch 39/40 = 97.5% | pytest-cov unavailable; Coverage.py used |
| Gap-focused | Broadcast/UI gap-focused command | PASS | — | 205 passed, 0 failed, 0 skipped | Exact boundary, dispatcher integration, UI routing and interruption tests |
| Independent review | Complete diff and evidence | PENDING | — | — | Required after final test repair |
