---
maintainer: human
---
# Test

Enhance unit tests.

Run all of tests via this script: `tests/run_tests.py`

## Test Sequence

- Common Utils
  - logger/
  - utils/
  - human/        -> General methods closely related to humans, such as defining names, identity identifiers, etc.

- Agent Core
  - prompt_hub/   -> Prompt Management & External
  - skill_hub/    -> Skill Management & External
  - tools/        -> Agent can use these Tools
  - context/      -> Context Messages Management
  - ai_base/      -> LLM/Agent Enginering Framework

- Agent Workers
  - ai_team/      -> A team work mode
  - workspace/    -> Worker Entry

## Regression Isolation and Result Attribution

- Editable installations can defeat pristine-snapshot comparisons. Resolve workspace symlinks before treating path strings as separate trees; `/root/ai/TopsailAI` and `/TopsailAI` may identify the same directory. If `PYTHONPATH` cannot provide the package, an editable `.pth` entry can silently import the live checkout.
- Create snapshots from the repository root so package layout is preserved: `git -C /TopsailAI archive <revision> | tar -x -C <tree>`, then set `PYTHONPATH=<tree>/src`. Before tests, prove `topsailai.__file__` and the target module's `__file__` are inside the snapshot, inspect `sys.path` ordering, and compare the revision's Git-blob SHA-256 with the extracted file's SHA-256. Do not run baseline tests if isolation is unproven.
- Verify the archive layout rather than assuming it. Archiving from the project subdirectory can put package contents at the archive root without a `topsailai/` child, making the intended `PYTHONPATH` ineffective and allowing the editable install to supply imports.

## Report Runner Counts at Both Levels

- Record file-level and case-level results separately. Runner summaries can disagree (for example, HEAD reported 410 files with 405 passed and 5 failed, while case totals reported 4 failures and 2 incomplete files; the snapshot reported 375 passed and 35 failed while its case summary reported 12,168 passed and 354 failures). Reconcile discrepancies where possible; otherwise flag them and do not present one aggregate as authoritative.
- A large baseline-versus-HEAD failure gap is a signal to investigate environment, dependency, interpreter, basetemp, and runner differences before claiming code fixed failures. The snapshot's 35 failing files versus 5 at HEAD is not, by itself, evidence of improvement.

## Isolate Failures Before Classification

- Re-run full-runner failures individually before attributing them. Four Hooks unit files that failed in the concurrent full run all passed alone, consistent with runner-concurrency or timing flakiness rather than a confirmed regression.
- Conversely, `test_summary_events_observer_lifecycle.py` and `test_summary_script_directory_lifecycle.py` failed when run alone; their earlier timeout symptoms are not explained by the full-runner timeout budget.
- Check test paths before execution. These lifecycle tests are under `tests/unit/test_topsailai_hooks/`; a wrong path can produce pytest exit 4 with zero tests collected, which is not a test result.

## Distinguish Harness Drift from Product Failures

- For `AttributeError` on a monkeypatched attribute, verify that the production module still exposes that attribute and that the test harness matches the current interface. In this run, `test_llm_request_stat.py` line 32 patches `print_info`, which is absent from `llm_request_stat`.
- For `RuntimeError: generator raised StopIteration`, inspect yield-fixture lifetime and parametrized-case reuse before attributing the failure to business logic. The first-byte BDD failure involved a yield fixture consumed across parametrized cases; isolation reproduced it, but did not alone establish the precise cause.
- Treat these as diagnostic leads, not proof of root cause; preserve unresolved attribution when evidence is incomplete.

## Preserve Read-Only Regression Evidence

- Keep regression logs, snapshots, reports, and other test-only artifacts under `{workspace}/.tmp`.
- For a read-only regression round, verify the live tree remains unchanged (`git status --short` is empty and HEAD is unchanged). Report exact commands, paths, exit codes, elapsed time, file-level and case-level counts, and any unresolved discrepancy. Never infer a test result from a failed command that collected zero tests.
