---
maintainer: AI
author: DawsonLin
status: planned-not-executed
---

# Manual and live acceptance test plan

## Goal and status

Verify that a human or agent can use the installed topsailai-data skill with the real compiled CLI, preserving existing data. The user requested a comprehensive manual/live plan inspired by BDD, saved under `tests/`. This is a plan, not an execution report: every case starts NOT RUN. Previous BDD runs and data recovery evidence do not count as execution of this plan.

Live means real subprocesses and filesystem rather than mocked APIs. Repeatable checks should become automated live integration or BDD scripts; manual testing covers terminal interaction, human interpretation and exploration. The Given/When/Then tables are specifications, not executable feature files.

## Ordered module index

| Order | Document | Coverage |
|---|---|---|
| A | [Startup and configuration](startup-configuration.md) | Fresh roots, installed binary, environment, help, PTY experience |
| B | [Objects and discovery](objects-discovery.md) | Create/show/update/list/search/tag/move, Hash metadata and independent tags |
| C | [Files and archives](files-archives.md) | All 13 file subcommands, get/put, archives, source precedence and binary integrity |
| D | [Lifecycle and recovery](lifecycle-recovery.md) | Complete state matrix, recover, GC and old-store recovery rehearsal |
| E | [Statistics and concurrency](statistics-concurrency.md) | Counters, ranking, lock custody and independent CLI processes |
| F | [Safety, scale and live acceptance](safety-scale-live.md) | Failures, containment, realistic scale, installed skill and existing-store acceptance |

Run A→B→C→D→E→F after relevant unit/integration behavior is stable. Stop dependent progression on failure; inspect saved output, record an issue and repair/rerun the failed check plus related regressions. Do not rerun blindly or claim independent acceptance when author and executor are the same agent.

## Environment and safety contract

- `I`: isolated fresh root. `C`: isolated verified clone. `F`: disposable fault fixture. `P`: explicitly authorized existing live store, business-read-only. P is never a target for mutation, GC, schema edits, alias injection, retention manipulation or load testing.
- All generated roots, fixtures, synthetic HOME, working directories, reports, logs, archive outputs, caches and test artifacts belong below `.tmp/manual-live/<run-id>/`. Resolve the base and runtime file paths to absolute paths before execution. Paths in these documents are project-relative for portability.
- Give every case a fresh root, unique `ml-<run-id>-<case>` object IDs, an unrelated control object, a separate sentinel store and an external sentinel file. Track created resources explicitly; never reuse unrelated data.
- Record resolved installed skill binary, SHA256, revision/build identity, OS, cwd, selected root and sanitized settings. Establish root isolation before invoking even help: the CLI initializes its manager before command dispatch.
- Build subprocess environments from an allowlist, removing inherited `TOPSAILAI_DATA_*`; set case options explicitly. Use a clean cwd. Do not alter the operator's global environment. Synthetic HOME is required for default-root cases.
- Use the actual installed skill entry as well as the intended build; pin the resolved executable. Source files must use absolute `--from` paths; stdin is only for generated in-memory content with complete arguments. Save binary stdout directly as bytes and stderr separately.
- Normal object operations use the CLI. A narrow read-only layout/hash observer, or reviewed F/C setup helper, may inspect backend structure only for a stated assertion. This is not routine backend exploration and is never allowed to mutate P. If authorization or capability is unavailable, mark BLOCKED.
- P runs use `TOPSAILAI_DATA_TRACK_STAT=0`. Read locks/initialization can still create internal files; document permitted internal effects rather than claiming filesystem-wide immutability without checking it. Confirm the existing layout/root before invoking P.
- No overwriting/deleting original data or old recovery backups. Cleanup requires a reviewed inventory, preview and approval for irreversible removal; log each deletion. No broad shell cleanup or process-name termination. Close streams and stop only exact owned PIDs/sessions.
- Redact credentials and personal content. Restrict raw evidence access; shared reports use hashes, counts and case IDs. Prior recovery backups are not test-owned cleanup artifacts.

## Required execution scripts before running

Scripts listed here are planned deliverables, not existing runnable commands. Select a language and read its rules before implementation. Each manual test must have its procedure implemented/reviewed before execution.

