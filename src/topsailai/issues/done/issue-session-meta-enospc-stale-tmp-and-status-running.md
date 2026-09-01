---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Issue: Session Meta Leaves Stale `.tmp` and Status Stuck at `running` Under Disk-Full (ENOSPC)

## Symptom

An agent session (`topsailai.3305591`, `session_id=""`) terminated abnormally while
working on a production qrew data-hub deployment. Afterwards:

- `/root/.topsailai/workspace/task/topsailai.3305591.session.meta` still reports
  `"status": "running"` and `"end_ts": null`, although the process is dead.
- A stale, zero-byte file `topsailai.3305591.session.meta.tmp` is left behind.
- The error log records:
  ```
  Failed to write session meta to /root/.topsailai/workspace/task/topsailai.3305591.session.meta:
  [Errno 28] No space left on device
  ```

Observed on a filesystem at 97% capacity (remaining ~13 GB).

## Root Cause

`workspace/session_meta.py::_atomic_write` writes atomically via a temporary file plus
`os.replace`:

```python
tmp_path = path + ".tmp"
try:
    ...
    with open(tmp_path, "w", encoding="utf-8") as fd:
        json.dump(data, fd, ensure_ascii=False, indent=2)
        fd.flush()
        os.fsync(fd.fileno())
    os.replace(tmp_path, path)
except Exception as e:
    logger.exception("Failed to write session meta to %s: %s", path, e)
```

Under `ENOSPC`:

1. `open(tmp_path, "w")` succeeds and creates an empty `.tmp` file, but the subsequent
   `json.dump`/`flush`/`fsync` raises `OSError: [Errno 28] No space left on device`.
2. Because the exception fires before `os.replace(tmp_path, path)`, the `.tmp` file is
   never renamed away and stays on disk permanently.
3. `_atomic_write` swallows the exception (by design, "logged but never raised"), so the
   caller cannot detect the failure.
4. The `atexit` handler `_finalize_on_exit` tries to flip `status` from `running` to
   `interrupted` on process exit, but that write also hits `ENOSPC` and fails. The meta
   therefore remains stuck at `"status": "running"` forever, masking the real terminal
   state of the session.

Additionally, `cleanup_session_meta_files()` only globs `*.meta` and never removes stray
`*.meta.tmp` leftovers, so the residue is not reclaimed by routine cleanup.

## Impact

- Misleading session bookkeeping: dead sessions look alive (`running`, no `end_ts`),
  complicating diagnosis of abnormal exits.
- Unbounded accumulation of stale `.tmp` files on a full disk, worsening the very
  condition that caused the failure.
- Silent write failure gives no signal to the agent loop that session state was not
  persisted.

## Suggested Fix (requires human decision — not applied)

Options, in order of preference:

1. On write failure, attempt to remove the partial `tmp_path` in the `except` block so
   no stale `.tmp` residue remains.
2. Extend `cleanup_session_meta_files()` to also prune orphaned `*.meta.tmp` files
   (e.g., older than a threshold), giving a recovery path for already-left residues.
3. Surface the persistence failure to the agent loop (e.g., return a failure status /
   emit a warning) instead of swallowing it, so an abnormal-exit state can be reflected
   promptly rather than depending on a later `atexit` write that may also fail.
4. Have `_finalize_on_exit` tolerate a failed write (it already does) but additionally
   attempt an in-memory/fallback marker so the terminal state is not lost.

## Reproduction

Not reproduced locally yet; inferred from production observation (`topsailai.3305591`)
where the filesystem hit `ENOSPC`. A targeted test should fill the target volume (or stub
`os.replace`/`fsync` to raise `OSError(EACCES/ENOSPC)`) and assert that (a) no `.tmp`
residue remains, and (b) the meta reflects a terminal status rather than `running`.
