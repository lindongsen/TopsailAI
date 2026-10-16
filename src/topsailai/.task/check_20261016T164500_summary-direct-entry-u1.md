---
maintainer: AI
author: DawsonLin
---
# Unit 1 Summary direct entries

Scope: add eight named direct entries and a validated JSON metadata bridge only; preserve business wiring and legacy adapter. Existing shared and point-local observers already accept main(*, hook_context), so preserve them unchanged.

Human decisions: keep shared prepared/trust and application_access libraries; default empty configuration discovers internal resources; Scripts execute directly without summary payload; later business Hook keywords may be removed.

## Checklist

- Validate all eight exact point envelopes and explicit signatures, classification rejection before dispatch, cross-layer stage rejection and inactive phase-two non-export.
- Execute bundled observers in real workers for all eight points with empty configuration; verify validated envelopes through external Modules and direct Scripts, ordering and cleanup.
- Run focused prototype, summary snapshot, point, observer and observer-wiring tests in colorless mode with all artifacts under .tmp.
- Check newly executable statements and branches with coverage; review each changed file diff and preserve unrelated cli/team_agent.py.
- Operation context, deduplication and nested restoration migration remain Unit 2; existing adapter tests must stay green.

## Results

Pending implementation and verification.

Focused run: 374 passed in 9.24s; exit 0. Coverage run: 350 passed in 8.87s; exit 0. Added executable lines: 45/45; no added conditional branches. Whitespace check: git diff --check passed. Per-file production diff reviewed: only additions, no deletions. New test reviewed separately. No source/test edits outside Unit 1; cli/team_agent.py left untouched. Awaiting independent review; no commit/push.

Exact commands use this common environment:
```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/TopsailAI/src/topsailai:/TopsailAI/src:/TopsailAI TOPSAILAI_HOME=/TopsailAI/src/topsailai/.tmp/summary-direct-entry-u1/home TMPDIR=/TopsailAI/src/topsailai/.tmp/summary-direct-entry-u1/tmp NO_COLOR=1
```

```sh
/TopsailAI/.venv/bin/python -m pytest --color=no -q --tb=short -o cache_dir=/TopsailAI/src/topsailai/.tmp/summary-direct-entry-u1/cache --basetemp=/TopsailAI/src/topsailai/.tmp/summary-direct-entry-u1/pytest-temp --junitxml=/TopsailAI/src/topsailai/.tmp/summary-direct-entry-u1/focused.xml /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_direct_entry.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_point_entry_prototype.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_snapshot.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_hook_points.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_events_observer.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_events_observer_wiring.py
```

```sh
COVERAGE_FILE=/TopsailAI/src/topsailai/.tmp/summary-direct-entry-u1/.coverage /TopsailAI/.venv/bin/python -m coverage run --branch --source=topsailai.hooks.points.context -m pytest --color=no -q --tb=short -o cache_dir=/TopsailAI/src/topsailai/.tmp/summary-direct-entry-u1/coverage-cache --basetemp=/TopsailAI/src/topsailai/.tmp/summary-direct-entry-u1/coverage-temp /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_direct_entry.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_snapshot.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_hook_points.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_events_observer.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_events_observer_wiring.py
```