| Planned helper | Responsibility |
|---|---|
| prepare | Validate absolute run boundaries, binary identity, environment, fixtures, controls and manifests; refuse unsafe/nonempty roots except explicit clones |
| run-live | Execute one selected case with exact argv/cwd/settings, binary-safe capture, elapsed time and structured status; no default debugging timeout for normal runs |
| observe-layout | Narrow read-only payload/Hash metadata/tag/stat and integrity checks; no sensitive content dumps |
| fault-fixtures / lock-holder | Clone-only fault setup; actual project-compatible locks, readiness barriers, exact owned process lifecycle; prove fault occurred |
| terminal-start | Only launch the terminal program and expose readiness/startup failures |
| terminal-interact | Separate PTY/tmux interaction, send keys and capture screen/behavior; a pipe is not proof of interactive UX |
| cleanup | Preview inventory, preserve failure evidence/backups, remove only approved owned resources, log removals and recheck sentinels |

Running as root may defeat permission faults. Use an unprivileged sandbox or bounded disposable filesystem and prove the fault; do not fill the host disk, change global permissions or kill unrelated processes.

## Fixtures and independent oracles

Copy useful existing BDD fixtures into the run area. Prepare Markdown with explicit/leading frontmatter/missing/malformed/non-string/empty description, 8 KiB boundary cases, Unicode, LF/CRLF/no final newline and empty content. Prepare numbered lines, overlapping regex matches, a deterministic binary including NUL and 0–255 values, size-limit−1/limit/limit+1 files, nested paths and internal-looking user filenames. Prepare safe and hostile tar variants in F only: marker present/absent, malformed/truncated, traversal, absolute names and link/special entries. Use known-byte manifests (path, size, SHA256), tags, identity, timestamps and statuses calculated before execution, not copied from observed output.

Create active/deleted/ceased states through CLI. Creating/aged/corrupt metadata requires a reviewed F helper; do not invent a public status-setting command. Backups and clone checks must cover every original file, not only visible active objects.

## Case expansion and completion gates

Each row is Given/When/Then. Expand every listed state, value, flag, source and format into a separately recorded variant. `P0` protects safety/basic availability, `P1` covers supported functionality, `P2` covers extended UX/scale/platform checks. Missing helpers or environments mean BLOCKED, not PASS. Unsettled semantics must be resolved before execution, not inferred from one observed result.

Acceptance requires all applicable P0/P1 cases PASS, no unresolved data-loss/containment defect, control integrity and owned-resource cleanup, plus explicit disposition of BLOCKED/P2 checks and known performance limits. Isolated-copy success is not existing-live-store acceptance. Do not imply database/S3, network API, authentication, hostile-race protection or power-loss durability are supported.

## Execution checklist and evidence template

For every variant record case ID, requirement/BDD reference, I/C/F/P, input fixture manifest, expected result and allowed effects before execution. Then save exact argv, cwd, sanitized explicit settings, stdin origin, binary hash/revision, start/end/elapsed time, exit code, stdout/stderr artifact paths, parsed output assertions, post-state/digests, sentinel checks, process/stream cleanup, outcome and issue/rerun links. Outcomes: NOT RUN, PASS, FAIL, BLOCKED, NOT APPLICABLE with reason. Keep artifacts in `.tmp/manual-live/<run-id>/reports/`; save a compact acceptance summary in `.task/`.

Before start: confirm authorization/root, backup where relevant, script review, resources/budgets and expected oracles. Before each module: verify predecessor gates and controls. At end: inspect every failure/skip, review evidence and cleanup inventory, obtain acceptance disposition. This is the test-execution checklist; writing it does not mark it executed.

## BDD traceability

Baseline feature groups: `create`, `show-update`, `list-search`, `tag-move`, `lifecycle-gc`, `file-tool`, `file-archive-marker`, `same-file-input`, `archive-overlap`, `smoke`. `non_smoke` verifies selection rather than another product capability. The BDD README's coverage sentence lags the actual feature inventory; use actual scenarios. Module footers map cases to these groups. Additional live checks cover configuration, the new layout, statistics, locking, failure boundaries, scale and actual installed-skill behavior.
